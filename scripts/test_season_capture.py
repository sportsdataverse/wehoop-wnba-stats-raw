"""Offline tests for the season-level capture planner/writer.

`fetch` is injected, so every path here runs without touching stats.wnba.com.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from season_capture import (  # noqa: E402
    MEASURE_TYPES_LINEUPS,
    MEASURE_TYPES_STATS,
    SEASON_TYPES,
    capture_season,
    payload_path,
    plan_season,
    slug,
    write_payload,
)


def _team_stats_payload(team_ids=(1611661313, 1611661317)):
    return {
        "resultSets": [
            {
                "name": "LeagueDashTeamStats",
                "headers": ["TEAM_ID", "TEAM_NAME"],
                "rowSet": [[t, f"Team {t}"] for t in team_ids],
            }
        ]
    }


def test_plan_covers_every_variant() -> None:
    plan = list(plan_season(2025))
    kinds = [e for e, _v, _k in plan]
    assert kinds.count("leaguedashplayerstats") == len(MEASURE_TYPES_STATS) * len(
        SEASON_TYPES
    )
    assert kinds.count("leaguedashteamstats") == len(MEASURE_TYPES_STATS) * len(
        SEASON_TYPES
    )
    assert kinds.count("leaguedashlineups") == len(MEASURE_TYPES_LINEUPS) * len(
        SEASON_TYPES
    )
    assert kinds.count("leaguegamelog") == len(SEASON_TYPES)
    for one in ("leaguestandingsv3", "commonallplayers", "drafthistory"):
        assert kinds.count(one) == 1, one


def test_plan_variants_are_unique_per_endpoint() -> None:
    """A collision would silently overwrite one capture with another."""
    seen = set()
    for endpoint, variant, _k in plan_season(2025):
        key = (endpoint, variant)
        assert key not in seen, f"duplicate capture key {key}"
        seen.add(key)


def test_lineups_carry_the_group_quantity() -> None:
    """R compiles five-player units; dropping the param silently changes the dataset."""
    for endpoint, _v, kwargs in plan_season(2025):
        if endpoint == "leaguedashlineups":
            assert kwargs["group_quantity"] == 5


def test_every_call_pins_the_wnba_league_id() -> None:
    """LeagueID 10 is WNBA; the endpoints default to NBA if it is omitted."""
    for endpoint, _v, kwargs in plan_season(2025):
        assert kwargs.get("league_id") == "10", endpoint


def test_payload_path_shape(tmp_path: Path) -> None:
    assert payload_path(tmp_path, "leaguedashlineups", 2025, "base_playoffs") == (
        tmp_path / "leaguedashlineups" / "2025" / "base_playoffs.json"
    )
    assert (
        payload_path(tmp_path, "drafthistory", 2025)
        == tmp_path / "drafthistory" / "2025.json"
    )


def test_slug() -> None:
    assert slug("Regular Season") == "regular-season"
    assert slug("FourFactors") == "fourfactors"


def test_write_payload_is_atomic(tmp_path: Path) -> None:
    p = tmp_path / "x" / "y.json"
    write_payload(p, {"a": 1})
    assert json.loads(p.read_text()) == {"a": 1}
    assert not list(tmp_path.rglob(".*.partial"))


def test_capture_writes_then_skips(tmp_path: Path) -> None:
    calls: list[str] = []

    def fetch(endpoint, kwargs):
        calls.append(endpoint)
        return (
            _team_stats_payload()
            if endpoint == "leaguedashteamstats"
            else {"endpoint": endpoint}
        )

    written, skipped, failed = capture_season(2025, tmp_path, fetch)
    assert failed == 0 and skipped == 0 and written == len(calls)
    # 2 teams -> 2 commonteamroster captures beyond the planned set
    assert written == len(list(plan_season(2025))) + 2

    # rerun is fully idempotent: nothing refetched
    before = len(calls)
    written2, skipped2, failed2 = capture_season(2025, tmp_path, fetch)
    assert (written2, failed2) == (0, 0)
    assert skipped2 == written
    assert len(calls) == before, "a second sweep must not refetch anything"


def test_one_failing_endpoint_does_not_abort_the_season(tmp_path: Path) -> None:
    def fetch(endpoint, kwargs):
        if endpoint == "leaguedashlineups":
            raise RuntimeError("upstream 500")
        return (
            _team_stats_payload() if endpoint == "leaguedashteamstats" else {"ok": True}
        )

    written, _skipped, failed = capture_season(2025, tmp_path, fetch)
    assert failed == len(MEASURE_TYPES_LINEUPS) * len(SEASON_TYPES)
    assert written > 0
    assert not (tmp_path / "leaguedashlineups").exists() or not list(
        (tmp_path / "leaguedashlineups").rglob("*.json")
    )


def test_team_roster_ids_come_from_the_team_stats_capture(tmp_path: Path) -> None:
    def fetch(endpoint, kwargs):
        return (
            _team_stats_payload((99,))
            if endpoint == "leaguedashteamstats"
            else {"ok": True}
        )

    capture_season(2025, tmp_path, fetch)
    assert (tmp_path / "commonteamroster" / "2025" / "99.json").exists()

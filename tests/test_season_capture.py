"""Offline tests for the registry + season-level capture.

``fetch`` is injected and the endpoint module is a stub, so everything here runs
without touching stats.{nba,wnba}.com.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from endpoints import (
    ENDPOINT_MEASURE_TYPES,
    LEAGUE_WNBA,
    MEASURE_TYPES,
    PER_MODES,
    SEASON_TYPES,
    discover,
    season_variants,
    slug,
)
from season_capture import (
    _ids_from,
    capture_season,
    game_ids_from_gamelog,
    payload_path,
    plan_season,
    write_payload,
)


# -- a stub league module: signatures are what the registry reads --------------
class StubStats:
    @staticmethod
    def stub_leaguedashteamstats(
        season=None,
        season_type_all_star=None,
        measure_type_detailed_defense=None,
        per_mode_detailed=None,
        league_id=None,
        return_parsed=True,
        proxy_url=None,
    ): ...

    @staticmethod
    def stub_leaguedashplayerstats(
        season=None,
        season_type_all_star=None,
        measure_type_detailed_defense=None,
        per_mode_detailed=None,
        league_id=None,
        return_parsed=True,
    ): ...

    @staticmethod
    def stub_leaguedashteamshotlocations(
        season=None,
        season_type_all_star=None,
        measure_type_simple=None,
        per_mode_detailed=None,
        league_id=None,
        return_parsed=True,
    ): ...

    @staticmethod
    def stub_playergamelogs(
        season_nullable=None,
        season_type_nullable=None,
        measure_type_player_game_logs_nullable=None,
        per_mode_simple_nullable=None,
        league_id=None,
        return_parsed=True,
    ): ...

    @staticmethod
    def stub_leaguedashlineups(
        season=None,
        season_type_all_star=None,
        measure_type_detailed_defense=None,
        per_mode_detailed=None,
        group_quantity=None,
        league_id=None,
        return_parsed=True,
        proxy_url=None,
    ): ...

    @staticmethod
    def stub_leaguestandingsv3(
        season=None, league_id=None, return_parsed=True, proxy_url=None
    ): ...

    @staticmethod
    def stub_leaguegamelog(
        season=None,
        season_type_all_star=None,
        league_id=None,
        return_parsed=True,
        proxy_url=None,
    ): ...

    @staticmethod
    def stub_commonteamroster(
        season=None, team_id=None, league_id=None, return_parsed=True
    ): ...

    @staticmethod
    def stub_playbyplayv3(game_id=None, return_parsed=True, proxy_url=None): ...

    @staticmethod
    def stub_teamgamelog(team_id=None, season=None, return_parsed=True): ...

    @staticmethod
    def stub_playercareerstats(player_id=None, return_parsed=True): ...


def _team_payload(team_ids=(1611661313, 1611661317)):
    return {
        "resultSets": [
            {
                "name": "LeagueDashTeamStats",
                "headers": ["TEAM_ID", "TEAM_NAME"],
                "rowSet": [[t, f"Team {t}"] for t in team_ids],
            }
        ]
    }


# -- registry ------------------------------------------------------------------


def test_discover_splits_game_from_season_and_drops_team_player() -> None:
    game, season = discover(StubStats, "stub")
    assert game == ["playbyplayv3"]
    assert "leaguestandingsv3" in season
    # team-/player-keyed endpoints are a separate capture decision
    assert "teamgamelog" not in season and "playercareerstats" not in season
    assert "commonteamroster" not in season  # team-keyed; scheduled separately


def test_matrix_is_derived_from_the_signature() -> None:
    v = list(season_variants(StubStats.stub_leaguedashteamstats, 2025, LEAGUE_WNBA))
    domain = ENDPOINT_MEASURE_TYPES["leaguedashteamstats"]
    assert len(v) == len(SEASON_TYPES) * len(domain) * len(PER_MODES)
    slugs = [s for s, _k in v]
    assert len(set(slugs)) == len(slugs), "variant slugs must be unique"
    assert "regular-season_base_totals" in slugs


def test_endpoint_without_axes_gets_one_unparameterized_capture() -> None:
    v = list(season_variants(StubStats.stub_leaguestandingsv3, 2025, LEAGUE_WNBA))
    assert len(v) == 1 and v[0][0] is None


def test_only_supported_axes_are_swept() -> None:
    """leaguegamelog has no measure/per-mode, so it must not be swept over them."""
    v = list(season_variants(StubStats.stub_leaguegamelog, 2025, LEAGUE_WNBA))
    assert len(v) == len(SEASON_TYPES)


def test_every_call_pins_season_and_league() -> None:
    for fn in (StubStats.stub_leaguedashteamstats, StubStats.stub_leaguestandingsv3):
        for _v, kwargs in season_variants(fn, 2025, LEAGUE_WNBA):
            assert kwargs["season"] == "2025"
            assert kwargs["league_id"] == LEAGUE_WNBA


def test_pinned_params_are_applied_only_where_accepted() -> None:
    lineups = list(season_variants(StubStats.stub_leaguedashlineups, 2025, LEAGUE_WNBA))
    assert all(k["group_quantity"] == 5 for _v, k in lineups)
    teams = list(season_variants(StubStats.stub_leaguedashteamstats, 2025, LEAGUE_WNBA))
    assert all("group_quantity" not in k for _v, k in teams)


def test_totals_and_pergame_are_both_captured() -> None:
    """Totals is the derivable form; PerGame is what current consumers read."""
    v = list(season_variants(StubStats.stub_leaguedashteamstats, 2025, LEAGUE_WNBA))
    modes = {k["per_mode_detailed"] for _s, k in v}
    assert modes == set(PER_MODES)


def test_slug() -> None:
    assert slug("Regular Season") == "regular-season"
    assert slug("FourFactors") == "fourfactors"


# -- paths + writing -----------------------------------------------------------


def test_payload_path_shape(tmp_path: Path) -> None:
    assert payload_path(tmp_path, "x", 2025, "base_playoffs") == (
        tmp_path / "x" / "2025" / "base_playoffs.json"
    )
    assert payload_path(tmp_path, "x", 2025) == tmp_path / "x" / "2025.json"


def test_write_payload_is_atomic(tmp_path: Path) -> None:
    p = tmp_path / "a" / "b.json"
    write_payload(p, {"a": 1})
    assert json.loads(p.read_text()) == {"a": 1}
    assert not list(tmp_path.rglob(".*.partial"))


def test_plan_keys_are_unique() -> None:
    """A collision would silently overwrite one capture with another."""
    seen = set()
    for endpoint, variant, _k in plan_season(2025, StubStats, "stub", LEAGUE_WNBA):
        assert (endpoint, variant) not in seen
        seen.add((endpoint, variant))


# -- capture -------------------------------------------------------------------


def test_capture_writes_then_skips(tmp_path: Path) -> None:
    calls: list[str] = []

    def fetch(endpoint, kwargs):
        calls.append(endpoint)
        return _team_payload() if endpoint == "leaguedashteamstats" else {"e": endpoint}

    written, skipped, failed = capture_season(
        2025, tmp_path, fetch, StubStats, "stub", LEAGUE_WNBA
    )
    planned = len(list(plan_season(2025, StubStats, "stub", LEAGUE_WNBA)))
    assert failed == 0 and skipped == 0
    assert written == planned + 2  # + one commonteamroster per team

    before = len(calls)
    w2, s2, f2 = capture_season(2025, tmp_path, fetch, StubStats, "stub", LEAGUE_WNBA)
    assert (w2, f2) == (0, 0) and s2 == written
    assert len(calls) == before, "a second sweep must not refetch anything"


def test_one_failing_endpoint_does_not_abort_the_season(tmp_path: Path) -> None:
    def fetch(endpoint, kwargs):
        if endpoint == "leaguedashlineups":
            raise RuntimeError("upstream 500")
        return _team_payload() if endpoint == "leaguedashteamstats" else {"ok": True}

    written, _skipped, failed = capture_season(
        2025, tmp_path, fetch, StubStats, "stub", LEAGUE_WNBA
    )
    assert failed == len(
        list(season_variants(StubStats.stub_leaguedashlineups, 2025, LEAGUE_WNBA))
    )
    assert written > 0


def test_team_roster_ids_come_from_the_team_stats_capture(tmp_path: Path) -> None:
    def fetch(endpoint, kwargs):
        return (
            _team_payload((99,)) if endpoint == "leaguedashteamstats" else {"ok": True}
        )

    capture_season(2025, tmp_path, fetch, StubStats, "stub", LEAGUE_WNBA)
    assert (tmp_path / "commonteamroster" / "2025" / "99.json").exists()


def test_game_ids_from_gamelog_zero_pads() -> None:
    payload = {
        "resultSets": [
            {"headers": ["GAME_ID"], "rowSet": [[1022500001], ["1022500002"]]}
        ]
    }
    assert game_ids_from_gamelog(payload) == ["1022500001", "1022500002"]
    assert game_ids_from_gamelog(None) == []


# -- against the real league modules ------------------------------------------


def test_real_modules_discover_expected_shapes() -> None:
    from sportsdataverse.nba import nba_stats as N
    from sportsdataverse.wnba import wnba_stats as W

    for mod, pre, n_game in ((W, "wnba_stats", 14), (N, "nba_stats", 13)):
        game, season = discover(mod, pre)
        assert len(game) == n_game
        assert len(season) > 30
        assert "playbyplayv3" in game and "boxscoresummaryv2" in game


@pytest.mark.parametrize("league", ["wnba", "nba"])
def test_real_variant_slugs_never_collide(league: str) -> None:
    import importlib

    pre = f"{league}_stats"
    mod = importlib.import_module(f"sportsdataverse.{league}.{pre}")
    lid = "10" if league == "wnba" else "00"
    seen = set()
    for endpoint, variant, _k in plan_season(2025, mod, pre, lid):
        assert (endpoint, variant) not in seen, f"{endpoint}/{variant}"
        seen.add((endpoint, variant))


# ---------------------------------------------------------------------------
# Ported from hoopR-nba-stats-raw. This repo had all the same defects and a
# WORSE empty rate: 3,872 files that were exactly `{}` (3.55% of 108,974,
# five times the NBA sibling's 0.68%).
# ---------------------------------------------------------------------------


def test_measure_types_are_narrowed_to_the_endpoint_domain() -> None:
    """Sweeping every MEASURE_TYPES value over every measure_type* parameter is
    what produced most of this archive's empty payloads. The domains here are
    derived from THIS repo's archive -- they are not the NBA ones. WNBA's
    measure_type_detailed_defense rejects Misc and Four Factors where NBA's
    accepts them, so copying the sibling's table would have been wrong.
    """
    shot = {
        k["measure_type_simple"]
        for _s, k in season_variants(StubStats.stub_leaguedashteamshotlocations, 2025, LEAGUE_WNBA)
    }
    assert shot == {"Base", "Opponent"}

    team = {
        k["measure_type_detailed_defense"]
        for _s, k in season_variants(StubStats.stub_leaguedashteamstats, 2025, LEAGUE_WNBA)
    }
    assert team == set(ENDPOINT_MEASURE_TYPES["leaguedashteamstats"])
    assert "Usage" not in team


def test_endpoints_sharing_a_parameter_keep_their_own_domains() -> None:
    """leaguedashplayerstats supports Usage and leaguedashteamstats does not,
    though both take measure_type_detailed_defense."""
    player = {
        k["measure_type_detailed_defense"]
        for _s, k in season_variants(StubStats.stub_leaguedashplayerstats, 2025, LEAGUE_WNBA)
    }
    assert "Usage" in player


def test_endpoint_override_does_not_leak_into_other_axes() -> None:
    """_SWEEPS also carries season_type and per_mode; an override applied there
    turns one endpoint's matrix into the cube of its measure types."""
    for _s, kwargs in season_variants(StubStats.stub_leaguedashteamstats, 2025, LEAGUE_WNBA):
        assert kwargs["season_type_all_star"] in SEASON_TYPES
        assert kwargs["per_mode_detailed"] in PER_MODES


def test_four_factors_is_not_swept_on_wnba() -> None:
    """Unlike the NBA sibling. A probe of leaguedashteamstats returned an empty
    body for Four Factors while the Base control returned 12 rows in the same
    run, and the archive holds no Four Factors capture to contradict it."""
    assert "Four Factors" not in MEASURE_TYPES


def test_season_is_pinned_even_when_spelled_nullable() -> None:
    """FIVE endpoints here spell it `season_nullable`. The pin tested the bare
    `season` only, so they were called with NO season filter -- which is why
    playergamelogs and teamgamelogs were 100% empty (840 files each)."""
    for _v, kwargs in season_variants(StubStats.stub_playergamelogs, 2025, LEAGUE_WNBA):
        assert kwargs.get("season_nullable") == "2025"
        assert "season" not in kwargs, "must not send a parameter the endpoint lacks"


@pytest.mark.parametrize("payload", [{}, [], None, "", 0, "not-json"])
def test_contentless_payloads_are_refused(payload, tmp_path: Path) -> None:
    path = tmp_path / "e" / "2024" / "v.json"
    assert write_payload(path, payload) is False
    assert not path.exists(), "a contentless payload must leave NO file behind"


@pytest.mark.parametrize(
    "payload",
    [
        {"resource": "leagueleaders", "parameters": {}, "resultSet": {"rowSet": []}},
        {"resource": "x", "parameters": {}, "resultSets": []},
        {"meta": {"version": 1}, "game": {"actions": []}},
    ],
)
def test_empty_but_real_answers_are_persisted(payload, tmp_path: Path) -> None:
    """An envelope with zero rows is a REAL answer and must survive the guard."""
    path = tmp_path / "e" / "2024" / "v.json"
    assert write_payload(path, payload) is True
    assert json.loads(path.read_text(encoding="utf-8")) == payload


def test_capture_counts_an_empty_payload_as_failed_not_written(tmp_path: Path) -> None:
    written, _skipped, failed = capture_season(
        2025, tmp_path, lambda e, k: {}, StubStats, "stub", LEAGUE_WNBA
    )
    assert written == 0
    assert failed > 0
    assert not list(tmp_path.rglob("*.json")), "no file may be left for a retry to skip"


def test_ids_from_survives_every_envelope_shape() -> None:
    """_ids_from used to iterate payload["resultSets"] directly, which is correct
    for only one of the five stats-API envelope families."""
    singular = {
        "resource": "leagueleaders",
        "parameters": {},
        "resultSet": {"headers": ["TEAM_ID"], "rowSet": [[9]]},
    }
    assert _ids_from(singular, "TEAM_ID") == ["9"]

    # resultSets as a DICT: iterating it yields KEYS, so the old code called
    # .get() on a string and raised AttributeError.
    grouped = {
        "resource": "leaguedashteamshotlocations",
        "parameters": {},
        "resultSets": {
            "headers": [{"name": "SHOT_CATEGORY", "columnNames": ["Restricted Area"]}],
            "rowSet": [[1611661313, "Team"]],
        },
    }
    assert _ids_from(grouped, "TEAM_ID") == []

    assert _ids_from({"meta": {"version": 1}, "game": {}}, "TEAM_ID") == []
    short_row = {"resultSets": [{"headers": ["A", "TEAM_ID"], "rowSet": [[1], [2, 3]]}]}
    assert _ids_from(short_row, "TEAM_ID") == ["3"]


def test_skip_endpoints_suppresses_the_request_entirely(tmp_path: Path) -> None:
    """Parking must reach the SEASON-level sweep, not just the per-game pass.

    This gap shipped: `playercompare` was parked with a floor above any real
    season, but capture_season never took a skip list, so every sweep still
    requested all 28 of its variants. Once the request deadline moved to 90s
    that was 42 minutes per season spent on an endpoint known to return
    nothing -- the first backfill run after the port sat on season 1997.
    """
    asked: list[str] = []

    def fetch(endpoint, kwargs):
        asked.append(endpoint)
        return _team_payload() if endpoint == "leaguedashteamstats" else {"e": endpoint}

    capture_season(
        2025,
        tmp_path,
        fetch,
        StubStats,
        "stub",
        LEAGUE_WNBA,
        skip_endpoints={"leaguedashlineups"},
    )
    assert "leaguedashlineups" not in asked, "a skipped endpoint must never be fetched"
    assert "leaguedashteamstats" in asked, "other endpoints must still be swept"
    assert not list((tmp_path / "leaguedashlineups").rglob("*.json"))


def test_skip_endpoints_defaults_to_sweeping_everything() -> None:
    """Omitting the argument must not silently drop endpoints."""
    import inspect

    sig = inspect.signature(capture_season)
    assert sig.parameters["skip_endpoints"].default == frozenset()

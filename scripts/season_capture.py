"""Season-level (non per-game) stats.wnba.com captures for the raw store.

``scrape_raw_json.py`` fills the per-game half of the store through sdv-py's
read-through cache, which keys on ``game_id``. The datasets compiled downstream
in ``wehoop-wnba-stats-data`` also need endpoints that are keyed on
*(season, parameters)* instead: rosters, season stats, lineups, standings, draft.
Those cannot go through the game store, so they land here under

    wnba_stats/json/{endpoint}/{season}/{variant}.json     (parameterized)
    wnba_stats/json/{endpoint}/{season}.json               (no variants)

``variant`` is slugged from only the parameters that actually vary for that
endpoint (e.g. ``advanced_playoffs``), so a filename is readable and stable --
adding an unrelated parameter later must not rename existing captures.

Writes are atomic (tmp + rename) and idempotent: an existing payload is skipped
without parsing, so a sweep is resumable after Ctrl-C.

Rate discipline: every fetch here goes through the same ProxyBonanza rotation and
the same shared stats.wnba.com budget as the per-game sweep. These endpoints are
cheap -- tens of calls per season against thousands for play-by-play -- so they
are fetched **sequentially**; there is nothing to gain from parallelising them and
the budget is shared.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

# Parameter matrices, mirroring the R creation scripts they feed.
# wnba_stats_03 / _05 iterate these seven; _04 (lineups) only the first three.
MEASURE_TYPES_STATS = (
    "Base",
    "Advanced",
    "Misc",
    "Scoring",
    "Usage",
    "Defense",
    "Opponent",
)
MEASURE_TYPES_LINEUPS = ("Base", "Advanced", "FourFactors")
SEASON_TYPES = ("Regular Season", "Playoffs")

# WNBA lineups are captured as five-player units (R: group_quantity = 5).
LINEUP_GROUP_QUANTITY = 5

LEAGUE_ID = "10"


def slug(value: str) -> str:
    """Filename-safe form of a parameter value (``Regular Season`` -> ``regular-season``)."""
    return value.lower().replace(" ", "-").replace("_", "-")


def payload_path(
    root: str | Path, endpoint: str, season: int, variant: str | None = None
) -> Path:
    """Where a season-level capture lives. ``variant=None`` means unparameterized."""
    base = Path(root) / endpoint
    return (
        base / str(season) / f"{variant}.json" if variant else base / f"{season}.json"
    )


def write_payload(path: Path, payload: Any) -> None:
    """Persist ``payload`` atomically, so a killed sweep never leaves half a file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.partial")
    try:
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def game_ids_from_gamelog(payload: Any) -> list[str]:
    """Zero-padded game ids out of a raw ``leaguegamelog`` payload.

    Lets the per-game sweep enumerate from the persisted capture instead of making
    its own parsed call for the same thing.
    """
    if not isinstance(payload, dict):
        return []
    out: set[str] = set()
    for rs in payload.get("resultSets") or []:
        headers = [str(h).upper() for h in rs.get("headers") or []]
        if "GAME_ID" not in headers:
            continue
        idx = headers.index("GAME_ID")
        for row in rs.get("rowSet") or []:
            if row[idx] is not None:
                out.add(str(row[idx]).zfill(10))
    return sorted(out)


def _team_ids_from(payload: Any) -> list[str]:
    """Pull TEAM_ID out of a resultSets payload (used to drive commonteamroster)."""
    if not isinstance(payload, dict):
        return []
    for rs in payload.get("resultSets") or []:
        headers = [str(h).upper() for h in rs.get("headers") or []]
        if "TEAM_ID" not in headers:
            continue
        idx = headers.index("TEAM_ID")
        return sorted(
            {str(row[idx]) for row in rs.get("rowSet") or [] if row[idx] is not None}
        )
    return []


def plan_season(season: int) -> Iterator[tuple[str, str | None, dict[str, Any]]]:
    """Yield ``(endpoint, variant, kwargs)`` for every season-level capture.

    ``commonteamroster`` is absent: it needs team ids that are only known after
    ``leaguedashteamstats`` lands, so :func:`capture_season` schedules it separately.
    """
    ss = str(season)
    for stype in SEASON_TYPES:
        st = slug(stype)
        for mt in MEASURE_TYPES_STATS:
            yield (
                "leaguedashplayerstats",
                f"{slug(mt)}_{st}",
                {
                    "season": ss,
                    "season_type_all_star": stype,
                    "measure_type_detailed_defense": mt,
                    "per_mode_detailed": "PerGame",
                    "league_id": LEAGUE_ID,
                },
            )
            yield (
                "leaguedashteamstats",
                f"{slug(mt)}_{st}",
                {
                    "season": ss,
                    "season_type_all_star": stype,
                    "measure_type_detailed_defense": mt,
                    "per_mode_detailed": "PerGame",
                    "league_id": LEAGUE_ID,
                },
            )
        for mt in MEASURE_TYPES_LINEUPS:
            yield (
                "leaguedashlineups",
                f"{slug(mt)}_{st}",
                {
                    "season": ss,
                    "season_type_all_star": stype,
                    "measure_type_detailed_defense": mt,
                    "per_mode_detailed": "PerGame",
                    "group_quantity": LINEUP_GROUP_QUANTITY,
                    "league_id": LEAGUE_ID,
                },
            )
        # Game index: the per-game sweep already fetches this to enumerate games but
        # discards it; persisting it makes the downstream schedule/game-log datasets
        # buildable offline instead of re-fetching the same thing.
        yield (
            "leaguegamelog",
            st,
            {"season": ss, "season_type_all_star": stype, "league_id": LEAGUE_ID},
        )

    yield (
        "leaguestandingsv3",
        None,
        {"season": ss, "season_type": "Regular Season", "league_id": LEAGUE_ID},
    )
    yield (
        "commonallplayers",
        None,
        {"season": ss, "league_id": LEAGUE_ID, "is_only_current_season": 0},
    )
    yield ("drafthistory", None, {"season_year_nullable": ss, "league_id": LEAGUE_ID})


def capture_season(
    season: int,
    root: str | Path,
    fetch: Callable[[str, dict[str, Any]], Any],
    log: Callable[[str], None] = lambda _m: None,
) -> tuple[int, int, int]:
    """Fetch every season-level payload for ``season``. Returns (written, skipped, failed).

    ``fetch(endpoint, kwargs)`` performs one call and returns the raw payload; the
    caller supplies it so proxy rotation and transport stay in the scraper and this
    module remains offline-testable.
    """
    written = skipped = failed = 0
    team_source: Any = None

    for endpoint, variant, kwargs in plan_season(season):
        path = payload_path(root, endpoint, season, variant)
        if path.exists():
            skipped += 1
            if endpoint == "leaguedashteamstats" and variant == "base_regular-season":
                team_source = json.loads(path.read_text(encoding="utf-8"))
            continue
        try:
            payload = fetch(endpoint, kwargs)
        except Exception as exc:  # noqa: BLE001 - one endpoint gap must not kill the season
            log(f"season {season} {endpoint}[{variant}]: {exc}")
            failed += 1
            continue
        write_payload(path, payload)
        written += 1
        if endpoint == "leaguedashteamstats" and variant == "base_regular-season":
            team_source = payload

    # commonteamroster is per (season, team); team ids come from the Base team-stats
    # capture above rather than a second index call.
    for team_id in _team_ids_from(team_source):
        path = payload_path(root, "commonteamroster", season, team_id)
        if path.exists():
            skipped += 1
            continue
        try:
            payload = fetch(
                "commonteamroster",
                {"season": str(season), "team_id": team_id, "league_id": LEAGUE_ID},
            )
        except Exception as exc:  # noqa: BLE001
            log(f"season {season} commonteamroster[{team_id}]: {exc}")
            failed += 1
            continue
        write_payload(path, payload)
        written += 1

    return written, skipped, failed

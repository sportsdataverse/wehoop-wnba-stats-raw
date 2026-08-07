"""Schedule master: universe, capture flags, scrape state, coverage roll-up.

Offline, fixture-backed: builds a miniature raw tree in ``tmp_path`` and
asserts the master's schema equals the universe (yearly) schema plus the
documented extras — ``has_<endpoint>`` per game-keyed endpoint and the four
scrape-state columns. WNBA-specific: seasons are bare calendar years and game
ids carry the "10" league prefix.
"""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl
import pytest
from schedule_master import (
    _UNIVERSE_SCHEMA,
    GAME_FILE_RE,
    SCRAPE_STATE_COLUMNS,
    build_coverage,
    build_master,
    load_universe,
    reconcile,
    walk_raw_tree,
)

GID_REG_1 = "1022300001"
GID_REG_2 = "1022300002"
GID_PLAYOFF = "1042300101"
GID_ORPHAN = "1022399999"  # in the tree, not in the schedule universe


def _lgl_payload(rows: list[list]) -> str:
    return json.dumps(
        {
            "resource": "leaguegamelog",
            "resultSets": [
                {
                    "name": "LeagueGameLog",
                    "headers": [
                        "SEASON_ID",
                        "TEAM_ID",
                        "TEAM_ABBREVIATION",
                        "GAME_ID",
                        "GAME_DATE",
                        "MATCHUP",
                    ],
                    "rowSet": rows,
                }
            ],
        }
    )


@pytest.fixture()
def tree(tmp_path: Path) -> Path:
    root = tmp_path / "json"
    lgl = root / "leaguegamelog" / "2023"
    lgl.mkdir(parents=True)
    (lgl / "regular-season.json").write_text(
        _lgl_payload(
            [
                ["22023", 1611661319, "LVA", GID_REG_1, "2023-05-19", "LVA vs. SEA"],
                ["22023", 1611661328, "SEA", GID_REG_1, "2023-05-19", "SEA @ LVA"],
                ["22023", 1611661313, "NYL", GID_REG_2, "2023-05-19", "NYL vs. WAS"],
                ["22023", 1611661322, "WAS", GID_REG_2, "2023-05-19", "WAS @ NYL"],
            ]
        )
    )
    (lgl / "playoffs.json").write_text(
        _lgl_payload(
            [
                ["42023", 1611661319, "LVA", GID_PLAYOFF, "2023-09-29", "LVA vs. NYL"],
                ["42023", 1611661313, "NYL", GID_PLAYOFF, "2023-09-29", "NYL @ LVA"],
            ]
        )
    )
    # Player-level variant must be skipped, or its game would double in.
    (lgl / "regular-season_p.json").write_text(
        _lgl_payload([["22023", 1, "XXX", "1029999999", "2023-05-19", "XXX vs. YYY"]])
    )

    pbp = root / "playbyplayv3" / "2023"
    pbp.mkdir(parents=True)
    (pbp / f"{GID_REG_1}.json").write_text('{"game": {"actions": [1]}}')  # ok
    (pbp / f"{GID_REG_2}.json").write_text("{}")  # 2 bytes -> error
    (pbp / f"{GID_ORPHAN}.json").write_text('{"game": {}}')  # orphan
    # GID_PLAYOFF absent -> missing

    box = root / "boxscoretraditionalv3" / "2023"
    box.mkdir(parents=True)
    (box / f"{GID_REG_1}.json").write_text("{}")

    # Variant endpoints: no game key, so no has_* flag — endpoint index only.
    tgl = root / "teamgamelogs" / "2023"
    tgl.mkdir(parents=True)
    (tgl / "regular-season_totals.json").write_text("{}")
    draft = root / "drafthistory"
    draft.mkdir(parents=True)
    (draft / "2023.json").write_text("{}")  # flat per-season payload shape
    return root


def test_universe_rows_and_dtypes(tree):
    universe = load_universe(tree)
    assert universe.height == 3
    assert universe.schema["game_id"] == pl.Utf8
    assert universe.schema["game_date"] == pl.Date
    assert set(universe["game_id"].to_list()) == {GID_REG_1, GID_REG_2, GID_PLAYOFF}


def test_season_is_a_bare_calendar_year_from_season_id(tree):
    """WNBA season format: SEASON_ID "22023" -> "2023", never a "2023-24" span."""
    universe = load_universe(tree)
    assert universe["season"].unique().to_list() == ["2023"]
    row = universe.filter(pl.col("game_id") == GID_PLAYOFF).to_dicts()[0]
    assert row["season_type"] == "playoffs"
    assert row["home_team_abbreviation"] == "LVA"
    assert row["away_team_abbreviation"] == "NYL"


def test_player_variant_files_are_skipped(tree):
    universe = load_universe(tree)
    assert "1029999999" not in universe["game_id"].to_list()


def test_game_keyed_classification(tree):
    endpoint_gids, _stats, index = walk_raw_tree(tree)
    assert set(endpoint_gids) == {"playbyplayv3", "boxscoretraditionalv3"}
    # Variant endpoints still appear in the per-(endpoint, season) index.
    assert index.filter(pl.col("endpoint") == "teamgamelogs").height == 1
    assert index.filter(pl.col("endpoint") == "drafthistory")["season"].to_list() == ["2023"]


def test_nba_prefixed_game_files_are_not_wnba_games():
    """The "00" NBA prefix must not match: the id namespaces are disjoint."""
    assert GAME_FILE_RE.match("0022300001.json") is None
    assert GAME_FILE_RE.match("1022300001.json") is not None


def test_master_schema_is_universe_plus_documented_extras(tree):
    universe = load_universe(tree)
    endpoint_gids, stats, _index = walk_raw_tree(tree)
    master = build_master(universe, endpoint_gids, stats)
    extras = {f"has_{ep}" for ep in endpoint_gids} | set(SCRAPE_STATE_COLUMNS)
    assert set(master.columns) == set(_UNIVERSE_SCHEMA) | extras
    assert master.columns == sorted(master.columns)  # pinned order
    assert master.schema["game_id"] == pl.Utf8


def test_flags_and_scrape_status_reflect_the_tree(tree):
    universe = load_universe(tree)
    endpoint_gids, stats, _index = walk_raw_tree(tree)
    master = build_master(universe, endpoint_gids, stats).sort("game_id")
    by_gid = {r["game_id"]: r for r in master.to_dicts()}
    assert by_gid[GID_REG_1]["has_playbyplayv3"] is True
    assert by_gid[GID_REG_1]["has_boxscoretraditionalv3"] is True
    assert by_gid[GID_REG_1]["scrape_status"] == "ok"
    assert by_gid[GID_REG_2]["scrape_status"] == "error"  # empty-{} payload
    assert by_gid[GID_PLAYOFF]["has_playbyplayv3"] is False
    assert by_gid[GID_PLAYOFF]["scrape_status"] == "missing"
    assert by_gid[GID_PLAYOFF]["json_bytes"] is None
    assert by_gid[GID_REG_1]["json_bytes"] > 2
    assert by_gid[GID_REG_1]["json_captured_at"] is not None
    assert by_gid[GID_REG_1]["last_scraped_at"] == by_gid[GID_REG_1]["json_captured_at"]


def test_coverage_grain_and_rates(tree):
    universe = load_universe(tree)
    endpoint_gids, stats, _index = walk_raw_tree(tree)
    coverage = build_coverage(build_master(universe, endpoint_gids, stats))
    assert coverage.height == 2  # (2023, playoffs) + (2023, regular_season)
    reg = coverage.filter(pl.col("season_type") == "regular_season").to_dicts()[0]
    assert reg["n_games"] == 2
    assert reg["pct_captured"] == 0.5  # one ok, one empty-{} error
    assert reg["pct_has_playbyplayv3"] == 1.0
    assert str(reg["first_date"]) == "2023-05-19"


def test_reconcile_reports_orphan_files(tree):
    universe = load_universe(tree)
    endpoint_gids, _stats, _index = walk_raw_tree(tree)
    report = reconcile(universe, endpoint_gids)
    pbp = report.filter(pl.col("endpoint") == "playbyplayv3").to_dicts()[0]
    assert pbp["n_orphans"] == 1  # GID_ORPHAN
    assert pbp["n_flagged"] == 2

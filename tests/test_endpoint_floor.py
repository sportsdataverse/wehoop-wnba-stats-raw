"""Tests for the per-endpoint season floor."""

from __future__ import annotations

from scrape_raw_json import ENDPOINT_MIN_SEASON, _skip_endpoint


def test_gamerotation_is_skipped_below_the_floor() -> None:
    assert _skip_endpoint("gamerotation", 2015)
    assert _skip_endpoint("gamerotation", 1997)


def test_gamerotation_runs_at_and_above_the_floor() -> None:
    floor = ENDPOINT_MIN_SEASON["gamerotation"]
    assert not _skip_endpoint("gamerotation", floor)
    assert not _skip_endpoint("gamerotation", floor + 5)


def test_other_endpoints_are_never_skipped() -> None:
    for season in (1997, 2015, 2026):
        assert not _skip_endpoint("playbyplayv3", season)
        assert not _skip_endpoint("boxscoretraditionalv3", season)


def test_wnba_measured_floors() -> None:
    """Rows-measured (archive scan 2026-08-02): tracking-provider era starts
    2023 for ptdefend/seasonmatchups; game-log rows begin 2018. All are genuine
    no-data eras -- the WNBA single-year season format was always correct."""
    for ep, floor in (
        ("leaguedashptdefend", 2023),
        ("leagueseasonmatchups", 2023),
        ("playergamelogs", 2018),
        ("teamgamelogs", 2000),
    ):
        assert _skip_endpoint(ep, floor - 1), f"{ep} must skip below {floor}"
        assert not _skip_endpoint(ep, floor), f"{ep} must sweep at {floor}"

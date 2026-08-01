"""Tests for the per-period boxscore window (WNBA time math).

The window is the whole point of this capture: request the wrong tick and the
endpoint still returns a well-formed boxscore, just for the wrong moment. Nothing
downstream would flag it, so the arithmetic is pinned explicitly here -- including
against the NBA values and the other WNBA era, both of which it must NOT equal.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest
from period_capture import (
    MAX_PERIODS,
    OT_PERIOD_SECONDS,
    QUARTERS_FROM_SEASON,
    period_elapsed_seconds,
    period_start_range,
    periods_in_game,
    regulation_shape,
    season_of,
)

REAL_PBP = (
    Path(__file__).resolve().parent.parent / "wnba_stats" / "json" / "playbyplayv3"
)
needs_store = pytest.mark.skipif(
    not REAL_PBP.is_dir(), reason="no captured play-by-play"
)


# -- era shape ---------------------------------------------------------------


def test_quarters_era_is_four_ten_minute_periods() -> None:
    assert regulation_shape(2006) == (4, 600)
    assert [period_elapsed_seconds(p, 2025) for p in (1, 2, 3, 4)] == [
        0,
        600,
        1200,
        1800,
    ]


def test_halves_era_is_two_twenty_minute_periods() -> None:
    assert regulation_shape(2005) == (2, 1200)
    assert [period_elapsed_seconds(p, 1998) for p in (1, 2)] == [0, 1200]


def test_the_two_eras_disagree_from_period_two() -> None:
    """Period 2 opens ten minutes apart; regulation totals match, so only this catches it."""
    assert period_elapsed_seconds(2, 2005) != period_elapsed_seconds(2, 2006)
    assert period_elapsed_seconds(2, 2005) - period_elapsed_seconds(2, 2006) == 600
    # regulation is 2400s either way -- a total-length check would pass a mix-up
    for season in (2005, 2006):
        periods, per_period = regulation_shape(season)
        assert periods * per_period == 2400


def test_overtime_follows_regulation_in_both_eras() -> None:
    for season in (1998, 2025):
        periods, _ = regulation_shape(season)
        assert period_elapsed_seconds(periods + 1, season) == 2400
        assert period_elapsed_seconds(periods + 2, season) == 2400 + OT_PERIOD_SECONDS


def test_window_is_never_the_nba_window() -> None:
    """Guard against someone swapping in sdv-py's 12-minute-quarter helper."""
    for season in (1998, 2025):
        for period in (2, 3, 4, 5):
            nba = (period - 1) * 720 if period <= 4 else 2880 + (period - 5) * 300
            assert period_elapsed_seconds(period, season) != nba, (season, period)


def test_start_range_is_tenths_with_a_one_second_window() -> None:
    assert period_start_range(1, 2025) == ("0", "10")
    assert period_start_range(2, 2025) == ("6000", "6010")
    assert period_start_range(2, 1998) == ("12000", "12010")


# -- period discovery --------------------------------------------------------


def test_periods_in_game_reads_the_max_period() -> None:
    assert periods_in_game({"game": {"actions": [{"period": 1}, {"period": 4}]}}) == 4


def test_periods_in_game_sees_overtime() -> None:
    """A fixed period count would silently truncate every OT game."""
    assert periods_in_game({"game": {"actions": [{"period": 4}, {"period": 6}]}}) == 6


def test_periods_in_game_tolerates_garbage() -> None:
    for bad in (None, {}, {"game": {}}, {"game": {"actions": [{"noperiod": 1}]}}):
        assert periods_in_game(bad) == 0


def test_periods_in_game_is_bounded() -> None:
    assert periods_in_game({"game": {"actions": [{"period": 999}]}}) == MAX_PERIODS


def test_season_of() -> None:
    assert season_of("1022600071") == 2026
    assert season_of("1029700031") == 1997


# -- against the real store --------------------------------------------------


@needs_store
def test_real_games_match_their_eras_period_count() -> None:
    """Every captured season's modal period count must match the era shape.

    This is the check that caught the halves era in the first place.
    """
    for season_dir in sorted(p for p in REAL_PBP.iterdir() if p.is_dir()):
        season = int(season_dir.name)
        files = list(season_dir.glob("*.json"))[:25]
        if not files:
            continue
        counts = Counter()
        for f in files:
            n = periods_in_game(json.loads(f.read_text(encoding="utf-8")))
            if n:
                counts[n] += 1
        assert counts, season
        modal = counts.most_common(1)[0][0]
        expected, _ = regulation_shape(season)
        assert modal == expected, (
            f"season {season}: modal {modal} periods, era expects {expected}"
        )


@needs_store
def test_game_ids_decode_to_their_directory_season() -> None:
    for season_dir in sorted(p for p in REAL_PBP.iterdir() if p.is_dir())[:8]:
        for path in list(season_dir.glob("*.json"))[:10]:
            assert season_of(path.stem) == int(season_dir.name)


@needs_store
def test_the_era_boundary_is_where_the_data_says_it_is() -> None:
    """Pin QUARTERS_FROM_SEASON to the observed switch, not to a remembered year."""

    def modal(season: int) -> int:
        d = REAL_PBP / str(season)
        counts = Counter(
            periods_in_game(json.loads(f.read_text(encoding="utf-8")))
            for f in list(d.glob("*.json"))[:25]
        )
        return counts.most_common(1)[0][0]

    assert modal(QUARTERS_FROM_SEASON - 1) == 2
    assert modal(QUARTERS_FROM_SEASON) == 4

"""Per-period boxscore capture — the quarter-box lineup grounding, WNBA time math.

``boxscoretraditionalv3`` accepts a ``RangeType=2`` request window; asking for the
one-second window at a period's opening tick returns exactly the players on court
when that period began. Those captures are what let a downstream builder
reconstruct on-court lineups from period starts + substitutions, instead of
inferring them from play-by-play alone. hoopR-nba-stats-raw carries the same
capture as ``boxscoretraditionalv3_period``; this is the WNBA half.

**The window is league-specific and sdv-py's helper is NBA-only.**
``sportsdataverse.nba.nba_lineups._period_start_range`` computes

    elapsed_s = (period - 1) * 720 if period <= 4 else 2880 + (period - 5) * 300

which is 12-minute quarters. The WNBA has never played those, so reusing it would
request a window minutes into every period from the 2nd on and silently ground
lineups on the wrong tick -- a plausible-looking boxscore for the wrong moment
rather than a failure. Do not swap in the NBA helper.

The WNBA also changed its own format: **two 20-minute halves through 2005, four
10-minute quarters from 2006**. Regulation is 2400s in both eras, so a
regulation-total check would not catch a mix-up, but the period boundaries differ
by ten minutes. The window therefore depends on the season, not just the period,
which is why :func:`period_elapsed_seconds` takes one and refuses to default it.

Period count comes from the play-by-play payload already in the store, so a game's
overtime periods cost no extra request to discover.
"""

from __future__ import annotations

from typing import Any

#: The WNBA switched from two 20-minute halves to four 10-minute quarters in 2006.
#: Confirmed from the captured play-by-play: every season 1997-2005 has a modal max
#: period of 2 and opens at ``PT20M00.00S``; 2006 onward is 4 periods at
#: ``PT10M00.00S``. Regulation is 2400s in both eras, but the *period boundaries*
#: are completely different -- treating a 1998 game as 10-minute quarters puts the
#: period-2 window ten minutes before that period actually starts.
QUARTERS_FROM_SEASON = 2006

HALVES_PERIOD_SECONDS = 1200
HALVES_PERIODS = 2
QUARTERS_PERIOD_SECONDS = 600
QUARTERS_PERIODS = 4

#: Overtime is 5 minutes in both eras.
OT_PERIOD_SECONDS = 300

#: ``RangeType=2`` selects an explicit Start/EndRange window (pbpstats convention).
QUARTER_BOX_RANGE_TYPE = "2"

#: One-second opening window, in tenths -- same width sdv-py and pbpstats use.
WINDOW_WIDTH_TENTHS = 10

#: Guard against a malformed payload driving an unbounded fetch loop.
MAX_PERIODS = 12


def regulation_shape(season: int) -> tuple[int, int]:
    """``(periods, seconds_per_period)`` for ``season``'s regulation format."""
    if season >= QUARTERS_FROM_SEASON:
        return QUARTERS_PERIODS, QUARTERS_PERIOD_SECONDS
    return HALVES_PERIODS, HALVES_PERIOD_SECONDS


def period_elapsed_seconds(period: int, season: int) -> int:
    """Game seconds elapsed when ``period`` (1-indexed) opens in ``season``.

    ``season`` is required rather than defaulted: the halves/quarters split makes a
    silent default wrong for a third of league history, and a wrong window returns a
    well-formed boxscore for the wrong moment rather than an error.
    """
    periods, per_period = regulation_shape(season)
    if period <= periods:
        return (period - 1) * per_period
    return periods * per_period + (period - periods - 1) * OT_PERIOD_SECONDS


def period_start_range(period: int, season: int) -> tuple[str, str]:
    """``(StartRange, EndRange)`` in tenths of a second at ``period``'s opening tick."""
    start = period_elapsed_seconds(period, season) * 10
    return str(start), str(start + WINDOW_WIDTH_TENTHS)


def periods_in_game(pbp_payload: Any) -> int:
    """Highest period number in a captured ``playbyplayv3`` payload (0 if unknown).

    Reading it off the stored play-by-play means overtime is discovered for free --
    fetching a fixed four periods would miss OT, and probing for it would spend a
    request per game to find out.
    """
    if not isinstance(pbp_payload, dict):
        return 0
    actions = (pbp_payload.get("game") or {}).get("actions") or []
    periods = [a.get("period") for a in actions if isinstance(a, dict)]
    valid = [
        int(p) for p in periods if isinstance(p, (int, float, str)) and str(p).isdigit()
    ]
    return min(max(valid), MAX_PERIODS) if valid else 0


def season_of(game_id: str) -> int:
    """Season (single calendar year) encoded in a 10-digit WNBA game id.

    ``1022600071`` -> 2026. Digits 3-4 are the two-digit year; >= 90 is 19xx.
    Needed here because the request window depends on which era the game is from.
    """
    gid = str(game_id).zfill(10)
    yy = int(gid[3:5])
    return 1900 + yy if yy >= 90 else 2000 + yy

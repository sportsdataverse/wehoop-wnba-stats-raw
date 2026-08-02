"""Declarative capture registry for the stats.{nba,wnba}.com surface.

One module drives both leagues and both raw repos; only ``league_id`` differs.

Rather than hand-maintaining ~90 endpoint entries and their parameter matrices,
the matrix for each endpoint is **derived from its own signature**: an endpoint
that accepts a ``season_type*`` parameter gets swept over season types, one that
accepts ``measure_type*`` over measure types, and so on. A new endpoint appearing
upstream is therefore captured at the right granularity with no edit here, and an
endpoint that drops a parameter stops being swept over it instead of 400-ing.

Granularity choices, made for reuse rather than for any one current consumer:

* **Game endpoints** are captured whole-game, one payload per game per endpoint.
  Anything narrower (period, range) is a strict subset that can be re-requested,
  and the per-period capture already exists separately for lineup grounding.
* **Season endpoints** are captured at ``Totals`` *and* ``PerGame``. Totals is the
  information-dense form -- PerGame, Per36 and Per100 are all derivable from it --
  but the currently published datasets are PerGame, and deriving them would
  introduce rounding differences against what consumers already read. Season-level
  calls are cheap enough (tens per season, against thousands per season of games)
  that capturing both removes the question entirely.
* Every call pins ``season`` and ``league_id`` explicitly rather than relying on
  upstream defaults, which are undocumented and free to drift.

Capturing a superset is deliberate: a payload already on disk costs nothing to
reshape later, while a payload never captured means re-sweeping a decade.
"""

from __future__ import annotations

import inspect
from collections.abc import Iterator
from typing import Any, Callable

LEAGUE_NBA = "00"
LEAGUE_WNBA = "10"

SEASON_TYPES = ("Regular Season", "Playoffs")
#: Every measure type the sweep may request.
#:
#: "Four Factors" was excluded here until 2026-08-02 on the strength of ONE
#: live probe -- which turned out to be throttle-corrupted, the exact trap the
#: interrogation notes warn about ("never conclude a domain from a live probe
#: under load"). A calm re-probe with passing controls measured real Four
#: Factors data across the team side AND the clutch/lineup family:
#: teamstats 12 rows, teamclutch 12, playerclutch 134, lineups 2,000,
#: lineupviz 2,865. leaguedashplayerstats answers a valid ZERO-ROW envelope --
#: a real "no data" answer, which by this module's own doctrine belongs in the
#: domain (only unparseable {} responses mark an unsupported value).
MEASURE_TYPES = (
    "Base",
    "Advanced",
    "Misc",
    "Four Factors",
    "Scoring",
    "Usage",
    "Defense",
    "Opponent",
)
PER_MODES = ("Totals", "PerGame")

#: Sub-dimension axes. These endpoints take a REQUIRED extra axis; before
#: 2026-08-02 the sweep left each at its wrapper default, so the archive held
#: one slice of a much larger surface: synergyplaytypes = Isolation/Offensive
#: only (1 of 22), leaguedashptstats = Drives only (1 of 12), leaguedashptdefend
#: = Overall only (1 of 6). Values from nba_api parameters.py (PtMeasureType /
#: DefenseCategory / PlayType classes) -- the API's own domain model.
PT_MEASURE_TYPES = (
    "SpeedDistance",
    "Rebounding",
    "Possessions",
    "CatchShoot",
    "PullUpShot",
    "Defense",
    "Drives",
    "Passing",
    "ElbowTouch",
    "PostTouch",
    "PaintTouch",
    "Efficiency",
)
DEFENSE_CATEGORIES = (
    "Overall",
    "3 Pointers",
    "2 Pointers",
    "Less Than 6Ft",
    "Less Than 10Ft",
    "Greater Than 15Ft",
)
#: Synergy spellings are the API's own: PRBallHandler / PRRollman, and
#: putbacks are "OffRebound".
PLAY_TYPES = (
    "Transition",
    "Isolation",
    "PRBallHandler",
    "PRRollman",
    "Postup",
    "Spotup",
    "Handoff",
    "Cut",
    "OffScreen",
    "OffRebound",
    "Misc",
)
TYPE_GROUPINGS = ("Offensive", "Defensive")

#: Season-level endpoints that must never be swept per-season.
#: scoreboardv3 is DATE-keyed (GameDate=YYYY-MM-DD); sweeping it per season
#: captured the wrapper's fixed default date over and over -- one junk file per
#: season. Its content (the day's games) is fully covered by the per-game
#: endpoints. Excluded in discover(), the single registry gate.
#: shotchartlineupdetail is LINEUP-keyed: it requires a GroupID (a 5-man
#: lineup id) and the roxygen-mined default pinned one specific lineup, so
#: every "season" capture was one lineup's shots. A season sweep cannot
#: enumerate lineups; per-lineup capture is an entity-iteration design.
EXCLUDED_SEASON_ENDPOINTS = frozenset({"scoreboardv3", "shotchartlineupdetail"})

#: Measure-type values each PARAMETER accepts, the default for endpoints with no
#: entry in ENDPOINT_MEASURE_TYPES below.
#:
#: Sweeping every MEASURE_TYPES value over every ``measure_type*`` parameter is
#: what produced most of this archive's empty payloads: the endpoint accepts the
#: parameter, but the API answers an unsupported value with a body that does not
#: parse, and that ``{}`` was persisted and never retried.
MEASURE_TYPE_DOMAINS: dict[str, tuple[str, ...]] = {
    # 5 of the 7 values were empty in EVERY season -- exactly the 71.4% empty
    # rate both shot-locations endpoints showed, identical in NBA and WNBA.
    "measure_type_simple": ("Base", "Opponent"),
    "measure_type_detailed_defense": MEASURE_TYPES,
    "measure_type_player_game_logs_nullable": (
        "Base",
        "Advanced",
        "Misc",
        "Scoring",
        "Usage",
    ),
}

#: Per-ENDPOINT narrowing, applied on top of the parameter default.
#:
#: The domain is not purely a property of the parameter: leaguedashteamstats and
#: leaguedashplayerstats both take ``measure_type_detailed_defense``, but only
#: the team one rejects Usage. Keying solely by parameter name would drop Usage
#: from leaguedashlineups / leaguedashplayerclutch / leaguedashplayerstats /
#: leaguedashteamclutch / leaguelineupviz, all of which support it.
#:
#: Derived by scanning this repo's committed archive -- a measure empty in EVERY
#: captured season is unsupported, one populated in any season is supported.
#: That is a far larger and more stable sample than live probing, which throttles
#: and returns inconsistent negatives (a probe run reported "Base is empty" for
#: an endpoint whose archive holds hundreds of populated Base captures).
ENDPOINT_MEASURE_TYPES: dict[str, tuple[str, ...]] = {
    "leaguedashteamstats": tuple(m for m in MEASURE_TYPES if m != "Usage"),
    "teamgamelogs": ("Base", "Advanced", "Misc", "Scoring"),
}

#: Season / league parameters, most-specific first. Matched by EXACT name from
#: this list rather than by prefix: prefix-matching "season" would also hit
#: ``season_segment_nullable`` and ``season_type_*``. The previous code tested
#: only the bare ``season``, so the FIVE endpoints spelling it ``season_nullable``
#: (assisttracker, leaguegamefinder, playergamelogs, playergamestreakfinder,
#: teamgamelogs) were called with NO season filter at all -- which is why
#: playergamelogs and teamgamelogs were 100% empty. ``leaguestandingsv3`` accepts
#: both, and the order here picks the non-nullable one.
_SEASON_PARAMS = ("season", "season_nullable", "season_year")
_LEAGUE_PARAMS = ("league_id", "league_id_nullable")


def measure_types_for(fn_name: str, param: str, default: tuple[str, ...]) -> tuple[str, ...]:
    """Values to sweep for ``param`` on the endpoint behind ``fn_name``.

    Endpoint override beats parameter default beats the caller's full list.

    ``fn_name`` is the wrapper's full name (``wnba_stats_leaguedashteamstats``),
    matched by SUFFIX. Splitting on the first underscore would be wrong -- the
    league prefix itself contains one -- and this function has no access to the
    prefix ``discover()`` used.
    """
    # Guard the axis. _SWEEPS also carries season_type and per_mode, and an
    # endpoint override applied to those would set season_type_all_star="Base"
    # and per_mode_detailed="Misc" -- silently turning one endpoint's matrix
    # into the cube of its measure types.
    if not param.startswith("measure_type"):
        return default
    for endpoint, values in ENDPOINT_MEASURE_TYPES.items():
        if fn_name == endpoint or fn_name.endswith(f"_{endpoint}"):
            return values
    return MEASURE_TYPE_DOMAINS.get(param, default)


#: Lineups are five-player units; the endpoint also accepts 2-4 but the published
#: datasets are 5-man and the smaller units are a much larger combinatorial space.
LINEUP_GROUP_QUANTITY = 5

#: Parameter-name prefix -> the values to sweep it over. Prefix-matched because the
#: same concept is spelled differently per endpoint (``season_type_all_star``,
#: ``season_type_playoffs``, ``season_type_nullable``).
_SWEEPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("season_type", SEASON_TYPES),
    ("measure_type", MEASURE_TYPES),
    ("pt_measure_type", PT_MEASURE_TYPES),
    ("defense_category", DEFENSE_CATEGORIES),
    ("play_type", PLAY_TYPES),
    ("type_grouping", TYPE_GROUPINGS),
    ("per_mode", PER_MODES),
)

#: Parameters pinned to a single value when the endpoint accepts them.
_PINS: tuple[tuple[str, Any], ...] = (("group_quantity", LINEUP_GROUP_QUANTITY),)


def _params(fn: Callable[..., Any]) -> set[str]:
    try:
        return set(inspect.signature(fn).parameters)
    except (TypeError, ValueError):
        return set()


def _match(params: set[str], prefix: str) -> str | None:
    """The endpoint's own spelling of a swept parameter, if it accepts one."""
    for name in sorted(params):
        if name.startswith(prefix):
            return name
    return None


def slug(value: Any) -> str:
    """Filename-safe parameter value (``Regular Season`` -> ``regular-season``)."""
    return str(value).lower().replace(" ", "-").replace("_", "-")


def discover(module: Any, prefix: str) -> tuple[list[str], list[str]]:
    """``(game_endpoints, season_endpoints)`` exposed by a league's stats module.

    Team- and player-keyed endpoints are excluded: they are addressed by an id this
    sweep does not enumerate, and are a separate (much larger) capture decision.
    """
    game: list[str] = []
    season: list[str] = []
    for name in sorted(dir(module)):
        if not name.startswith(f"{prefix}_"):
            continue
        fn = getattr(module, name)
        if not callable(fn):
            continue
        params = _params(fn)
        if not params:
            continue
        short = name[len(prefix) + 1 :]
        if short in EXCLUDED_SEASON_ENDPOINTS:
            continue
        if "game_id" in params:
            game.append(short)
        elif "team_id" in params or "player_id" in params:
            continue
        else:
            season.append(short)
    return game, season


def season_variants(
    fn: Callable[..., Any], season: int, league_id: str
) -> Iterator[tuple[str | None, dict[str, Any]]]:
    """Yield ``(variant_slug, kwargs)`` for every capture of one season endpoint.

    The slug is built only from the parameters this endpoint actually sweeps, so
    an endpoint gaining an unrelated parameter later cannot rename existing
    captures, and two endpoints never collide on a filename.
    """
    params = _params(fn)
    base: dict[str, Any] = {}
    season_param = next((p for p in _SEASON_PARAMS if p in params), None)
    if season_param:
        base[season_param] = str(season)
    league_param = next((p for p in _LEAGUE_PARAMS if p in params), None)
    if league_param:
        base[league_param] = league_id
    for pin, value in _PINS:
        name = _match(params, pin)
        if name:
            base[name] = value

    # Expand the cartesian product of whichever sweeps this endpoint supports.
    # Each axis is narrowed to the values that endpoint actually accepts, so the
    # sweep stops issuing calls the API cannot answer.
    axes: list[tuple[str, tuple[str, ...]]] = []
    for prefix, values in _SWEEPS:
        name = _match(params, prefix)
        if name:
            axes.append((name, measure_types_for(fn.__name__, name, values)))

    if not axes:
        yield None, base
        return

    def walk(i: int, acc: dict[str, Any], parts: list[str]) -> Iterator[tuple[str, dict[str, Any]]]:
        if i == len(axes):
            yield "_".join(parts), {**base, **acc}
            return
        name, values = axes[i]
        for value in values:
            yield from walk(i + 1, {**acc, name: value}, [*parts, slug(value)])

    yield from walk(0, {}, [])


def plan_counts(module: Any, prefix: str, league_id: str, season: int = 2025) -> dict[str, int]:
    """Per-season call counts, for sizing a sweep before running one."""
    game, season_eps = discover(module, prefix)
    n_season = sum(
        len(list(season_variants(getattr(module, f"{prefix}_{ep}"), season, league_id)))
        for ep in season_eps
    )
    return {
        "game_endpoints": len(game),
        "season_endpoints": len(season_eps),
        "season_calls_per_season": n_season,
    }

"""Shared capture runtime for the numbered stats.wnba.com capture stages.

Every capture stage needs the same plumbing: the league binding, per-endpoint
season floors, the proxy pool and its sticky ``curl_cffi`` transport, the
progress heartbeat, and the end-of-run health breakdown. That plumbing lives
here ONCE.

This is an import seam, not a stage — it has no ``main()`` and captures
nothing. The stages that use it are independently runnable and resume from
what is on disk, so a failure in one does not strand the others:

    wnba_stats_01_season_endpoints.py   season-level payloads (persists leaguegamelog)
    wnba_stats_02_game_endpoints.py     per-game whole-game payloads
    wnba_stats_03_period_boxscores.py   per-period boxscores

They are ordered by DATA dependency, through the store rather than through
memory: stage 01 persists ``leaguegamelog``, which 02 and 03 read back for
their game universe. That indirection is exactly what lets each be re-run,
resumed, or skipped on its own.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

# ---- league binding: the only WNBA-specific block ----------------------------
LEAGUE_SLUG = "wnba"
LEAGUE_ID = "10"
STATS_PREFIX = "wnba_stats"
STORE_ENV = "SDV_PY_WNBA_RAW_JSON_DIR"
STORE_SUBDIR = ("wnba_stats", "json")
# -----------------------------------------------------------------------------

# parents[2], not parent.parent: this file moved one level deeper when the
# library was packaged (python/wnba_stats_raw_scrape/), and parent.parent then
# silently anchored the store at python/wnba_stats/ -- 2026-09-01's refresh
# wrote 4,551 payloads there and stage 40 green-committed nothing.
REPO = Path(__file__).resolve().parents[2]
SEASON_TYPES = ("Regular Season", "Playoffs")


WORKERS = int(os.environ.get("SCRAPE_WORKERS", "6"))
PERIOD_ENDPOINT = "boxscoretraditionalv3_period"
# Per-endpoint season floor (start-year): below it the endpoint has no data and
# either 500s or returns an empty envelope, so we skip the wasted call. Floors are
# measured (store scan + live probe), not guessed. Game-keyed endpoints are dropped
# in _endpoints_for; season-level ones via capture_season(skip_endpoints=...).
#
# NOT skipped (verified they DO carry old-season data): leaguedashteamshotlocations
# / leaguedashplayershotlocations (basic shot-zone variants populate back to 1996);
# leaguedashteamstats (its Base variant is the team-id source for commonteamroster).
def _parked(endpoint: str) -> int:
    """Floor for a PARKED endpoint: above any real season, so it is skipped.

    Read from ``<ENDPOINT>_MIN_SEASON`` so every parked endpoint is
    independently re-enablable. A shared variable would be a trap: one knob
    covering several endpoints would un-park all of them at once, so a
    fixed-parameter run for one would silently resume hammering the rest.
    """
    return int(os.environ.get(f"{endpoint.upper()}_MIN_SEASON", "9999"))


ENDPOINT_MIN_SEASON = {
    "gamerotation": 2016,
    # Rows-measured floors (archive scan 2026-08-02). These are GENUINE
    # no-data eras, not artifacts: the WNBA single-year season format was
    # always correct here, and the sub-floor captures are valid zero-row
    # envelopes. Floors just stop re-asking a question already answered.
    #   leaguedashptdefend / leagueseasonmatchups: the new tracking-provider
    #   era starts 2023 (NBA's 2013 SportVU floor does not transfer).
    #   player/teamgamelogs: rows begin 2018.
    "leaguedashptdefend": 2023,
    "leagueseasonmatchups": 2023,
    "playergamelogs": 2018,
    # teamgamelogs was floored 2018 by analogy with playergamelogs; the
    # acceptance census then showed rows back to 2000. Measured, not assumed.
    "teamgamelogs": 2000,
    "playercompare": _parked("playercompare"),
    "draftcombinestats": _parked("draftcombinestats"),
}

#: Season CEILINGS (see the NBA sibling): consulted by _skip_endpoint; none
#: measured for WNBA yet -- the mechanism exists so a measured ceiling is a
#: one-line entry, not a code change.
ENDPOINT_MAX_SEASON: dict[str, int] = {}


def _skip_endpoint(endpoint: str, season: int) -> bool:
    """True when `endpoint` has no data for `season`, so the call is skipped.

    Single owner of the floor comparison. Both call sites -- the per-game
    `_endpoints_for` and the season-level `skip_season_eps` -- previously
    inlined it, in INVERTED forms (`yr >= floor` to keep vs `season < mn` to
    skip). Two hand-maintained copies of one boundary is how the shot-locations
    over-skip (4ec4c143a4) happened. An endpoint absent from the table has no
    floor and is never skipped.
    """
    if season < ENDPOINT_MIN_SEASON.get(endpoint, 0):
        return True
    return season > ENDPOINT_MAX_SEASON.get(endpoint, 9999)


def _log(msg: str) -> None:
    print(f"[{datetime.now(timezone.utc).strftime('%F %T')}Z] {msg}", flush=True)


class Progress:
    """Shared per-game progress, updated by the main consume loop and read by the
    heartbeat thread. games_done is per-season so the rate/ETA reflect now, not
    the whole run."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.season: object = None
        self.games_done = 0
        self.games_total = 0
        self.season_start = time.monotonic()

    def begin_season(self, season: object, total: int) -> None:
        with self.lock:
            self.season = season
            self.games_done = 0
            self.games_total = total
            self.season_start = time.monotonic()

    def tick(self) -> None:
        with self.lock:
            self.games_done += 1

    def snapshot(self) -> tuple:
        with self.lock:
            return self.season, self.games_done, self.games_total, self.season_start


def _heartbeat(
    progress: Progress, health, stop_evt: threading.Event, secs: float, pool_size: int
) -> None:
    """Emit a steady progress + IP-health line every ``secs`` and WARN when the
    proxy pool degrades. Windowed on the delta since the last beat so the
    error-rate reflects the recent window, not the cumulative run."""
    last = {}
    while not stop_evt.wait(secs):
        season, done, total, t0 = progress.snapshot()
        if not total:
            continue
        elapsed = max(time.monotonic() - t0, 1e-6)
        rate = done / elapsed
        remaining = max(total - done, 0)
        eta_min = (remaining / rate / 60) if rate > 0 else float("inf")
        snap = health.snapshot()
        c = snap["cat"]
        delta = {k: c.get(k, 0) - last.get(k, 0) for k in c}
        last = dict(c)
        eta_s = "?" if eta_min == float("inf") else f"{eta_min:.0f}m"
        _log(
            f"season {season}: {done}/{total} games | {rate:.1f}/s | ETA {eta_s} | "
            f"win[ok={delta['ok']} blank={delta['blank']} 404={delta['notfound']} "
            f"blocked={delta['blocked']} 5xx={delta['server_err']} timeout/err={delta['transport_err']}] | "
            f"proxies {snap['healthy']}ok/{snap['degraded']}deg/{snap['quar']}quar of {pool_size} | "
            f"top-err: {health.top_error_endpoints(3)}"
        )
        # Degradation WARN — driven by proxy-fault signals (timeouts + blocks +
        # quarantines), NOT 404s (those are expected-absent old-season endpoints).
        win_total = sum(delta.values())
        win_fault = delta["transport_err"] + delta["blocked"]
        if snap["quar"] >= max(3, pool_size // 5) or (
            win_total > 50 and win_fault / win_total > 0.35
        ):
            worst = ", ".join(f"{k}:{n}" for k, n in snap["worst"]) or "n/a"
            _log(
                f"WARN: proxy pool degrading — {snap['quar']}/{pool_size} quarantined, "
                f"{win_fault}/{win_total} recent faults; worst: {worst}"
            )


def _parse_seasons(spec: str) -> list[int]:
    if ":" in spec:
        lo, hi = spec.split(":", 1)
        return list(range(int(lo), int(hi) + 1))
    return [int(spec)]


# ---- shared setup, previously inline in the monolith's main() ---------------


def resolve_store() -> str:
    """Pin the store to THIS checkout.

    Explicit rather than env mutation, so a stage is immune to ambient config:
    a leaked ``*_READONLY`` would otherwise silently turn a capture stage into
    a no-op that still exits 0.
    """
    return os.environ.get(STORE_ENV) or str(REPO.joinpath(*STORE_SUBDIR))


def load_stats_module():
    """The league's sdv-py stats module, plus its discovered endpoint split."""
    import importlib

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from wnba_stats_raw_scrape.endpoints import discover

    stats = importlib.import_module(f"sportsdataverse.{LEAGUE_SLUG}.{STATS_PREFIX}")
    game_endpoints, season_endpoints = discover(stats, STATS_PREFIX)
    return stats, game_endpoints, season_endpoints


def open_transport():
    """Proxy pool -> health -> round robin -> sticky session transport.

    Returns ``(transport, health, pool)``, or ``(None, None, [])`` when no
    proxies are configured. Every capture stage must treat the empty pool as
    fatal: un-proxied stats.{nba,wnba}.com calls HANG rather than fail, so a
    stage that proceeded would look busy forever instead of erroring.
    """
    from sportsdataverse.scrape.stats.proxy import ProxyHealth, RoundRobin, load_proxies
    from sportsdataverse.scrape.stats.session_transport import SessionTransport

    pool = load_proxies()
    if not pool:
        return None, None, []
    health = ProxyHealth(
        quarantine_fails=int(os.environ.get("PROXY_QUARANTINE_FAILS", "5")),
        quarantine_secs=float(os.environ.get("PROXY_QUARANTINE_SECS", "120")),
        error_log=os.environ.get("STATS_ERROR_LOG", "logs/errors.jsonl"),
    )
    return SessionTransport(RoundRobin(pool, health=health), health), health, pool


def no_proxy_error() -> int:
    _log(
        "ERROR: no proxies. Un-proxied stats.%s.com calls hang rather than fail;"
        " export PROXY_ENDPOINT / PROXY_KEY / PROXY_PKG (they live in ~/.Renviron,"
        " which Python does not read)." % LEAGUE_SLUG
    )
    return 1


def start_heartbeat(progress: "Progress", health, n_proxies: int):
    """Daemon heartbeat thread; returns ``(thread, stop_event)``."""
    stop = threading.Event()
    t = threading.Thread(
        target=_heartbeat,
        args=(progress, health, stop, float(os.environ.get("HEARTBEAT_SECS", "60")), n_proxies),
        daemon=True,
    )
    t.start()
    return t, stop


def summarize_health(health) -> None:
    """Full by-endpoint fault breakdown, so 'which requests errored and why' is
    answerable without opening the JSONL."""
    for ep, errs, ec in health.endpoint_summary():
        _log(
            f"endpoint {ep}: {errs} faults | ok={ec['ok']} 404={ec['notfound']}"
            f" blocked={ec['blocked']} 5xx={ec['server_err']} blank={ec['blank']}"
            f" timeout/err={ec['transport_err']}"
        )
    health.close()


def game_ids_for_season(store: str, season: int) -> set[str]:
    """The season's game universe, read from the ``leaguegamelog`` payloads
    stage 01 persisted.

    Reading from disk rather than re-fetching is what makes 02 and 03
    independently runnable: the index is already paid for.
    """
    from wnba_stats_raw_scrape.season_capture import game_ids_from_gamelog, payload_path

    gids: set[str] = set()
    for stype in SEASON_TYPES:
        flat = payload_path(store, "leaguegamelog", season, None)
        variant = stype.lower().replace(" ", "-")
        for candidate in (payload_path(store, "leaguegamelog", season, variant), flat):
            if candidate.exists():
                try:
                    gids.update(
                        game_ids_from_gamelog(json.loads(candidate.read_text(encoding="utf-8")))
                    )
                except (OSError, json.JSONDecodeError) as exc:
                    _log(f"season {season} {stype}: game-index read failed: {exc}")
                break
    return gids


def targeted_ids(ids_file: str) -> dict[int, list[str]]:
    """Parse a ``--game-ids=<file>`` list into ``{season: [game_id, ...]}``.

    leaguegamelog indexes regular season + playoffs only, so preseason,
    All-Star, play-in and Cup-final games are unreachable by the season sweep
    however often it is rerun -- they have to be named.
    """
    from wnba_stats_raw_scrape.period_capture import season_of

    out: dict[int, list[str]] = {}
    for line in Path(ids_file).read_text(encoding="utf-8").splitlines():
        gid = line.strip()
        if gid:
            out.setdefault(season_of(gid), []).append(gid)
    return out


def parse_common(argv: list[str], doc: str):
    """Shared CLI shape for every capture stage: ``[--check] [--game-ids=F] LO:HI``.

    Returns ``(seasons, targeted, check_only)`` or ``None`` on a usage error.
    """
    check_only = "--check" in argv
    ids_file = next((a.split("=", 1)[1] for a in argv if a.startswith("--game-ids=")), None)
    positional = [a for a in argv if not a.startswith("--")]
    if not positional and ids_file is None:
        print(doc, file=sys.stderr)
        return None
    targeted: dict[int, list[str]] = {}
    if ids_file is not None:
        targeted = targeted_ids(ids_file)
        # An empty / all-blank file otherwise reaches the summary log with no
        # seasons and dies on seasons[0] -- an IndexError traceback in place of
        # the usage error this actually is.
        if not targeted:
            print(f"no game ids in {ids_file}", file=sys.stderr)
            return None
    seasons = sorted(targeted) if ids_file is not None else _parse_seasons(positional[0])
    return seasons, targeted, check_only

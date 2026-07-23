#!/usr/bin/env python
"""Scrape stats.wnba.com per-game raw JSON into this repo's wnba_stats/json tree.

THIS repo owns filling the WNBA raw store. Compile/build jobs elsewhere
(wehoop-wnba-stats-data, sdv-py's wnba_engine) consume the tree as pure
readers (``SDV_PY_WNBA_RAW_JSON_DIR`` + ``SDV_PY_WNBA_RAW_JSON_READONLY=1``)
and never write it — the raw-vs-data separation of concerns, mirroring
hoopR-nba-stats-raw.

Each season is swept in two passes. **Season-level** endpoints go first via
``season_capture`` (rosters, season stats, lineups, standings, draft, and the
``leaguegamelog`` game index) into
``wnba_stats/json/{endpoint}/{season}/{variant}.json``. **Per-game** payloads
(``playbyplayv3``, ``boxscoretraditionalv3``, ``gamerotation``,
``boxscoresummaryv2``) then go through sdv-py's read-through raw store in
read-write mode, persisting ``wnba_stats/json/{endpoint}/{season}/{game_id}.json``
(atomic tmp+rename).

Game discovery reads the ``leaguegamelog`` payload the season pass just persisted
rather than making its own call, so the index is fetched once per season/type.

Between the two passes the store covers every dataset ``wehoop-wnba-stats-data``
compiles, which is what lets that repo reshape offline instead of re-fetching. WNBA seasons are single calendar years — game id ``1022600071``
-> season ``2026`` — and the sdv-py store decodes that from the ``10``
league prefix. Idempotent and resumable: on-disk payloads are skipped
without a parse; Ctrl-C and rerun. ``gamerotation`` misses are tolerated
(the endpoint has no data for early seasons). WNBA Stats quirks (LeagueID
``"10"``, Origin/Referer headers, TLS impersonation) live in sdv-py's
``wnba_stats`` runtime — nothing is reimplemented here.

Seasons on the CLI are plain calendar years: ``2024`` or ``1997:2026``.

Run with the wehoop-wnba-stats-data venv (carries sportsdataverse+curl_cffi;
this repo deliberately has no Python project of its own):

    /mnt/sdv_repos/wehoop-wnba-stats-data/python/.venv/bin/python \\
      scripts/scrape_raw_json.py 1997:2026
"""

from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SEASON_TYPES = ("Regular Season", "Playoffs")
WORKERS = int(os.environ.get("SCRAPE_WORKERS", "6"))


def _log(msg: str) -> None:
    print(f"[{datetime.now(timezone.utc).strftime('%F %T')}Z] {msg}", flush=True)


def _parse_seasons(spec: str) -> list[int]:
    if ":" in spec:
        lo, hi = spec.split(":", 1)
        return list(range(int(lo), int(hi) + 1))
    return [int(spec)]


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    # Explicit store args (not env mutation) so this writer is immune to
    # ambient config: store pins the tree to THIS checkout and
    # readonly=False overrides any leaked READONLY env var.
    store = os.environ.get("SDV_PY_WNBA_RAW_JSON_DIR") or str(
        REPO / "wnba_stats" / "json"
    )
    from proxy import RoundRobin, load_proxies
    from season_capture import capture_season, game_ids_from_gamelog, payload_path
    from sportsdataverse.nba.nba_possessions import _raw_store_path, _through_raw_store
    from sportsdataverse.wnba import wnba_stats as _wnba
    from sportsdataverse.wnba.wnba_stats import (
        wnba_stats_boxscoresummaryv2,
        wnba_stats_boxscoretraditionalv3,
        wnba_stats_gamerotation,
        wnba_stats_playbyplayv3,
    )

    endpoints = (
        (
            "playbyplayv3",
            lambda gid, p: wnba_stats_playbyplayv3(
                game_id=gid, return_parsed=False, proxy_url=p
            ),
        ),
        (
            "boxscoretraditionalv3",
            lambda gid, p: wnba_stats_boxscoretraditionalv3(
                game_id=gid, return_parsed=False, proxy_url=p
            ),
        ),
        (
            "gamerotation",
            lambda gid, p: wnba_stats_gamerotation(
                game_id=gid, return_parsed=False, proxy_url=p
            ),
        ),
        # Feeds the game_rosters + officials datasets downstream; without it those
        # two are the only ones that still need a live call at compile time.
        (
            "boxscoresummaryv2",
            lambda gid, p: wnba_stats_boxscoresummaryv2(
                game_id=gid, return_parsed=False, proxy_url=p
            ),
        ),
    )

    def _season_fetch(endpoint: str, kwargs: dict) -> object:
        """Dispatch one season-level call by endpoint name, through the proxy pool."""
        fn = getattr(_wnba, f"wnba_stats_{endpoint}")
        return fn(return_parsed=False, proxy_url=rr.next(), **kwargs)

    seasons = _parse_seasons(argv[0])
    rr = RoundRobin(load_proxies())
    _log(
        f"sweeping {len(seasons)} seasons x {len(SEASON_TYPES)} types, workers={WORKERS}"
    )
    _log(f"store: {store}")

    def _one(gid: str) -> tuple[int, int]:
        fetched = failed = 0
        for ep, fetch in endpoints:
            path = _raw_store_path(ep, gid, root=store)
            if path is not None and path.exists():
                continue
            try:
                _through_raw_store(
                    ep,
                    gid,
                    lambda f=fetch, g=gid: f(g, rr.next()),
                    store_dir=store,
                    readonly=False,
                )
                fetched += 1
            except Exception:  # noqa: BLE001 - a game-local failure must not kill the sweep
                failed += 1
        return fetched, failed

    grand_fetched = grand_failed = 0
    for season in seasons:
        # Season-level endpoints first: they are cheap (tens of calls), and they
        # persist leaguegamelog, which the per-game sweep below then reads for its
        # game index instead of making a second call for the same payload.
        s_written, s_skipped, s_failed = capture_season(
            season, store, _season_fetch, _log
        )
        _log(
            f"season {season}: season-level | {s_written} written | {s_skipped} present"
            f" | {s_failed} failed"
        )

        gids: set[str] = set()
        for stype in SEASON_TYPES:
            path = payload_path(
                store, "leaguegamelog", season, stype.lower().replace(" ", "-")
            )
            if not path.exists():
                _log(f"season {season} {stype}: no game index captured, skipping games")
                continue
            try:
                gids.update(
                    game_ids_from_gamelog(json.loads(path.read_text(encoding="utf-8")))
                )
            except Exception as exc:  # noqa: BLE001 - index gap shouldn't kill the sweep
                _log(f"season {season} {stype}: game-index read failed: {exc}")
        todo = [
            g
            for g in sorted(gids)
            if any(
                not _raw_store_path(ep, g, root=store).exists() for ep, _ in endpoints
            )  # type: ignore[union-attr]
        ]
        _log(f"season {season}: {len(gids)} games indexed, {len(todo)} incomplete")
        if not todo:
            continue
        fetched = failed = 0
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            for fut in as_completed(pool.submit(_one, g) for g in todo):
                f, x = fut.result()
                fetched += f
                failed += x
        grand_fetched += fetched
        grand_failed += failed
        _log(
            f"season {season}: done | {fetched} payloads fetched | {failed} endpoint misses"
        )
    _log(
        f"sweep complete: {grand_fetched} payloads persisted, {grand_failed} endpoint misses (rotation gaps expected in early seasons)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

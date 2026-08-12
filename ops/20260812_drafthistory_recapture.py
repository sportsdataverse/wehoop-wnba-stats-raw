#!/usr/bin/env python
"""One-off repair: re-capture drafthistory/{1997..2026}.json.

Dated one-off, not a pipeline stage: it exists to repair an archive already on
disk, and once the captures are correct there is nothing left for it to do. The
recurring sweep (``python/scrape_raw_json.py``) is the durable entrypoint and
now captures drafthistory correctly on its own.

**The defect it repairs.** ``endpoints._SEASON_PARAMS`` matched season parameters
by EXACT name and drafthistory is the only endpoint spelling its season
``season_year_nullable``, so ``season_variants`` emitted ``{"league_id": "10"}``
with no season filter at all. Unfiltered, drafthistory answers with the FULL
draft history rather than nothing, so the sweep wrote that same 1,201-row payload
under all 30 seasons -- 30 byte-identical files, md5 b682aa93cc, ``"Season":
null`` echoed in each. Fixed in sdv-py b17685a6 (#362); this driver needs that
lock bump to be in effect.

**Why it does not just call the sweep.** ``capture_season`` resumes on
``path.exists()``, so the 30 wrong-but-present files would be skipped. They are
deleted first, then re-fetched through that same engine with every other season
endpoint skipped, so this touches nothing else in the archive.

**Verification is inside the fetch, not after it.** The failure mode here is a
*plausible* payload with the wrong contents -- non-empty, well-formed, just not
the season asked for. ``write_payload``'s contentless guard cannot see that, so
``_verify`` runs before the payload is returned to the engine and raises on a
mismatch; ``capture_season`` then logs the failure and leaves no file, which is
what lets a re-run retry it. A final pass re-reads the files from disk and
asserts they are mutually distinct -- the assertion the original bug would have
failed.

Run (residential IP; stats.wnba.com TLS-blocks plain requests, so the sdv-py
runtime's curl_cffi impersonate="chrome" transport is the one doing the work)::

    ./.venv/Scripts/python.exe ops/20260812_drafthistory_recapture.py
    ./.venv/Scripts/python.exe ops/20260812_drafthistory_recapture.py --verify-only
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
STORE = REPO / "wnba_stats" / "json"
ENDPOINT = "drafthistory"
SEASONS = range(1997, 2027)
LEAGUE_ID = "10"

sys.path.insert(0, str(REPO / "python"))


def _log(msg: str) -> None:
    print(f"[{datetime.now(timezone.utc).strftime('%F %T')}Z] {msg}", flush=True)


def _rows(payload: object) -> tuple[list[str], list[list]]:
    """The ``DraftHistory`` result set as (headers, rowSet). ({}, []) if absent."""
    sets = payload.get("resultSets") if isinstance(payload, dict) else None
    for rs in sets or []:
        if isinstance(rs, dict) and rs.get("name") == "DraftHistory":
            return list(rs.get("headers") or []), list(rs.get("rowSet") or [])
    return [], []


def _verify(payload: object, season: int) -> None:
    """Raise unless ``payload`` is a non-empty DraftHistory for exactly ``season``.

    The SEASON check is the load-bearing one: the bug this repairs produced a
    payload that passes every other check.
    """
    headers, rowset = _rows(payload)
    if not rowset:
        raise ValueError(f"{season}: DraftHistory result set is missing or empty")
    if "SEASON" not in headers:
        raise ValueError(f"{season}: no SEASON column in {headers}")
    idx = headers.index("SEASON")
    seen = {str(row[idx]) for row in rowset if idx < len(row)}
    if seen != {str(season)}:
        raise ValueError(f"{season}: payload carries seasons {sorted(seen)}")
    echoed = (payload.get("parameters") or {}).get("Season")
    if echoed is not None and str(echoed) != str(season):
        raise ValueError(f"{season}: echoed Season={echoed!r}")


def _assert_distinct() -> int:
    """Re-read every capture from disk; assert content + mutual distinctness."""
    digests: dict[int, str] = {}
    counts: dict[int, int] = {}
    for season in SEASONS:
        path = STORE / ENDPOINT / f"{season}.json"
        if not path.exists():
            raise SystemExit(f"FAIL: {path} missing")
        blob = path.read_bytes()
        payload = json.loads(blob)
        _verify(payload, season)
        digests[season] = hashlib.md5(blob).hexdigest()
        counts[season] = len(_rows(payload)[1])

    dupes = {d: n for d, n in Counter(digests.values()).items() if n > 1}
    if dupes:
        collide = sorted(s for s, d in digests.items() if d in dupes)
        raise SystemExit(f"FAIL: {len(collide)} captures share a payload: {collide}")

    for season in SEASONS:
        _log(f"  {season}: {counts[season]:>3} picks  md5 {digests[season][:10]}")
    _log(f"OK: {len(digests)} captures, all mutually distinct, {sum(counts.values())} picks total")
    return 0


def main(argv: list[str]) -> int:
    if "--verify-only" in argv:
        return _assert_distinct()

    from season_capture import capture_season, payload_path
    from sportsdataverse.scrape.stats.endpoints import discover
    from sportsdataverse.wnba import wnba_stats

    _season_endpoints = discover(wnba_stats, "wnba_stats")[1]
    skip = frozenset(e for e in _season_endpoints if e != ENDPOINT)
    if ENDPOINT not in _season_endpoints:
        raise SystemExit(f"FAIL: {ENDPOINT} is not a discovered season endpoint")

    # Resume is path.exists(), so a wrong-but-present file must go before the
    # engine will refetch it -- but only a wrong one. Deleting unconditionally
    # would make a re-run after a transport timeout refetch all 30 seasons to
    # recover the one that failed.
    for season in SEASONS:
        path = payload_path(STORE, ENDPOINT, season, None)
        if not path.exists():
            continue
        try:
            _verify(json.loads(path.read_text(encoding="utf-8")), season)
        except (ValueError, json.JSONDecodeError) as exc:
            _log(f"season {season}: discarding bad capture ({exc})")
            path.unlink()

    written = failed = 0
    for season in SEASONS:

        def _fetch(endpoint: str, kwargs: dict, _season: int = season) -> object:
            payload = getattr(wnba_stats, f"wnba_stats_{endpoint}")(return_parsed=False, **kwargs)
            _verify(payload, _season)  # before the engine is allowed to persist it
            return payload

        w, _skipped, f = capture_season(
            season, STORE, _fetch, wnba_stats, "wnba_stats", LEAGUE_ID, _log, skip_endpoints=skip
        )
        written += w
        failed += f
        _log(f"season {season}: {w} written, {f} failed")

    _log(f"capture complete: {written} written, {failed} failed")
    if failed:
        raise SystemExit(f"FAIL: {failed} season(s) did not verify; nothing written for them")
    return _assert_distinct()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

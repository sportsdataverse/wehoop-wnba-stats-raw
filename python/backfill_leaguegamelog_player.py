"""One-off top-up: capture player-variant leaguegamelog into the raw store.

The season sweep captured leaguegamelog with the default player_or_team="T"
(``{season_type}.json``); the player variant lands additively beside it as
``{season_type}_p.json`` — same convention as hoopR-nba-stats-raw. Skips
files that already exist, never writes an empty payload.

Run from a residential IP (stats.wnba.com hangs on datacenter IPs)::

    python scripts/backfill_leaguegamelog_player.py [start_year] [end_year]
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from sportsdataverse.wnba.wnba_stats import wnba_stats_leaguegamelog

STORE = Path(__file__).resolve().parents[1] / "wnba_stats" / "json" / "leaguegamelog"
SEASON_TYPES = {"Regular Season": "regular-season_p", "Playoffs": "playoffs_p"}
# Rate tuning is env-only so a throttled run can be re-paced without edits.
DELAY_S = float(os.environ.get("STATS_RATE_DELAY_S", "2.0"))
RETRIES = int(os.environ.get("STATS_RATE_RETRIES", "3"))
RETRY_PAUSE_S = float(os.environ.get("STATS_RATE_RETRY_PAUSE_S", "60"))


def _proxy_provider():
    """RoundRobin over the ProxyBonanza pool when PROXY_* env is set, else None."""
    try:
        from wnba_data_build.scrape.proxy import RoundRobin, load_proxies
    except ImportError:
        return None
    proxies = load_proxies()
    if not proxies:
        return None
    print(f"rotating through {len(proxies)} proxies")
    return RoundRobin(proxies).next


def main() -> int:
    lo = int(sys.argv[1]) if len(sys.argv) > 1 else 1997
    hi = int(sys.argv[2]) if len(sys.argv) > 2 else 2026
    provider = _proxy_provider()
    for year in range(lo, hi + 1):
        for stype, slug in SEASON_TYPES.items():
            out = STORE / str(year) / f"{slug}.json"
            if out.exists():
                print(f"skip {year} {stype}: exists")
                continue
            payload = None
            for attempt in range(1, RETRIES + 1):
                try:
                    payload = wnba_stats_leaguegamelog(
                        player_or_team_abbreviation="P",
                        season=str(year),
                        season_type_all_star=stype,
                        league_id="10",
                        return_parsed=False,
                        proxy_url=provider() if provider is not None else None,
                    )
                    break
                except Exception as exc:  # timeout = throttled; pause and retry
                    print(f"retry {attempt}/{RETRIES} {year} {stype}: {exc}")
                    if attempt == RETRIES:
                        raise
                    time.sleep(RETRY_PAUSE_S)
            rows = sum(
                len(rs.get("rowSet") or [])
                for rs in (payload or {}).get("resultSets", [])
            )
            if not rows:
                print(f"EMPTY {year} {stype}: not written")
            else:
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(json.dumps(payload), encoding="utf-8")
                print(f"wrote {year} {stype}: {rows} rows")
            time.sleep(DELAY_S)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

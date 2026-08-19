"""One-off top-up: capture player-variant leaguegamelog into the raw store.

The season sweep captured leaguegamelog with the default player_or_team="T"
(``{season_type}.json``); the player variant lands additively beside it as
``{season_type}_p.json`` — same convention as hoopR-nba-stats-raw. Skips
files that already exist, never writes an empty payload.

Run from a residential IP, or with PROXY_ENDPOINT/PROXY_KEY/PROXY_PKG set
(stats.wnba.com hangs, rather than errors, on a datacenter IP -- see
``_proxy_provider``)::

    python python/wnba_stats_10_leaguegamelog_player_topup.py [start_year] [end_year]

Note: the private ``STATS_RATE_DELAY_S`` / ``STATS_RATE_RETRIES`` /
``STATS_RATE_RETRY_PAUSE_S`` env names below predate the repo convention
(the ``SCRAPE_WORKERS`` / ``SDV_PY_NBA_STATS_TIMEOUT`` family used by the
other scrapers). Kept as-is for compatibility with existing run recipes.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

from sportsdataverse.scrape.stats.proxy import ProxyHealth, RoundRobin, load_proxies
from sportsdataverse.scrape.stats.session_transport import SessionTransport
from sportsdataverse.wnba.wnba_stats import wnba_stats_leaguegamelog

STORE = Path(__file__).resolve().parents[1] / "wnba_stats" / "json" / "leaguegamelog"
SEASON_TYPES = {"Regular Season": "regular-season_p", "Playoffs": "playoffs_p"}
# Rate tuning is env-only so a throttled run can be re-paced without edits.
DELAY_S = float(os.environ.get("STATS_RATE_DELAY_S", "2.0"))
RETRIES = int(os.environ.get("STATS_RATE_RETRIES", "3"))
RETRY_PAUSE_S = float(os.environ.get("STATS_RATE_RETRY_PAUSE_S", "60"))


def _proxy_provider() -> SessionTransport | None:
    """A SessionTransport over the shared proxy pool when PROXY_* env is set, else None.

    Routes through the same ``sportsdataverse.scrape.stats`` machinery
    ``_capture_runtime.py`` uses -- never ``proxy_url=`` directly -- so a
    faulted/blocked proxy is recorded into ``ProxyHealth`` and the session
    rotates itself, instead of this script's own retry loop silently eating it.

    A previous version of this function imported the nonexistent
    ``wnba_data_build.scrape.proxy`` (the -data repo's package -- not
    importable from -raw) and swallowed the resulting ``ImportError``, so this
    always returned ``None`` and every run was silently proxy-less no matter
    the PROXY_* environment. If PROXY_ENDPOINT/KEY/PKG are all set but
    ``load_proxies()`` still comes back empty, that is a real misconfiguration
    (bad credentials, unreachable endpoint, malformed payload) and must raise
    rather than repeat that mistake.
    """
    proxies = load_proxies()
    if not proxies:
        if all(os.environ.get(v) for v in ("PROXY_ENDPOINT", "PROXY_KEY", "PROXY_PKG")):
            raise RuntimeError(
                "PROXY_ENDPOINT/PROXY_KEY/PROXY_PKG are all set but load_proxies() "
                "returned no proxies -- fix the proxy config rather than run "
                "proxy-less against stats.wnba.com (which hangs, not errors, from a "
                "datacenter IP)."
            )
        return None
    print(f"rotating through {len(proxies)} proxies")
    health = ProxyHealth(error_log=os.environ.get("STATS_ERROR_LOG", "logs/errors.jsonl"))
    return SessionTransport(RoundRobin(proxies, health=health), health)


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
                        transport=provider,
                    )
                    break
                except Exception as exc:  # timeout = throttled; pause and retry
                    print(f"retry {attempt}/{RETRIES} {year} {stype}: {exc}")
                    if attempt == RETRIES:
                        raise
                    time.sleep(RETRY_PAUSE_S)
            rows = sum(len(rs.get("rowSet") or []) for rs in (payload or {}).get("resultSets", []))
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

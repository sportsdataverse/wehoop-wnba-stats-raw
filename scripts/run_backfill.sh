#!/bin/bash
# Full WNBA raw backfill. Resumable: payloads already on disk are skipped without
# a parse, so Ctrl-C and rerun costs nothing.
#
#   bash scripts/run_backfill.sh              # 1997:2026
#   bash scripts/run_backfill.sh 2024:2026    # a slice
#
# Watch it:  tail -f /mnt/sdv_repos/wehoop-wnba-stats-raw/logs/backfill.log
#
# PROXY_ENDPOINT / PROXY_KEY / PROXY_PKG live in ~/.Renviron, which R reads
# automatically and Python does not -- so they are exported here. Without them the
# scraper aborts rather than hanging on un-proxied stats.wnba.com calls.

set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SEASONS="${1:-1997:2026}"
# shellcheck source=scripts/_venv.sh
. "$REPO/scripts/_venv.sh"
PY="$SDV_PY"
LOG="${REPO}/logs/backfill.log"

mkdir -p "${REPO}/logs"

# shellcheck disable=SC2046
export $(grep -E "^\s*PROXY" "$HOME/.Renviron" | sed 's/[";]//g' | xargs) 2>/dev/null

if [ -z "${PROXY_KEY:-}" ]; then
    echo "::error ::PROXY_* not found in ~/.Renviron; refusing to run un-proxied"
    exit 1
fi

export PYTHONUNBUFFERED=1 PYTHONIOENCODING=utf-8
# Shared per-IP budget across a 50-IP pool. Raising this is the first thing to
# revisit if the sweep looks slow -- and the first suspect if it starts 429-ing.
export SCRAPE_WORKERS="${SCRAPE_WORKERS:-6}"
# Per-request deadline. Defaulted HERE rather than inherited: the transport's own
# fallback is 30s, and a high-concurrency sweep at 30s produced a few percent
# timeout/err on the slow endpoints, each costing a whole extra pass to recover.
export SDV_PY_NBA_STATS_TIMEOUT="${SDV_PY_NBA_STATS_TIMEOUT:-90}"

{
    echo "=== backfill ${SEASONS} started $(date -u +'%F %T')Z (workers=${SCRAPE_WORKERS}) ==="
    cd "${REPO}" && "${PY}" python/scrape_raw_json.py "${SEASONS}"
    rc=$?
    echo "EXIT=$rc"
    echo "=== finished $(date -u +'%F %T')Z ==="
} >> "${LOG}" 2>&1

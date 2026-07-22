#!/usr/bin/env bash
#
# daily_refresh.sh
#
# Incremental daily refresh: sweep the CURRENT WNBA season's new games into the
# raw store, then commit+push. Cron entry point. Idempotent — already-captured
# games are skipped, and the empty-{} guard (sportsdataverse-py#293) keeps
# dataless fetches from being persisted, so this can run every day cheaply.
#
# WNBA seasons are single calendar years (the 2026 season is dir 2026), so the
# current season is just the current UTC year. In the Oct-Apr offseason this is
# a harmless near-no-op until the new season tips off.
#
# Runs the guard-fixed sportsdataverse via .venv/bin/python directly (NOT
# `uv run`, which would resync the venv to the lockfile).
set -u

REPO="$(cd "$(dirname "$0")/.." && pwd)"
PY=/mnt/sdv_repos/wehoop-wnba-stats-data/python/.venv/bin/python
. "$HOME/.config/sdv/env" 2>/dev/null || true

season=$(date -u +%Y)
LOG="$REPO/logs/daily_refresh_$(date -u +%Y%m%d).log"

{
  echo "[$(date -u '+%F %T')Z] daily refresh start: WNBA season=$season"
  cd "$REPO" || exit 1
  SCRAPE_WORKERS="${SCRAPE_WORKERS:-4}" "$PY" scripts/scrape_raw_json.py "$season"
  bash scripts/commit_raw_json.sh
  echo "[$(date -u '+%F %T')Z] daily refresh done (rc=$?)"
} >> "$LOG" 2>&1

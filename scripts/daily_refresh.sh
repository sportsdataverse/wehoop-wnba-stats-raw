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
. "$HOME/.config/sdv/env" 2>/dev/null || true

season=$(date -u +%Y)
mkdir -p "$REPO/logs"
LOG="$REPO/logs/daily_refresh_$(date -u +%Y%m%d).log"

{
  echo "[$(date -u '+%F %T')Z] daily refresh start: WNBA season=$season"
  cd "$REPO" || exit 1
  # Interpreter resolution runs INSIDE this block deliberately. It used to sit
  # above, so when a venv sweep removed .venv on 2026-08-12 the resolver's
  # `exit 2` fired before $LOG was ever opened: cron kept firing daily and left
  # an empty logs/ directory behind, which read as "the job never ran". Every
  # way this job can die must be readable in its own log.
  # shellcheck source=scripts/_venv.sh
  . "$REPO/scripts/_venv.sh"
  PY="$SDV_PY"
  echo "[$(date -u '+%F %T')Z] interpreter: $PY"
  sdv_preflight sportsdataverse curl_cffi
  SCRAPE_WORKERS="${SCRAPE_WORKERS:-4}" "$PY" python/scrape_raw_json.py "$season"
  scrape_rc=$?
  # The commit used to run unconditionally, so a failed sweep still published a
  # partial season -- and the `rc=$?` below reported the COMMIT's status, which
  # made the failure invisible in the log too.
  if [ "$scrape_rc" -ne 0 ]; then
    echo "[$(date -u '+%F %T')Z] scrape failed (rc=$scrape_rc); not committing"
    exit "$scrape_rc"
  fi
  # Stage 99 (spec D16): rebuild the schedule master + coverage index LAST, so
  # it sees everything this run captured. Non-fatal: a master failure must not
  # keep the day's payloads from being committed.
  "$PY" python/wnba_stats_99_schedule_master_creation.py
  master_rc=$?
  [ "$master_rc" -ne 0 ] && echo "[$(date -u '+%F %T')Z] schedule master failed (rc=$master_rc)"
  bash scripts/commit_raw_json.sh
  commit_rc=$?
  # The master artifacts live beside the json tree, which commit_raw_json.sh
  # deliberately does not stage — commit them separately, only when changed.
  if [ "$master_rc" -eq 0 ]; then
    git add -- wnba_stats/wnba_stats_schedule_master.parquet \
               wnba_stats/wnba_stats_schedule_coverage.parquet \
               wnba_stats/wnba_stats_endpoint_coverage.parquet 2>/dev/null
    git diff --cached --quiet || {
      git commit -m "chore(schedule): refresh schedule master + coverage index"
      git push origin main
    }
  fi
  echo "[$(date -u '+%F %T')Z] daily refresh done (scrape=$scrape_rc master=$master_rc commit=$commit_rc)"
  exit "$commit_rc"
} >> "$LOG" 2>&1

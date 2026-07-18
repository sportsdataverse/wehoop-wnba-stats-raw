#!/usr/bin/env bash
#
# commit_raw_json.sh
#
# Commit + push captured stats.wnba.com raw JSON in per-season batches.
#
# The JSON tree is populated by scripts/scrape_raw_json.py through sdv-py's
# read-through raw store:
#   wnba_stats/json/{endpoint}/{season}/{game_id}.json
# WNBA seasons are single calendar years (2024 season => dir 2024), so the
# commit label is the directory name verbatim — no start/end-year shift.
#
# Safe to re-run any time (cron or manual): only seasons with new/changed
# files produce a commit, one commit per season. *.json.tmp files are
# atomic-write leftovers and are gitignored — never commit them.
#
# The "(Start: YYYY End: YYYY)" subject tail is load-bearing: downstream
# tooling parses the years out of it.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

seasons=$(find wnba_stats/json -mindepth 2 -maxdepth 2 -type d -printf '%f\n' 2>/dev/null | sort -u)
[ -z "$seasons" ] && { echo "no captured seasons under wnba_stats/json — nothing to do"; exit 0; }

for season in $seasons; do
  git add -- wnba_stats/json/*/"$season" 2>/dev/null || true
  if git diff --cached --quiet; then
    continue
  fi
  n=$(git diff --cached --name-only | wc -l)
  git commit -m "WNBA Stats Raw Update (Start: $season End: $season)"
  git push origin main
  echo "[$(date -u '+%F %TZ')] pushed season $season ($n files)"
done

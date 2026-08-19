#!/usr/bin/env bash
#
# commit_raw_json.sh
#
# Commit + push captured stats.wnba.com raw JSON in per-season batches.
#
# The JSON tree is populated by python/wnba_stats_01_raw_json_scrape.py through sdv-py's
# read-through raw store, in two shapes:
#   wnba_stats/json/{endpoint}/{season}/{game_id}.json   per-game and per-variant
#   wnba_stats/json/{endpoint}/{season}.json             one payload per season
# The second shape is easy to miss: league-level endpoints (commonallplayers,
# drafthistory, playerindex, ...) write a flat file, so a season-directory-only
# scan never sees them and they stay untracked forever without ever erroring.
# Both shapes are discovered and staged below.
#
# WNBA seasons are single calendar years (2024 season => 2024), so the commit
# label is the season name verbatim — no start/end-year shift.
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

seasons=$(
  {
    find wnba_stats/json -mindepth 2 -maxdepth 2 -type d -printf '%f\n'
    find wnba_stats/json -mindepth 2 -maxdepth 2 -type f -name '*.json' -printf '%f\n' | sed 's/\.json$//'
  } 2>/dev/null | grep -E '^[0-9]{4}$' | sort -u
)
[ -z "$seasons" ] && { echo "no captured seasons under wnba_stats/json — nothing to do"; exit 0; }

for season in $seasons; do
  git add -- wnba_stats/json/*/"$season" wnba_stats/json/*/"$season".json 2>/dev/null || true
  if git diff --cached --quiet; then
    continue
  fi
  n=$(git diff --cached --name-only | wc -l)
  git commit -m "WNBA Stats Raw Update (Start: $season End: $season)"
  git push origin main
  echo "[$(date -u '+%F %TZ')] pushed season $season ($n files)"
done

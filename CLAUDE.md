# CLAUDE.md — wehoop-wnba-stats-raw Development Guide

## Repo Overview

`wehoop-wnba-stats-raw` is the placeholder repo for a future WNBA Stats API
advanced-statistics scraping pipeline. **It currently holds no scraper
code** — the WNBA Stats API is itself the raw layer, and the
`wehoop::wnba_*()` R functions in the parent
[`wehoop`](https://github.com/sportsdataverse/wehoop) package call the API
directly without a Git-backed cache. This repo exists so that, if/when a
disk-backed cache of WNBA Stats payloads (boxscore V3, leaders,
play-by-play V3, etc.) is needed, the URL and CI plumbing already exist
under the SportsDataverse org.

Do not confuse with [`wehoop-wnba-raw`](https://github.com/sportsdataverse/wehoop-wnba-raw),
which is the active ESPN-side Python scraper (and produces the
ESPN play-by-play JSON consumed by `wehoop-wnba-data`). The two cover
different upstream APIs:

| Repo                       | Upstream                | Status   |
|----------------------------|-------------------------|----------|
| `wehoop-wnba-raw`          | ESPN WNBA API           | active   |
| `wehoop-wnba-stats-raw`    | WNBA Stats API          | reserved |

## Pipeline Position (intended)

```
WNBA Stats API --[future python scrape]--> wehoop-wnba-stats-raw [HERE]
                                                  | (future) push trigger
                                                  v
                                             wehoop-wnba-data
                                                  | release upload
                                                  v
                                          sportsdataverse-data
                                                  | piggyback
                                                  v
                                             wehoop R package
```

Until that pipeline is wired up, the equivalent flow is:

```
WNBA Stats API --[live call from R]--> wehoop::wnba_*() --> end user
```

i.e. there is no raw cache — every call hits `stats.wnba.com` through
`wehoop::request_with_proxy()` with the load-bearing
`Origin: https://stats.wnba.com` / `Referer: https://www.wnba.com/` headers.

## Build & Development Commands

There is no scraper to run yet. Once a Python scraper is added, it should
mirror the shape of its sister scrapers in `wehoop-wnba-raw`:

```sh
# (PROPOSED — not yet implemented)
bash scripts/daily_wnba_stats_scraper.sh -s 2025 -e 2025 -r false
python3 python/scrape_wnba_stats_boxscore_v3.py -s 2025 -e 2025 -r false
python3 python/scrape_wnba_stats_leaders.py     -s 2025 -e 2025 -r false
python3 python/scrape_wnba_stats_pbp_v3.py      -s 2025 -e 2025 -r false
```

Proposed `-r true` / `-r false` semantics: force re-scrape vs. skip files
already on disk, matching the sister repos exactly.

Proposed output tree (when implemented):

```
wnba/
  boxscore_v3/json/{season}/{game_id}.json
  leaders/json/{season}.json
  playbyplay_v3/json/{game_id}.json
  schedule/{rds,csv,parquet}/wnba_stats_schedule_{season}.{ext}
  errors/
```

The Python scrapers, if/when added, should call into `sportsdataverse-py`
(WNBA Stats helpers) and persist the raw response — they should **not**
re-implement WNBA Stats parsing locally. Schema drift is handled in the
SDK at the call boundary.

## Project Structure (current)

```
README.md                       # one-line stub
.gitignore                      # standard R + R-package ignores
wehoop-wnba-stats-raw.Rproj     # RStudio project marker
.github/
  CODE_OF_CONDUCT.md            # (added by governance pass)
  CONTRIBUTING.md
  ...
```

There is no `R/`, `python/`, `scripts/`, or `wnba/` tree yet. Adding any
of those should land alongside a real scraper script and a daily umbrella
workflow modeled on `wehoop-wnba-raw/.github/workflows/daily_wnba_raw.yml`.

## Cross-Repo References

- Shared WNBA Stats conventions (HTTP headers, V2/V3 patterns, `pad_id()`,
  `make_wehoop_data()`, proxy support):
  <https://github.com/sportsdataverse/wehoop/blob/main/CLAUDE.md>
- Active ESPN scraper for WNBA play-by-play (different upstream, same
  org pattern): <https://github.com/sportsdataverse/wehoop-wnba-raw>
- Downstream parser/loader: <https://github.com/sportsdataverse/wehoop-wnba-data>
- Python SDK (the layer any future scraper here should call into):
  <https://github.com/sportsdataverse/sportsdataverse-py>

## Project-Specific Gotchas

- This repo is **a placeholder, not an active scraper**. Do not invent a
  scraper without first checking that the parent `wehoop` package can't
  already serve the same data live via `wnba_*()`.
- The WNBA Stats API (unlike ESPN) requires the `Origin`/`Referer`
  headers handled in `wehoop::request_with_proxy()`. A future scraper
  here must replicate that header convention (or call the wehoop R
  function directly from R via a thin shell wrapper).
- `pad_id()` (zero-pad to 10 digits) and `LeagueID="10"` are load-bearing
  for the WNBA Stats API. Any scraper that builds game IDs locally must
  apply both before HTTP call.
- WNBA-specific time math: 10-minute quarters, 40-minute regulation,
  600s/quarter, 2400s/regulation. Do not copy NBA time constants from
  `hoopR-nba-stats-raw` patterns.
- The push trigger / `repository_dispatch` flow used by `wehoop-wnba-raw`
  is **not** wired up here. Adding scraper output without first adding
  the trigger workflow will land data with no downstream consumer.

## Commit Convention

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat(scrape): seed scrape_wnba_stats_boxscore_v3.py
fix(scrape): pad game IDs to 10 digits before request
chore(deps): pin sportsdataverse-py in requirements.txt
ci: add daily_wnba_stats_raw.yml umbrella workflow
docs: clarify placeholder status in README
```

Prefer scoped subjects (`feat(scrape): ...`, `ci(trigger): ...`). Use
`type!:` or a `BREAKING CHANGE:` footer for breaking changes. Split
unrelated work into separate commits for reviewability.

**Important: Never include AI agents or assistants (e.g., Claude,
Copilot, Cursor, GPT, Gemini) as co-authors on commits.** Omit all
`Co-Authored-By` trailers referencing AI tools. This applies whether the
change was generated, refactored, or reviewed with AI assistance — the
human author is the sole attributable contributor.

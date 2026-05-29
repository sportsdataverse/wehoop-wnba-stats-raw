# wehoop-wnba-stats-raw Copilot Instructions

## Project Context

This repo is a **placeholder** for a future WNBA Stats API
advanced-statistics scraping pipeline. It currently holds no scraper
code — the WNBA Stats API itself acts as the raw layer, and the
`wehoop::wnba_*()` R functions in
[`sportsdataverse/wehoop`](https://github.com/sportsdataverse/wehoop)
call the API live with no Git-backed cache.

Do not confuse with [`wehoop-wnba-raw`](https://github.com/sportsdataverse/wehoop-wnba-raw),
the active ESPN-side Python scraper for WNBA play-by-play JSON. The two
cover different upstream APIs:

| Repo                       | Upstream         | Status   |
|----------------------------|------------------|----------|
| `wehoop-wnba-raw`          | ESPN WNBA API    | active   |
| `wehoop-wnba-stats-raw`    | WNBA Stats API   | reserved |

Intended pipeline (once wired up):

```
WNBA Stats API -> wehoop-wnba-stats-raw [HERE] -> wehoop-wnba-data -> sportsdataverse-data -> wehoop
```

Today the equivalent flow is:

```
WNBA Stats API --[live call from R]--> wehoop::wnba_*() --> end user
```

## Repository Workflow

- `main` is the default and release branch; commit directly to `main`.
- No scraper exists yet. Before adding one, confirm the data can't
  already be served live via `wehoop::wnba_*()`.
- When a scraper is added, mirror the structure of `wehoop-wnba-raw`:
  one Python entry per dataset under `python/`, a `scripts/` shell
  driver, and a daily umbrella workflow in `.github/workflows/`.
- Call into `sportsdataverse-py` WNBA Stats helpers. Don't reimplement
  WNBA Stats parsing locally.

## Build & Development Commands

There is nothing to run yet. Proposed shape for a future scraper:

```sh
# (PROPOSED — not yet implemented)
bash scripts/daily_wnba_stats_scraper.sh    -s 2025 -e 2025 -r false
python3 python/scrape_wnba_stats_boxscore_v3.py -s 2025 -e 2025 -r false
python3 python/scrape_wnba_stats_leaders.py     -s 2025 -e 2025 -r false
python3 python/scrape_wnba_stats_pbp_v3.py      -s 2025 -e 2025 -r false
```

`-r true` forces re-scrape; `-r false` skips files already on disk
(matches the sister repos). Proposed outputs:

- `wnba/boxscore_v3/json/{season}/{game_id}.json`
- `wnba/leaders/json/{season}.json`
- `wnba/playbyplay_v3/json/{game_id}.json`
- `wnba/schedule/{rds,csv,parquet}/wnba_stats_schedule_{season}.{ext}`
- `wnba/errors/`

## Code Style

- Python: snake_case, 4-space indent, `pathlib.Path` for file I/O,
  `concurrent.futures` for parallelism, `tqdm` for progress.
- WNBA Stats API quirks that must survive into any scraper:
  - Pass `Origin: https://stats.wnba.com` and `Referer: https://www.wnba.com/`
    on every request — without these the API returns errors.
  - Zero-pad game IDs to 10 digits (`pad_id()` in wehoop / equivalent in py).
  - WNBA `LeagueID = "10"` (not NBA's `"00"`).
  - WNBA time math is 10-min quarters / 40-min regulation. Do not copy
    NBA constants from `hoopR-nba-stats-raw`.
- Keep `requirements.txt` minimal — pin `sportsdataverse-py` and let it
  carry the parsing logic.

## WNBA Stats vs ESPN

The wehoop R package distinguishes the two upstreams by function
prefix: `wnba_*()` for WNBA Stats endpoints, `espn_wnba_*()` for ESPN
endpoints. Any scraper here would correspond to the `wnba_*()` family
only — the `espn_wnba_*()` family is already covered by
`wehoop-wnba-raw`.

## Cross-Repo References

- Shared WNBA Stats conventions and HTTP layer:
  <https://github.com/sportsdataverse/wehoop/blob/main/CLAUDE.md>
- Sister active scraper (ESPN, different upstream):
  <https://github.com/sportsdataverse/wehoop-wnba-raw>
- Downstream parser/loader:
  <https://github.com/sportsdataverse/wehoop-wnba-data>
- Python SDK to call into:
  <https://github.com/sportsdataverse/sportsdataverse-py>

## Conventional Commits

Use: `type(scope): description`. Common types: `feat`, `fix`, `chore`,
`ci`, `docs`, `refactor`. Use `type!:` or a `BREAKING CHANGE:` footer
for breaking changes.

**Important: Never include AI agents or assistants (e.g., Claude,
Copilot, Cursor, GPT, Gemini) as co-authors on commits.** Omit all
`Co-Authored-By` trailers referencing AI tools. This applies whether the
change was generated, refactored, or reviewed with AI assistance — the
human author is the sole attributable contributor.

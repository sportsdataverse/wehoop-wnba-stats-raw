# wehoop-wnba-stats-raw Copilot Instructions

## Project Context

This repo is the **raw cache of WNBA Stats API (`stats.wnba.com`) payloads** —
sibling to `hoopR-nba-stats-raw` (the men's equivalent, same scraper design)
and to `wehoop-wnba-raw` (the ESPN-side cache).

Earlier revisions of this file called the repo a placeholder holding no
scraper code. That is no longer true: it holds the Python scrapers
(`python/`), bash entry points (`scripts/`), ~109k committed payloads under
`wnba_stats/`, and 30 per-season `.bundles/wnba_stats_json_YYYY.tar.gz`
archives that let consumers fetch a season without cloning the tree.

Do not confuse with [`wehoop-wnba-raw`](https://github.com/sportsdataverse/wehoop-wnba-raw),
the ESPN-side scraper. The two cover different upstream APIs:

| Repo                       | Upstream         | Status   |
|----------------------------|------------------|----------|
| `wehoop-wnba-raw`          | ESPN WNBA API    | active   |
| `wehoop-wnba-stats-raw`    | WNBA Stats API   | active   |

Pipeline:

```
WNBA Stats API -> wehoop-wnba-stats-raw [HERE] -> wehoop-wnba-data
                        -> sportsdataverse-data releases -> wehoop
```

## Repository Workflow

- `main` is the default and release branch. Captured JSON is committed
  per-season by `ops/commit_raw_json.sh`, which the daily job runs.
- Python lives in `python/`, tests in `tests/`, and `scripts/` holds bash
  entry points only. `pyproject.toml` + `uv.lock` at the repo root pin the
  environment; resolve the interpreter by sourcing `scripts/_venv.sh`
  (never hardcode a path to a sibling repo's venv).
- Call into `sportsdataverse-py` WNBA Stats helpers. Don't reimplement
  WNBA Stats parsing locally.

## Build & Development Commands

```sh
uv sync --dev            # create/refresh .venv from uv.lock
uv run pytest            # offline unit tests
uv run ruff check python tests

# Scrape entry points (bash only; each sources scripts/_venv.sh).
bash scripts/daily_refresh.sh              # current season top-up
bash scripts/run_backfill.sh 1997:2026     # full cold backfill
bash ops/refill_empty_payloads.sh --check   # census of `{}` payloads
```

Outputs land under `wnba_stats/json/{endpoint}/{season}/{variant|game_id}.json`,
with league-level endpoints writing a flat `{endpoint}/{season}.json`.

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
- Deps live in `pyproject.toml` + `uv.lock` (no `requirements.txt`);
  `sportsdataverse` is pinned to git `main` via `[tool.uv.sources]` and CI
  installs with `uv sync --frozen --dev`. Keep the dependency list minimal and
  let `sportsdataverse-py` carry the parsing logic.

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

# CLAUDE.md — wehoop-wnba-stats-raw

**Placeholder repo** reserved for a future disk-backed scraper of the **WNBA Stats
API** (`stats.wnba.com`, the official NBA-Stats-style tracking/advanced endpoints).
**It currently holds no scraper code** — verified contents are just `README.md`,
`LICENSE(.md)`, `CODE_OF_CONDUCT.md`, `CONTRIBUTING.md`, `.gitignore`,
`.gitattributes`, and the `.Rproj` marker. No `R/`, `python/`, `scripts/`, `wnba/`,
or `.github/workflows/` tree, and no scraper has ever been committed.

Reason it can be empty: the WNBA Stats API *is* the raw layer. The parent
[`wehoop`](https://github.com/sportsdataverse/wehoop) package's `wnba_*()` functions
hit the API live, and the R-side parser/uploader
[`wehoop-wnba-stats-data`](https://github.com/sportsdataverse/wehoop-wnba-stats-data)
caches per-game JSON locally + uploads release assets. So today's flow is
`stats.wnba.com → wehoop::wnba_*() → wehoop-wnba-stats-data → sportsdataverse-data → wehoop`,
with **no separate raw cache**. Distinct from
[`wehoop-wnba-raw`](https://github.com/sportsdataverse/wehoop-wnba-raw) (active ESPN-API
Python scraper) — different upstream.

## Status / Commands
There is nothing to run. **Do not invent a scraper** without first confirming the parent
`wehoop` package (or `wehoop-wnba-stats-data`) can't already serve the data. If a real
scraper is added, mirror the sister ESPN scraper `wehoop-wnba-raw`: `-s/-e/-r` shell
flags (`-r true|false` = force re-scrape vs. skip files already on disk), call into
`sportsdataverse-py` WNBA Stats helpers rather than re-implementing parsing, persist the
raw response, commit per-game JSON directly to git (the intentional SDV `-raw` pattern),
and add the daily umbrella workflow + downstream push trigger together (output with no
consumer is dead data).

## Gotchas — stats.wnba.com handling (the non-obvious part)
Any future scraper here must replicate the WNBA Stats request convention that lives in
`wehoop` (`R/utils_wnba_stats.R`, `request_with_proxy`) — un-proxied / header-less calls
to `stats.wnba.com` time out:
- **Load-bearing headers**: `Host: stats.wnba.com`, a desktop-Chrome `User-Agent`,
  `x-nba-stats-origin: stats`, `x-nba-stats-token: true`,
  `Origin: https://stats.wnba.com`, `Referer: https://www.wnba.com/`.
- **`pad_id()`** (zero-pad game IDs to 10 digits) and **`LeagueID="10"`** must be applied
  before any HTTP call.
- **Proxy + rate-limit** are required at volume. See `wehoop-wnba-stats-data/R/utils.R`
  (`load_proxies` precedence: `PROXY_KEY`+`PROXY_PKG` env → proxybonanza pull → local
  `proxylist.csv` → un-proxied; `select_proxy()` per request; `rate_limit()` trailing-window
  token bucket tuned by `STATS_RATE_MAX/_WINDOW/_HITS`). Keep the fetch loop **sequential**
  — parallel workers blow the shared per-IP budget.
- WNBA time math: 10-min quarters, 2400s regulation. Do not copy NBA constants from
  `hoopR-nba-stats-raw`.

## Commits
Conventional Commits (`feat(scrape):`, `fix(scrape):`, `ci:`, `docs:`).
**Never add AI co-author / `Co-Authored-By` trailers to commits.**

Refs: `wehoop` (SDK + shared WNBA Stats conventions) · `wehoop-wnba-stats-data` (downstream parser/uploader) · `sportsdataverse-py` (the layer a scraper should call into).

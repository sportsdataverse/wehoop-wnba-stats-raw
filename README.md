# wehoop-wnba-stats-raw

Raw cache of WNBA Stats API (`stats.wnba.com`) payloads. Scrapers live in
`python/`, bash entry points in `scripts/`, and captures land under
`wnba_stats/json/{endpoint}/{season}/{variant|game_id}.json` (league-level
endpoints write a flat `{endpoint}/{season}.json`). Downstream:
`wehoop-wnba-data` builds tidy datasets from this store.

**The season in a path is a claim about the payload, not just a filename.**
`{endpoint}/2013.json` holds the payload the API returned *filtered to 2013* —
verified for `drafthistory` on 2026-08-12, where the 30 per-season files are
mutually distinct and each echoes its own `"Season"`. It was briefly untrue:
`_SEASON_PARAMS` matched season parameters by exact name and `drafthistory`
alone spells its season `season_year_nullable`, so the filter was dropped and
the sweep wrote the same full-history payload under all 30 seasons (sdv-py
b17685a6). An unfiltered call that answers with *everything* rather than
nothing is the quiet failure to watch for when adding an endpoint: check that
two seasons differ, not just that the file is non-empty.

Each script's header comment is the authoritative doc — read it before
running. This section is the map, not the manual.

## wehoop WNBA Stats workflow diagram

```mermaid
  graph LR;
    S[stats.wnba.com]-->A[wehoop-wnba-stats-raw];
    A[wehoop-wnba-stats-raw]-->B[wehoop-wnba-stats-data];
    A[wehoop-wnba-stats-raw]-->D[wnba-stats-raw-json season bundles];
    B[wehoop-wnba-stats-data]-->C1[wnba_stats_schedules];
    B[wehoop-wnba-stats-data]-->C2[wnba_stats_pbp];
    B[wehoop-wnba-stats-data]-->C3[wnba_stats_possessions];
    B[wehoop-wnba-stats-data]-->C4[wnba_stats_game_lineups];
    B[wehoop-wnba-stats-data]-->C5[wnba_stats_lineups];
    B[wehoop-wnba-stats-data]-->C6[wnba_stats_shots];
    B[wehoop-wnba-stats-data]-->C7[wnba_stats_player_boxscores];
    B[wehoop-wnba-stats-data]-->C8[wnba_stats_team_boxscores];
    B[wehoop-wnba-stats-data]-->C9[wnba_stats_player_game_logs];
    B[wehoop-wnba-stats-data]-->C10[wnba_stats_player_season_stats];
    B[wehoop-wnba-stats-data]-->C11[wnba_stats_team_season_stats];
    B[wehoop-wnba-stats-data]-->C12[wnba_stats_game_rosters];
    B[wehoop-wnba-stats-data]-->C13[wnba_stats_rosters];
    B[wehoop-wnba-stats-data]-->C14[wnba_stats_standings];
    B[wehoop-wnba-stats-data]-->C15[wnba_stats_officials];
    B[wehoop-wnba-stats-data]-->C16[wnba_stats_coaches];
    B[wehoop-wnba-stats-data]-->C17[wnba_stats_draft];
    B[wehoop-wnba-stats-data]-->C18[wnba_stats_leaguedash];
```

```mermaid
flowchart TB;
    subgraph A[wehoop-wnba-stats-raw];
        direction TB;
        A0[scripts/daily_refresh.sh]-->A1[python/wnba_stats_01_season_endpoints.py];
        A1[python/wnba_stats_01_season_endpoints.py]-->A2[python/wnba_stats_02_game_endpoints.py];
        A2[python/wnba_stats_02_game_endpoints.py]-->A3[python/wnba_stats_03_period_boxscores.py];
        A3[python/wnba_stats_03_period_boxscores.py]-->A4[python/wnba_stats_10_leaguegamelog_player_topup.py];
        A4[python/wnba_stats_10_leaguegamelog_player_topup.py]-->A5[python/wnba_stats_20_refill_empty.py];
        A5[python/wnba_stats_20_refill_empty.py]-->A6[python/wnba_stats_99_schedule_master_creation.py];
        A6[python/wnba_stats_99_schedule_master_creation.py]-->A7[ops/publish_season_bundles.sh];
    end;

    subgraph B[wehoop-wnba-stats-data];
        direction TB;
        B0[scripts/daily_wnba_stats_python_processor.sh]-->B1[python/wnba_stats_01_standings_creation.py];
        B1[python/wnba_stats_01_standings_creation.py]-->B2[python/wnba_stats_02_player_season_stats_creation.py];
        B2[python/wnba_stats_02_player_season_stats_creation.py]-->B3[python/wnba_stats_03_team_season_stats_creation.py];
        B3[python/wnba_stats_03_team_season_stats_creation.py]-->B4[python/wnba_stats_04_lineups_creation.py];
        B4[python/wnba_stats_04_lineups_creation.py]-->B5[python/wnba_stats_05_rosters_creation.py];
        B5[python/wnba_stats_05_rosters_creation.py]-->B6[python/wnba_stats_06_coaches_creation.py];
        B6[python/wnba_stats_06_coaches_creation.py]-->B7[python/wnba_stats_07_draft_creation.py];
        B7[python/wnba_stats_07_draft_creation.py]-->B8[python/wnba_stats_08_schedules_creation.py];
        B8[python/wnba_stats_08_schedules_creation.py]-->B9[python/wnba_stats_09_player_game_logs_creation.py];
        B9[python/wnba_stats_09_player_game_logs_creation.py]-->B10[python/wnba_stats_10_pbp_creation.py];
        B10[python/wnba_stats_10_pbp_creation.py]-->B11[python/wnba_stats_11_game_rosters_creation.py];
        B11[python/wnba_stats_11_game_rosters_creation.py]-->B12[python/wnba_stats_12_officials_creation.py];
    end;

    subgraph C[sportsdataverse-data Releases];
        direction TB;
        C1[wnba_stats_schedules];
        C2[wnba_stats_pbp];
        C3[wnba_stats_possessions];
        C4[wnba_stats_game_lineups];
        C5[wnba_stats_lineups];
        C6[wnba_stats_shots];
        C7[wnba_stats_player_boxscores];
        C8[wnba_stats_team_boxscores];
        C9[wnba_stats_player_game_logs];
        C10[wnba_stats_player_season_stats];
        C11[wnba_stats_team_season_stats];
        C12[wnba_stats_game_rosters];
        C13[wnba_stats_rosters];
        C14[wnba_stats_standings];
        C15[wnba_stats_officials];
        C16[wnba_stats_coaches];
        C17[wnba_stats_draft];
        C18[wnba_stats_leaguedash];
    end;

    A-->B;
    B-->C;
```

`scripts/daily_refresh.sh` (raw) and `scripts/daily_wnba_stats_python_processor.sh`
(data) are the drivers; the raw side also publishes whole-season JSON bundles to
its own `wnba-stats-raw-json` release. Stage numbers are intended build order,
not run order.

[wehoop-wbb-raw repository (source: ESPN)](https://github.com/sportsdataverse/wehoop-wbb-raw)

[wehoop-wbb-data repository (source: ESPN)](https://github.com/sportsdataverse/wehoop-wbb-data)

[wehoop-wnba-raw repository (source: ESPN)](https://github.com/sportsdataverse/wehoop-wnba-raw)

[wehoop-wnba-data repository (source: ESPN)](https://github.com/sportsdataverse/wehoop-wnba-data)

[wehoop-wnba-stats-raw repository (source: WNBA Stats)](https://github.com/sportsdataverse/wehoop-wnba-stats-raw)

[wehoop-wnba-stats-data repository (source: WNBA Stats)](https://github.com/sportsdataverse/wehoop-wnba-stats-data)

[ncaa-wbb-hoops-raw repository (source: stats.ncaa.org)](https://github.com/sportsdataverse/ncaa-wbb-hoops-raw)

[ncaa-wbb-hoops-data repository (source: stats.ncaa.org)](https://github.com/sportsdataverse/ncaa-wbb-hoops-data)

## Run order

1. **Cold backfill** (rare, multi-hour): `bash scripts/backfill.sh 1997:2026`
   — or, for unattended runs, wrap the sweep in the crash-restart supervisor:
   `tmux new-session -d -s sweepsup 'bash ops/supervise_sweep.sh 1997:2026'`.
   Run `bash ops/commit_loop.sh <launcher_pid>` alongside so multi-hour
   captures are committed per season as they finish, not lost on a crash.
2. **Daily** (cron): `bash scripts/daily_refresh.sh` — current-season top-up,
   then commit+push.
3. **Repair** (as needed): `bash ops/refill_empty_payloads.sh --check`
   to census empty `{}` payloads, then run without `--check` from a
   residential IP to refetch them.
4. **Publish** (after a backfill or season close): `bash
   ops/publish_season_bundles.sh` — a real pipeline stage, not optional:
   `wehoop-wnba-stats-data`'s full rebuilds consume its per-season tarballs
   instead of ~100k per-file GETs.

All scrapes need a residential IP or the proxy pool — stats.wnba.com hangs
(does not error) on datacenter IPs.

## Ops scripts

| Script | What / when | Watch |
|---|---|---|
| `scripts/backfill.sh [A:B]` | Full resumable backfill driver (skips on-disk payloads; refuses to run un-proxied). Manual, rare. | `tail -f logs/backfill.log` |
| `ops/supervise_sweep.sh [A:B]` | Crash-restart wrapper around `python/_capture_runtime.py`: relaunches on abnormal death, stops on "sweep complete", gives up after `MAX_RESTARTS`. Launch under tmux/nohup. | `tail -f logs/watchdog_*.log` |
| `ops/commit_loop.sh <pid>` | Commits the store per-season on a timer while a sweep runs, exits when the watched pid dies. Pass the pid — `pgrep` fallback is blind under Git Bash. | `git log --oneline` |
| `ops/commit_raw_json.sh` | Per-season commit+push of captured JSON (both store shapes). Idempotent; the "(Start: YYYY End: YYYY)" subject is parsed downstream. | `git log --oneline` |
| `scripts/daily_refresh.sh` | Cron entry point: sweep the current season, commit+push. Near-no-op in the offseason. | `tail -f logs/daily_refresh_*.log` |
| `ops/publish_season_bundles.sh [A:B]` | Builds one tarball per season under `.bundles/` and uploads to the `wnba-stats-raw-json` release. `DRY_RUN=1` to build without uploading; needs authed `gh`. | script stdout |
| `ops/refill_empty_payloads.sh` + `python/wnba_stats_20_refill_empty.py` | Repair pair for `{}` payloads persisted before the empty-payload guard: shell wrapper handles env/proxy/log, the python module deletes files `<= 2` bytes and refetches exactly those tuples. `--check` = census only, no network. | `tail -f logs/wnba_stats_20_refill_empty.log` |
| `python/wnba_stats_10_leaguegamelog_player_topup.py` | One-off top-up of the player-variant leaguegamelog (`*_p.json`); see its docstring for env caveats. | script stdout |
| `scripts/_venv.sh` | Sourced by every driver: resolves `SDV_PY` to the repo `.venv` (override with `WNBA_VENV_PYTHON`). Not run directly. | — |

## Env knobs

Rate/behavior tuning is env-only — never hardcoded — so a throttled run can
be re-paced without code edits:

- `SCRAPE_WORKERS` — sweep parallelism (backfill default 6, daily 4).
- `SDV_PY_NBA_STATS_TIMEOUT` — per-request timeout seconds (drivers default 90).
- `WNBA_VENV_PYTHON` — interpreter override, beats `.venv` (see `scripts/_venv.sh`).
- `PROXY_ENDPOINT` / `PROXY_KEY` / `PROXY_PKG` — proxy pool; live in
  `~/.Renviron`, which the drivers export (Python does not read `.Renviron`).
- `MAX_RESTARTS`, `INTERVAL`, `DRY_RUN`, `BUNDLE_TAG`, `BUNDLE_OUT_DIR` —
  per-script knobs; see the respective headers.

## Reports & explainers

<!-- BEGIN GENERATED: reports -->

| Report | What it is | Last updated |
|---|---|---|
| _none yet_ | — | — |

<!-- END GENERATED: reports -->

## Automation & status

<!-- BEGIN GENERATED: status -->

| workflow | schedule | last run |
|---|---|---|
| [![orphan_scripts.yml](https://github.com/sportsdataverse/wehoop-wnba-stats-raw/actions/workflows/orphan_scripts.yml/badge.svg)](https://github.com/sportsdataverse/wehoop-wnba-stats-raw/actions/workflows/orphan_scripts.yml) | on push / dispatch | 2026-08-27 |
| [![tests.yml](https://github.com/sportsdataverse/wehoop-wnba-stats-raw/actions/workflows/tests.yml/badge.svg)](https://github.com/sportsdataverse/wehoop-wnba-stats-raw/actions/workflows/tests.yml) | on push / PR / dispatch | 2026-08-27 |

<!-- END GENERATED: status -->

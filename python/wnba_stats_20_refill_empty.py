"""Refill the season-level payloads that were persisted as empty ``{}``.

The repair logic (census, delete-only-with-a-replacement-in-hand, atomic
rewrite) lives in :mod:`sportsdataverse.scrape.stats.refill` (sdv-py #327);
this is the WNBA binding and entry point. See that module for the incident
background and the safety contract.

The pre-migration version of this file imported ``sportsdataverse.nba.wnba_stats``,
which does not exist -- every real (non-``--check``) run raised
ModuleNotFoundError. The module is now resolved from the league config.

Usage
-----
    python python/wnba_stats_20_refill_empty.py --check          # census only, no network
    python python/wnba_stats_20_refill_empty.py                  # refill everything
    python python/wnba_stats_20_refill_empty.py 2015:2026        # season range
    python python/wnba_stats_20_refill_empty.py --endpoint matchupsrollup
"""

import sys

from wnba_stats_raw_scrape._capture_runtime import REPO, STORE_SUBDIR
from sportsdataverse.scrape.stats.league_config import WNBA
from sportsdataverse.scrape.stats.refill import main

if __name__ == "__main__":
    sys.exit(main(WNBA, default_root=REPO.joinpath(*STORE_SUBDIR)))

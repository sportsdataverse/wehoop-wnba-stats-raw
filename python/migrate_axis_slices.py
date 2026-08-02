"""One-shot migration for the 2026-08-02 sub-dimension axis changes (WNBA).

Unlike the NBA sibling, this archive holds NO bare-year artifacts -- the WNBA
single-year season format was always correct, so its zero-row captures are
genuine answers and stay. Two narrow actions:

1. DELETE all scoreboardv3 season files: the endpoint is DATE-keyed and every
   per-season file captured the wrapper's fixed default date (junk by
   construction). scoreboardv3 is now excluded from discovery.
2. RENAME leaguedashptdefend captures to carry their true slice token: every
   existing file is the DefenseCategory="Overall" slice, and now that
   defense_category is a swept axis its slug carries the category --
   {season_type}_{per_mode}.json -> {season_type}_overall_{per_mode}.json.

Idempotent; prints a full accounting.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ROOT = REPO / "wnba_stats" / "json"


def main() -> int:
    deleted = renamed = 0
    sb = ROOT / "scoreboardv3"
    if sb.exists():
        junk = list(sb.rglob("*.json"))
        for f in junk:
            f.unlink()
        deleted = len(junk)
        print(f"scoreboardv3: {deleted} date-keyed junk files deleted")

    ptd = ROOT / "leaguedashptdefend"
    if ptd.exists():
        for f in sorted(ptd.rglob("*.json")):
            stem = f.stem
            if "overall" in stem:  # already migrated
                continue
            parts = stem.rsplit("_", 1)  # {season_type}, {per_mode}
            if len(parts) != 2:
                continue
            f.rename(f.with_name(f"{parts[0]}_overall_{parts[1]}.json"))
            renamed += 1
        print(f"leaguedashptdefend: {renamed} renamed to explicit slice names")

    print(f"TOTAL: deleted={deleted} renamed={renamed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

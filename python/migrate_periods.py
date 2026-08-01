#!/usr/bin/env python
"""Convert split per-period boxscores into the combined per-game form.

An earlier sweep wrote one file per game-period (``{game_id}_p{period}.json``)
before the store standardised on one payload per game keyed by period. This
converts what those sweeps captured instead of re-fetching it -- the data is
identical, and a re-fetch would spend thousands of requests against a shared
stats-host budget to end up in the same place.

Safe by construction: the combined payload is written and read back before any
split file is removed, so an interrupted run leaves both forms on disk (which
readers already tolerate) rather than a half-converted game.

    python scripts/migrate_periods.py <store-root>           # report only
    python scripts/migrate_periods.py <store-root> --apply   # convert
"""

from __future__ import annotations

import json
import os
import sys
from collections import defaultdict
from pathlib import Path

PERIOD_ENDPOINT = "boxscoretraditionalv3_period"


def split_groups(store: Path) -> dict[Path, list[Path]]:
    """Map each game's combined destination to its split parts, period-ordered."""
    groups: dict[Path, list[Path]] = defaultdict(list)
    root = store / PERIOD_ENDPOINT
    if not root.is_dir():
        return {}
    for path in root.rglob("*_p*.json"):
        stem, _, period = path.stem.rpartition("_p")
        if not period.isdigit() or not stem:
            continue
        groups[path.parent / f"{stem}.json"].append(path)
    for dest in groups:
        groups[dest].sort(key=lambda p: int(p.stem.rpartition("_p")[2]))
    return dict(groups)


def convert(dest: Path, parts: list[Path]) -> int:
    """Write one combined payload and drop its parts. Returns parts removed."""
    combined = {p.stem.rpartition("_p")[2]: json.loads(p.read_text()) for p in parts}
    tmp = dest.with_name(f".{dest.name}.partial")
    tmp.write_text(json.dumps(combined))
    os.replace(tmp, dest)

    # Read back before deleting anything: if this does not round-trip, the parts
    # are still the only copy and must stay.
    check = json.loads(dest.read_text())
    if set(check) != set(combined):
        raise RuntimeError(f"round-trip mismatch for {dest}")

    for part in parts:
        part.unlink()
    return len(parts)


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    store = Path(argv[0])
    apply = "--apply" in argv
    groups = split_groups(store)
    parts = sum(len(v) for v in groups.values())
    print(f"{store}: {parts} split files across {len(groups)} games")
    if not groups:
        return 0
    if not apply:
        print("dry run -- pass --apply to convert")
        return 0

    converted = removed = failed = 0
    for dest, files in sorted(groups.items()):
        try:
            removed += convert(dest, files)
            converted += 1
        except Exception as exc:  # noqa: BLE001 - report and continue
            print(f"  FAILED {dest}: {exc}")
            failed += 1
    print(
        f"converted {converted} games, removed {removed} split files, {failed} failed"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

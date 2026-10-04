"""The daily's season: the WNBA plays one calendar year, so October does not roll forward.

``scripts/run_pipeline.sh`` picks the season a daily run captures. It was copied
from the NBA twin with the NBA's rule (October starts the NEXT season), so from
2026-10-01 the WNBA daily captured a season "2027" that does not exist -- 0 games
indexed, exit 0 -- while the 2026 playoffs went uncaptured. The function is run
here as bash, with ``date`` stubbed, so the test reads the shipped script.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run_pipeline.sh"


def _current_season(month: str, year: str = "2026") -> str:
    fn = re.search(r"^current_season\(\) \{.*?^\}", SCRIPT.read_text(), re.S | re.M)
    assert fn, "current_season() not found in scripts/run_pipeline.sh"
    stub = f'date() {{ case "$2" in +%m) echo {month};; +%Y) echo {year};; esac; }}'
    out = subprocess.run(
        ["bash", "-c", f"{stub}\n{fn.group(0)}\ncurrent_season"],
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.strip()


@pytest.mark.parametrize("month", ["05", "09", "10", "11", "12"])
def test_the_season_is_the_calendar_year_through_the_playoffs(month: str) -> None:
    # the Finals are played in October: still the season that tipped off in May
    assert _current_season(month) == "2026"

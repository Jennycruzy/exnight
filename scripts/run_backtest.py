"""Rerun the Alpha Factory backtest from the committed data and write `reports/`.

    python scripts/run_backtest.py            # walk-forward + comparison + report
    python scripts/run_backtest.py --report   # report only, from the committed decisions

The walk-forward refuses to run if its frozen manifest has changed.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from exnight import backtest_report, baseline, competition  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--report", action="store_true", help="skip the walk-forward and use the committed decisions")
    args = parser.parse_args()
    if not args.report:
        competition.score()
        baseline.build()
    backtest_report.build()
    print(backtest_report.MARKDOWN.read_text())


if __name__ == "__main__":
    main()

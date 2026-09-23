"""Record every scheduled forward window that is open now (one sample per call).

Reads data/forward/v3_schedule.json and, for each group whose [start, end) contains the
current minute, appends one sample per symbol through scripts/record_event.py's writer. One
cron line covers every planned event; outside all windows the script touches nothing.

    * * * * * cd /home/ubuntu/exnight && .venv/bin/python scripts/record_schedule.py \
        >> data/raw/recorder/cron_v3.log 2>&1
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from exnight.market import BitgetPublic  # noqa: E402
from record_event import append, sample  # noqa: E402

SCHEDULE = ROOT / "data" / "forward" / "v3_schedule.json"


def active_groups(plan: dict, now: dt.datetime) -> list[dict]:
    return [g for g in plan["groups"]
            if dt.datetime.fromisoformat(g["start"]) <= now < dt.datetime.fromisoformat(g["end"])]


def main() -> int:
    ap = argparse.ArgumentParser(description="Record all open scheduled forward windows")
    ap.add_argument("--schedule", type=Path, default=SCHEDULE)
    args = ap.parse_args()
    now = dt.datetime.now(dt.UTC).replace(microsecond=0)
    groups = active_groups(json.loads(args.schedule.read_text()), now)
    if not groups:
        return 0
    api = BitgetPublic()
    for g in groups:
        rows = sample(api, g["symbols"], now)
        path = append(g["label"], rows, now)
        books = ", ".join(f"{r['symbol']} {(r.get('ticker') or {}).get('lastPrice')}" for r in rows)
        print(f"{now.isoformat()} {g['label']}/{path.name}: {books}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

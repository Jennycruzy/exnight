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
import fcntl
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from exnight.market import BitgetPublic  # noqa: E402
from record_event import append, sample  # noqa: E402

SCHEDULE = ROOT / "data" / "forward" / "v3_schedule.json"
LOCK = ROOT / "data" / "raw" / "recorder" / ".record_schedule.lock"
RETRY_WITHIN_SECONDS = 30   # one retry only if the first attempt failed early enough in the minute


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
    # Runs are serialised: if the previous minute's run is still waiting on the API, this one
    # skips rather than risk appending rows out of timestamp order (a validation failure).
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    lock = LOCK.open("w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(f"{now.isoformat()} previous run still active; skipped this minute")
        return 0
    api = BitgetPublic()
    started = time.monotonic()
    for g in groups:
        stamp = now
        for attempt in (1, 2):
            try:
                rows = sample(api, g["symbols"], stamp)
                break
            except Exception as exc:  # network or API failure; the minute is otherwise lost
                if attempt == 2 or time.monotonic() - started > RETRY_WITHIN_SECONDS:
                    print(f"{stamp.isoformat()} {g['label']}: sample failed: {exc}")
                    rows = None
                    break
                time.sleep(5)
                stamp = dt.datetime.now(dt.UTC).replace(microsecond=0)
        if rows is None:
            continue
        path = append(g["label"], rows, stamp)
        books = ", ".join(f"{r['symbol']} {(r.get('ticker') or {}).get('lastPrice')}" for r in rows)
        print(f"{stamp.isoformat()} {g['label']}/{path.name}: {books}"
              + (" (retry)" if stamp != now else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

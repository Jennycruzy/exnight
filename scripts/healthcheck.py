"""Small scheduler health gate for the forward recorder and depth collector."""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

import pandas as pd

from validate_recording import read_rows, validate


def depth_health(path: Path, now: dt.datetime, max_age_seconds: int) -> dict:
    if not path.exists():
        return {"status": "FAIL", "reason": "depth csv missing", "path": str(path)}
    try:
        frame = pd.read_csv(path)
        timestamps = pd.to_datetime(frame["ts"], utc=True)
        latest = timestamps.max().to_pydatetime()
        age = (now - latest).total_seconds()
        status = "PASS" if age <= max_age_seconds else "FAIL"
        return {"status": status, "path": str(path), "latest": latest.isoformat(), "age_seconds": age,
                "rows": int(len(frame)), "symbols": int(frame["symbol"].nunique())}
    except (OSError, KeyError, ValueError, TypeError) as exc:
        return {"status": "FAIL", "path": str(path), "reason": str(exc)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Check EXNIGHT scheduler outputs")
    parser.add_argument("paths", nargs="+", type=Path, help="recorder JSONL files")
    parser.add_argument("--symbols", nargs="+", required=True)
    parser.add_argument("--depth", type=Path, required=True)
    parser.add_argument("--max-age-seconds", type=int, default=7200)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    now = dt.datetime.now(dt.UTC)
    by_symbol, errors = read_rows(args.paths)
    recorder = validate(by_symbol, errors, expected_symbols=args.symbols,
                        max_gap_seconds=180, max_age_seconds=args.max_age_seconds, now=now)
    depth = depth_health(args.depth, now, args.max_age_seconds)
    report = {"checked_at": now.isoformat(), "status": "PASS" if recorder["status"] == "PASS" and depth["status"] == "PASS" else "FAIL",
              "recorder": recorder, "depth": depth}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.output.with_name(args.output.name + ".tmp")
    tmp.write_text(json.dumps(report, indent=1) + "\n")
    tmp.replace(args.output)
    print(json.dumps({"status": report["status"], "recorder": recorder["status"], "depth": depth["status"]}))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

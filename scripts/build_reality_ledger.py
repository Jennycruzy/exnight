"""Build the complete Reality ledger in resumable public-API batches."""
from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import json
import os
from pathlib import Path

from exnight.calendar import REALITY_RAW_DIR, build_reality_ledger, write_ledger
from exnight.market import BitgetPublic

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = ROOT / "data" / "ledger" / "reality_full.jsonl"
DEFAULT_STATE = ROOT / "data" / "results" / "reality_full_build.json"
DEFAULT_LOCK = ROOT / "data" / "results" / "reality_full_build.lock"


def _date(value: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid date: {value}") from exc


def _save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")
    with tmp.open("rb") as f:
        os.fsync(f.fileno())
    tmp.replace(path)


def main() -> int:
    ap = argparse.ArgumentParser(description="Resumable complete Reality ledger builder")
    ap.add_argument("--start-date", required=True, type=_date)
    ap.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    ap.add_argument("--state", type=Path, default=DEFAULT_STATE)
    ap.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    ap.add_argument("--batch-size", type=int, default=25)
    args = ap.parse_args()
    if args.batch_size < 1:
        ap.error("--batch-size must be positive")

    args.lock.parent.mkdir(parents=True, exist_ok=True)
    with args.lock.open("a+") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("another full Reality ledger build is already running")
            return 2

        state = {"start_date": args.start_date.isoformat(), "output": str(args.output),
                 "batch_size": args.batch_size, "completed": [], "failed": []}
        if args.state.exists():
            state = json.loads(args.state.read_text())
            if state.get("start_date") != args.start_date.isoformat() or state.get("output") != str(args.output):
                raise SystemExit("state file belongs to a different start date or output")

        api = BitgetPublic()
        universe = api.rtokens()
        base_coins = sorted(universe)
        completed = set(state.get("completed", []))
        pending = [coin for coin in base_coins if coin not in completed]
        print(f"Reality universe={len(base_coins)} completed={len(completed)} pending={len(pending)}")
        for offset in range(0, len(pending), args.batch_size):
            batch = pending[offset:offset + args.batch_size]
            print(f"batch {len(completed) + 1}-{len(completed) + len(batch)}: {','.join(batch)}", flush=True)
            try:
                events = build_reality_ledger(
                    api, {coin: universe[coin] for coin in batch}, args.start_date,
                    raw_dir=REALITY_RAW_DIR,
                )
                write_ledger(events, args.output)
            except Exception as exc:
                state.setdefault("failed", []).append({
                    "base_coins": batch,
                    "error": f"{type(exc).__name__}: {exc}",
                    "at": dt.datetime.now(dt.UTC).isoformat(),
                })
                _save_state(args.state, state)
                raise
            completed.update(batch)
            state["failed"] = [failure for failure in state.get("failed", [])
                                if failure.get("base_coins") != batch]
            state["completed"] = sorted(completed)
            state["last_batch"] = batch
            state["last_event_count"] = len(events)
            _save_state(args.state, state)
            print(f"completed {len(completed)}/{len(base_coins)}; events in batch={len(events)}", flush=True)
        print(f"complete: {len(completed)} instruments -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

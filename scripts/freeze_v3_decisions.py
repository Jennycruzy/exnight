"""Freeze V3 forward decisions before the 20:00 ET sell cutoff and commit them locally.

Run each weekday at 19:30 ET (23:30 UTC while US daylight time is in force):

    30 23 * * 1-5 cd /path/to/exnight && .venv/bin/python scripts/freeze_v3_decisions.py \
        >> data/raw/recorder/freeze_v3.log 2>&1

Writes data/results/signals_v3_<UTC stamp>.csv and its run manifest, then commits exactly
those two files. The commit refuses to run under any identity other than the configured
jennycruzy one and carries no attribution lines. Pushing is left to the operator.

After the commit, if EXNIGHT_ANCHOR_KEY is set (in the environment or .env), the commit and
the sha256 of both files are written into an Arbitrum One transaction (exnight/anchor.py), and
the record goes to data/anchors/anchor_v3_<UTC stamp>.json in a second commit. An anchoring
failure is logged and exits 3, but never undoes the freeze. With no key it logs a skip.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

from exnight import anchor, strategy_v3  # noqa: E402

NAME = "jennycruzy"
EMAIL = "103373316+Jennycruzy@users.noreply.github.com"


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()


def main() -> int:
    if (_git("config", "user.name"), _git("config", "user.email")) != (NAME, EMAIL):
        print("refusing to commit: repository identity is not jennycruzy", file=sys.stderr)
        return 1
    now = dt.datetime.now(dt.UTC).replace(microsecond=0)
    tag = f"_{now:%Y%m%dT%H%MZ}"
    frame = strategy_v3.forward(now=now, tag=tag)
    paths = [f"data/results/signals_v3{tag}.csv", f"data/results/run_manifest_v3{tag}.json"]
    counts = frame.drop_duplicates("event_id").verdict.value_counts().to_dict()
    _git("add", "--", *paths)
    _git("commit", "--only", "-q", "-m", f"Freeze V3 forward decisions at {now.isoformat()}", "--", *paths)
    commit = _git("rev-parse", "HEAD")
    print(f"{now.isoformat()} froze {len(frame)} rows {counts}; commit {commit[:7]}")
    return anchor_freeze(commit, paths, now, tag)


def anchor_freeze(commit: str, paths: list[str], now: dt.datetime, tag: str) -> int:
    load_dotenv(ROOT / ".env")
    key = os.environ.get("EXNIGHT_ANCHOR_KEY", "").strip()
    if not key:
        print("anchor skipped: EXNIGHT_ANCHOR_KEY not set")
        return 0
    try:
        payload = anchor.build_payload(commit, paths, ROOT)
        rpc = anchor.Rpc(os.environ.get("ARBITRUM_RPC_URL", anchor.DEFAULT_RPC))
        record = anchor.anchor(payload, key, rpc, send=True)
    except Exception as exc:  # the freeze is already committed; report and stop
        print(f"anchor FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3
    cutoff = anchor.next_cutoff(now)
    record.update(frozen_at_utc=now.isoformat(), cutoff_utc=cutoff.isoformat(), commit=commit, files=paths,
                  before_cutoff=record["block_time_utc"] < cutoff.isoformat())
    out = f"data/anchors/anchor_v3{tag}.json"
    (ROOT / out).parent.mkdir(parents=True, exist_ok=True)
    (ROOT / out).write_text(json.dumps(record, indent=1) + "\n")
    _git("add", "--", out)
    _git("commit", "--only", "-q", "-m", f"Anchor V3 freeze {tag[1:]} on Arbitrum One: {record['tx_hash']}", "--", out)
    flag = "" if record["before_cutoff"] else " (AFTER CUTOFF)"
    print(f"anchored {commit[:7]} in block {record['block_number']} at {record['block_time_utc']}{flag}: "
          f"{record['explorer']}")
    return 0 if record["before_cutoff"] else 4


if __name__ == "__main__":
    raise SystemExit(main())

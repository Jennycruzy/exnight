"""Freeze V3 forward decisions before the 20:00 ET sell cutoff and commit them locally.

Run each weekday at 19:30 ET (23:30 UTC while US daylight time is in force):

    30 23 * * 1-5 cd /home/ubuntu/exnight && .venv/bin/python scripts/freeze_v3_decisions.py \
        >> data/raw/recorder/freeze_v3.log 2>&1

Writes data/results/signals_v3_<UTC stamp>.csv and its run manifest, then commits exactly
those two files. The commit refuses to run under any identity other than the configured
jennycruzy one and carries no attribution lines. Pushing is left to the operator.
"""
from __future__ import annotations

import datetime as dt
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from exnight import strategy_v3  # noqa: E402

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
    print(f"{now.isoformat()} froze {len(frame)} rows {counts}; commit {_git('rev-parse', '--short', 'HEAD')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

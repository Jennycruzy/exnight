"""Score every V3 forward group whose recording window has closed, and commit the evidence.

Run hourly from cron:

    20 * * * * cd /home/ubuntu/exnight && .venv/bin/python scripts/score_due_v3.py \
        >> data/raw/recorder/score_v3.log 2>&1

For each group whose window ended at least five minutes ago and whose score is not yet
committed, it runs scripts/score_forward_v3.py, force-adds the raw recording (the recorder
directory is otherwise ignored), commits exactly those files as jennycruzy with no attribution,
rebuilds the public dashboard onto gh-pages, and then tries to push both branches. Pushing
goes through the VS Code Git credential helper, so it only succeeds while a VS Code window is
connected; otherwise the commits wait locally and the log says so. An INCOMPLETE score is
still committed: a gap is part of the evidence.
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEDULE = ROOT / "data" / "forward" / "v3_schedule.json"
NAME = "jennycruzy"
EMAIL = "103373316+Jennycruzy@users.noreply.github.com"
SETTLE = dt.timedelta(minutes=5)


def _git(*args: str, env: dict | None = None, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, env=env, timeout=timeout)


def _tracked(path: str) -> bool:
    return bool(_git("ls-files", "--", path).stdout.strip())


def _push_env() -> dict | None:
    """Environment for the VS Code credential helper, if a VS Code server is present."""
    newest = lambda pattern: max(glob.glob(os.path.expanduser(pattern)), key=os.path.getmtime, default=None)
    askpass = newest("~/.vscode-server/bin/*/extensions/git/dist/askpass.sh")
    socket = newest("/run/user/%d/vscode-git-*.sock" % os.getuid())
    if not askpass or not socket:
        return None
    base = Path(askpass).parents[3]
    return {**os.environ, "GIT_ASKPASS": askpass, "VSCODE_GIT_ASKPASS_NODE": str(base / "node"),
            "VSCODE_GIT_ASKPASS_MAIN": str(Path(askpass).with_name("askpass-main.js")),
            "VSCODE_GIT_ASKPASS_EXTRA_ARGS": "", "VSCODE_GIT_IPC_HANDLE": socket, "GIT_TERMINAL_PROMPT": "0"}


def _push(branch: str) -> str:
    env = _push_env()
    if env is None:
        return f"{branch}: not pushed (no VS Code credential helper found)"
    try:
        result = _git("push", "origin", branch, env=env, timeout=90)
    except subprocess.TimeoutExpired:
        return f"{branch}: not pushed (timed out; VS Code probably disconnected)"
    return f"{branch}: pushed" if result.returncode == 0 else f"{branch}: not pushed ({result.stderr.strip()[-160:]})"


def main() -> int:
    ap = argparse.ArgumentParser(description="Score and commit closed V3 forward windows")
    ap.add_argument("--schedule", type=Path, default=SCHEDULE)
    ap.add_argument("--dry-run", action="store_true", help="score only; no commit, publish or push")
    args = ap.parse_args()
    if (_git("config", "user.name").stdout.strip(), _git("config", "user.email").stdout.strip()) != (NAME, EMAIL):
        print("refusing to commit: repository identity is not jennycruzy", file=sys.stderr)
        return 1
    now = dt.datetime.now(dt.UTC)
    plan = json.loads(args.schedule.read_text())
    scored_any = False
    for group in plan["groups"]:
        label = group["label"]
        score = f"data/results/forward_score_{label}.json"
        if now < dt.datetime.fromisoformat(group["end"]) + SETTLE or _tracked(score):
            continue
        run = subprocess.run([sys.executable, str(ROOT / "scripts" / "score_forward_v3.py"), label,
                              "--schedule", str(args.schedule)],
                             cwd=ROOT, capture_output=True, text=True, timeout=600)
        if not (ROOT / score).exists():
            print(f"{now.isoformat()} {label}: scorer produced no file\n{run.stderr[-800:]}")
            continue
        status = json.loads((ROOT / score).read_text()).get("status")
        if args.dry_run:
            print(f"{now.isoformat()} {label}: {status} (dry run; nothing committed)")
            continue
        paths = [score]
        recording = f"data/raw/recorder/{label}"
        if (ROOT / recording).is_dir():
            paths.append(recording)
        added = _git("add", "-f", "--", *paths)
        commit = _git("commit", "--only", "-q", "-m", f"Score V3 forward recording {label}", "--", *paths)
        if added.returncode or commit.returncode:
            print(f"{now.isoformat()} {label}: commit failed: {added.stderr}{commit.stderr}")
            continue
        scored_any = True
        print(f"{now.isoformat()} {label}: {status}; committed {_git('rev-parse', '--short', 'HEAD').stdout.strip()}")
    if scored_any:
        publish = subprocess.run(["bash", str(ROOT / "scripts" / "publish_pages.sh")], cwd=ROOT,
                                 capture_output=True, text=True, timeout=600)
        print(publish.stdout.strip() or publish.stderr.strip()[-400:])
        print(_push("main"))
        print(_push("gh-pages"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

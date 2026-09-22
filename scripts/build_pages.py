"""Build the browser-only Exnight dashboard published by GitHub Pages."""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import shutil
import sys
from pathlib import Path

PROJECT_PATH = Path(__file__).resolve().parent.parent
if str(PROJECT_PATH) not in sys.path:
    sys.path.insert(0, str(PROJECT_PATH))

from dashboard.server import (
    PROJECT_ROOT,
    _symbol_aliases,
    dashboard_data,
    decision_lookup,
)


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def public_snapshot(project_root: Path, now: dt.datetime | None = None) -> dict[str, object]:
    snapshot = dashboard_data(project_root, now=now)
    snapshot["mode"] = "PUBLIC_SNAPSHOT"
    snapshot["downloads"] = []
    snapshot["observation"]["message"] = (
        "Public evidence snapshot. Recorder collection and scoring continue on the private service."
    )
    return snapshot


def decision_index(project_root: Path, now: dt.datetime | None = None) -> dict[str, object]:
    path = project_root / "data" / "results" / "signals_v1.csv"
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    aliases = sorted({alias for row in rows for alias in _symbol_aliases(row)})
    return {alias: decision_lookup(project_root / "data", alias, now=now) for alias in aliases}


def build(project_root: Path, output: Path, snapshot_path: Path | None = None,
          now: dt.datetime | None = None) -> None:
    output.mkdir(parents=True, exist_ok=True)
    for name in ("index.html", "app.js", "style.css"):
        shutil.copy2(project_root / "dashboard" / name, output / name)
    (output / ".nojekyll").write_text("", encoding="utf-8")
    if snapshot_path and snapshot_path.is_file():
        summary = json.loads(snapshot_path.read_text(encoding="utf-8"))
    else:
        summary = public_snapshot(project_root, now=now)
    summary["mode"] = "PUBLIC_SNAPSHOT"
    summary["downloads"] = []
    write_json(output / "api" / "summary.json", summary)
    write_json(output / "api" / "decisions.json", decision_index(project_root, now=now))


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the Exnight GitHub Pages site")
    parser.add_argument("--root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--output", type=Path, default=Path("_site"))
    parser.add_argument("--snapshot", type=Path,
                        default=Path("data/results/public_dashboard_snapshot.json"))
    parser.add_argument("--write-snapshot", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    if args.write_snapshot:
        write_json(args.write_snapshot, public_snapshot(root))
        return 0
    snapshot = args.snapshot if args.snapshot.is_absolute() else root / args.snapshot
    build(root, args.output.resolve(), snapshot_path=snapshot)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

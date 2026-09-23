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
    _signal_row,
    _signals,
    _symbol_aliases,
    dashboard_data,
)

PUBLIC_EVIDENCE = {
    "competition_scorecard.json": "Walk-forward scorecard",
    "competition_backtest_manifest.json": "Frozen backtest manifest",
    "forward_score_20260922.json": "September 22 forward score",
    "forward_capacity_20260922.json": "September 22 book capacity",
    "always_exit_baseline.json": "Always-step-out comparison",
}


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def public_snapshot(project_root: Path, now: dt.datetime | None = None) -> dict[str, object]:
    snapshot = dashboard_data(project_root, now=now)
    snapshot["mode"] = "PUBLIC_SNAPSHOT"
    snapshot["downloads"] = []
    snapshot["observation"]["message"] = (
        "Public evidence snapshot. " + snapshot["observation"]["message"]
    )
    return snapshot


def decision_index(project_root: Path, now: dt.datetime | None = None) -> dict[str, object]:
    path = project_root / "data" / "results" / "signals_v1.csv"
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    aliases = sorted({alias for row in rows for alias in _symbol_aliases(row)})
    index = {}
    for alias in aliases:
        matches = [row for row in rows if alias in _symbol_aliases(row)]
        by_date = {}
        for event_date in sorted({row.get("ex_date", "") for row in matches if row.get("ex_date")}):
            dated = [row for row in matches if row.get("ex_date") == event_date]
            dated.sort(key=lambda row: int(float(row.get("notional_usd", 0) or 0)))
            by_date[event_date] = [_signal_row(row) for row in dated]
        if by_date:
            index[alias] = {
                "status": "FOUND", "symbol": matches[0].get("symbol"),
                "spot_symbol": matches[0].get("spot_symbol"), "events": by_date,
            }
    return index


def signal_date_index(project_root: Path, now: dt.datetime | None = None) -> dict[str, object]:
    now = now or dt.datetime.now(dt.timezone.utc)
    _, meta = _signals(project_root / "data", now)
    index = {}
    for event_date in meta.get("available_dates", []):
        rows, dated_meta = _signals(project_root / "data", now, requested_date=event_date)
        index[event_date] = {"meta": dated_meta, "rows": [_signal_row(row) for row in rows]}
    return index


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
    # The headline comparison and V3's forward view are always rebuilt from committed results,
    # so the published page shows the latest frozen decisions and scores.
    from dashboard import v3_view
    summary["comparison"] = v3_view.comparison(project_root)
    summary["v3"] = v3_view.v3(project_root)
    from dashboard.server import LIMITS
    summary["limits"] = list(LIMITS)
    downloads = []
    for name, label in PUBLIC_EVIDENCE.items():
        source = project_root / "data" / "results" / name
        if source.is_file():
            destination = output / "evidence" / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            downloads.append({"name": name, "label": label, "href": f"evidence/{name}"})
    summary["downloads"] = downloads
    write_json(output / "api" / "summary.json", summary)
    write_json(output / "api" / "decisions.json", decision_index(project_root, now=now))
    write_json(output / "api" / "signal_dates.json", signal_date_index(project_root, now=now))


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

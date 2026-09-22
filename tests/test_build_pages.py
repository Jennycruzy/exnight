import csv
import json
from pathlib import Path

from scripts.build_pages import build


def test_build_pages_creates_static_decision_lookup(tmp_path):
    (tmp_path / "dashboard").mkdir()
    for name in ("index.html", "app.js", "style.css"):
        (tmp_path / "dashboard" / name).write_text(name, encoding="utf-8")
    results = tmp_path / "data/results"
    results.mkdir(parents=True)
    with (results / "signals_v1.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "event_id", "symbol", "spot_symbol", "ex_date", "notional_usd", "verdict",
        ])
        writer.writeheader()
        writer.writerow({
            "event_id": "rAPH-2026-09-22-1", "symbol": "rAPH", "spot_symbol": "RAPHUSDT",
            "ex_date": "2026-09-22", "notional_usd": "1000", "verdict": "HOLD",
        })
    snapshot = results / "public_dashboard_snapshot.json"
    snapshot.write_text(json.dumps({"mode": "READ_ONLY", "downloads": []}), encoding="utf-8")
    output = tmp_path / "site"
    now = __import__("datetime").datetime.fromisoformat("2026-09-21T12:00:00+00:00")
    build(tmp_path, output, snapshot_path=snapshot, now=now)
    decisions = json.loads((output / "api/decisions.json").read_text(encoding="utf-8"))
    assert decisions["APH"]["rows"][0]["verdict"] == "HOLD"
    assert decisions["RAPHUSDT"]["spot_symbol"] == "RAPHUSDT"
    assert (output / ".nojekyll").is_file()

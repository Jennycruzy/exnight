import csv
import json
from pathlib import Path

from dashboard.server import dashboard_data, recorder_summary


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_recorder_summary_reports_book_coverage_and_gap(tmp_path):
    rows = [
        {"ts": "2026-09-20T12:00:00Z", "symbol": "RAVGOUSDT", "ticker": {}, "orderbook": {"bids": [[1, 1]], "asks": [[2, 1]]}},
        {"ts": "2026-09-20T12:01:00Z", "symbol": "RAVGOUSDT", "ticker": {}, "orderbook": {"bids": [], "asks": []}},
        {"ts": "2026-09-20T12:00:00Z", "symbol": "RSATAUSDT", "ticker": {"lastPrice": "1"}, "orderbook": {}},
    ]
    path = tmp_path / "data/raw/recorder/run.jsonl"
    _write(path, "\n".join(json.dumps(row) for row in rows) + "\n")
    result = recorder_summary(tmp_path / "data", now=__import__("datetime").datetime.fromisoformat("2026-09-20T12:02:00+00:00"))
    assert result["status"] == "FAIL"
    assert result["symbols"]["RAVGOUSDT"]["book_coverage"] == 0.5
    assert result["symbols"]["RSATAUSDT"]["book_coverage"] == 0
    assert any("RVSTUSDT: no samples" in error for error in result["errors"])


def test_dashboard_is_read_only_and_flags_manifest_gap(tmp_path):
    data = tmp_path / "data"
    results = data / "results"
    results.mkdir(parents=True)
    with (results / "signals_v1.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["event_id", "symbol", "spot_symbol", "ex_date", "notional_usd", "verdict"])
        writer.writeheader()
        writer.writerows([
            {"event_id": "rA-2026-09-21-1", "symbol": "rA", "spot_symbol": "RAUSDT", "ex_date": "2026-09-21", "notional_usd": "1000", "verdict": "HOLD"},
            {"event_id": "rS-2026-09-21-1", "symbol": "rS", "spot_symbol": "RSUSDT", "ex_date": "2026-09-21", "notional_usd": "1000", "verdict": "NO_SIGNAL"},
        ])
    (results / "run_manifest_v1.json").write_text(json.dumps({"forward_events_decided": {"rA-2026-09-21-1": "HOLD"}}))
    result = dashboard_data(tmp_path, now=__import__("datetime").datetime.fromisoformat("2026-09-20T12:02:00+00:00"))
    assert result["mode"] == "READ_ONLY"
    assert result["provenance"]["status"] == "WARN"
    assert result["provenance"]["missing_events"] == ["rS-2026-09-21-1"]
    assert result["forward_score"]["status"] == "PENDING"


def test_dashboard_can_select_an_explicit_signal_date(tmp_path):
    results = tmp_path / "data/results"
    results.mkdir(parents=True)
    with (results / "signals_v1.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["event_id", "symbol", "spot_symbol", "ex_date", "notional_usd", "verdict"])
        writer.writeheader()
        writer.writerows([
            {"event_id": "rA-2026-09-21-1", "symbol": "rA", "spot_symbol": "RAUSDT", "ex_date": "2026-09-21", "notional_usd": "1000", "verdict": "HOLD"},
            {"event_id": "rA-2026-09-22-1", "symbol": "rA", "spot_symbol": "RAUSDT", "ex_date": "2026-09-22", "notional_usd": "1000", "verdict": "NO_SIGNAL"},
        ])
    result = dashboard_data(tmp_path, now=__import__("datetime").datetime.fromisoformat("2026-09-20T12:02:00+00:00"), signal_date="2026-09-22")
    assert result["signals"]["meta"]["event_date"] == "2026-09-22"
    assert result["signals"]["rows"][0]["verdict"] == "NO_SIGNAL"
    assert result["signals"]["meta"]["available_dates"] == ["2026-09-21", "2026-09-22"]

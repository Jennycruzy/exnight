import csv
import json
from pathlib import Path

from dashboard.server import dashboard_data, decision_lookup, recorder_summary


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
    result = recorder_summary(
        tmp_path / "data",
        now=__import__("datetime").datetime.fromisoformat("2026-09-20T12:02:00+00:00"),
        expected_symbols=("RAVGOUSDT", "RVSTUSDT", "RSATAUSDT"),
    )
    assert result["status"] == "FAIL"
    assert result["symbols"]["RAVGOUSDT"]["book_coverage"] == 0.5
    assert result["symbols"]["RSATAUSDT"]["book_coverage"] == 0
    assert any("RVSTUSDT: no samples" in error for error in result["errors"])


def test_recorder_summary_uses_newest_run_folder(tmp_path):
    old_path = tmp_path / "data/raw/recorder/old/run.jsonl"
    new_path = tmp_path / "data/raw/recorder/new/run.jsonl"
    _write(old_path, json.dumps({"ts": "2026-09-20T12:00:00Z", "symbol": "RAPHUSDT"}) + "\n")
    _write(new_path, json.dumps({"ts": "2026-09-20T12:10:00Z", "symbol": "RAPHUSDT"}) + "\n")
    __import__("os").utime(old_path, (1, 1))
    __import__("os").utime(new_path, (2, 2))
    result = recorder_summary(
        tmp_path / "data",
        now=__import__("datetime").datetime.fromisoformat("2026-09-20T12:11:00+00:00"),
    )
    assert result["symbols"]["RAPHUSDT"]["rows"] == 1
    assert result["symbols"]["RAPHUSDT"]["first_ts"] == "2026-09-20T12:10:00Z"


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


def test_dashboard_exposes_walk_forward_validation(tmp_path):
    results = tmp_path / "data/results"
    results.mkdir(parents=True)
    (results / "competition_backtest_manifest.json").write_text(json.dumps({
        "oos_calendar_days": 47, "slippage_sensitivity_bps": [10, 25, 50, 100],
    }))
    (results / "competition_scorecard.json").write_text(json.dumps({
        "name": "walk-forward OOS performance of the Exnight selection procedure",
        "sample": {"resolved_usable": 127, "eligible_ex_ante": 56},
        "oos_concatenated_non_overlapping_folds": {
            "policy": {"event_count": 39, "trade_count": 0, "total_return": -0.001},
            "benchmark": {"total_return": -0.001}, "active": {"total_return": 0},
        },
        "folds": [{"fold": "OOS_1", "test_events": 39, "test_trades": 0}],
    }))
    result = dashboard_data(tmp_path)
    assert result["competition"]["status"] == "AVAILABLE"
    assert result["competition"]["sample"]["eligible_ex_ante"] == 56
    assert result["competition"]["oos"]["policy"]["trade_count"] == 0


def test_completed_forward_window_uses_saved_cadence_instead_of_live_freshness(tmp_path):
    results = tmp_path / "data/results"
    results.mkdir(parents=True)
    (results / "forward_score_20260922.json").write_text(json.dumps({
        "status": "INCOMPLETE", "checked_at": "2026-09-22T14:30:00Z", "errors": [],
        "symbols": {"RSATAUSDT": {
            "rows": 1348, "first_ts": "2026-09-21T16:02:00Z",
            "last_ts": "2026-09-22T14:29:00Z", "max_gap_seconds": 63,
            "gaps_over_limit": 0, "ticker_rows": 1348, "nonempty_book_rows": 0,
        }},
        "results": [{"symbol": "rSATA", "ex_date": "2026-09-22", "complete": True},
                    {"symbol": "rAPH", "ex_date": "2026-09-22", "complete": False}],
    }))
    (results / "forward_capacity_20260922.json").write_text(json.dumps({
        "as_of": "2026-09-22T14:29:00Z",
        "events": [{"symbol": "rSATA", "nonempty_public_book_samples": 0}],
    }))
    now = __import__("datetime").datetime.fromisoformat("2026-09-23T05:00:00+00:00")
    result = dashboard_data(tmp_path, now=now)
    assert result["observation"]["status"] == "SCORED"
    assert result["observation"]["event_date"] == "2026-09-22"
    assert result["recorder"]["status"] == "PASS"
    assert result["recorder"]["sample_count"] == 1348
    assert result["forward_score"]["status"] == "INCOMPLETE"
    assert "rAPH" in result["forward_score"]["message"]
    assert result["depth"]["book_supported_count"] == 0


def test_decision_lookup_accepts_consumer_symbol_formats(tmp_path):
    results = tmp_path / "data/results"
    results.mkdir(parents=True)
    with (results / "signals_v1.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "event_id", "symbol", "spot_symbol", "ex_date", "notional_usd", "verdict", "reason",
        ])
        writer.writeheader()
        writer.writerows([
            {"event_id": "rAPH-2026-09-22-1", "symbol": "rAPH", "spot_symbol": "RAPHUSDT",
             "ex_date": "2026-09-22", "notional_usd": "100", "verdict": "HOLD", "reason": "guarded"},
            {"event_id": "rAPH-2026-09-22-1", "symbol": "rAPH", "spot_symbol": "RAPHUSDT",
             "ex_date": "2026-09-22", "notional_usd": "1000", "verdict": "EXIT", "reason": "edge"},
        ])
    now = __import__("datetime").datetime.fromisoformat("2026-09-21T12:02:00+00:00")
    for query in ("rAPH", "RAPHUSDT", "APH"):
        result = decision_lookup(tmp_path / "data", query, now=now)
        assert result["status"] == "FOUND"
        assert result["event_date"] == "2026-09-22"
        assert [row["verdict"] for row in result["rows"]] == ["HOLD", "EXIT"]


def test_decision_lookup_does_not_guess_unknown_tokens(tmp_path):
    results = tmp_path / "data/results"
    results.mkdir(parents=True)
    (results / "signals_v1.csv").write_text(
        "event_id,symbol,spot_symbol,ex_date,notional_usd,verdict\n"
        "rAPH-2026-09-22-1,rAPH,RAPHUSDT,2026-09-22,100,HOLD\n",
        encoding="utf-8",
    )
    result = decision_lookup(tmp_path / "data", "UNKNOWN")
    assert result["status"] == "NOT_EVALUATED"
    assert "rows" not in result

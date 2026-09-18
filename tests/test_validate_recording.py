import datetime as dt
import json

from scripts.validate_recording import read_rows, validate


def row(ts: str, symbol: str = "RAVGOUSDT", book: bool = True) -> dict:
    return {
        "ts": ts,
        "symbol": symbol,
        "ticker": {"bid1Price": "1", "ask1Price": "2"},
        "orderbook": {"bids": [["1", "1"]], "asks": [["2", "1"]]} if book else {},
    }


def test_regular_cadence_passes(tmp_path):
    path = tmp_path / "samples.jsonl"
    path.write_text("\n".join(json.dumps(row(f"2026-09-18T00:0{i}:00Z")) for i in range(3)) + "\n")
    by_symbol, errors = read_rows([path])
    report = validate(by_symbol, errors, expected_symbols=["RAVGOUSDT"], max_gap_seconds=120)
    assert report["status"] == "PASS"
    assert report["symbols"]["RAVGOUSDT"]["nonempty_book_rows"] == 3


def test_large_gap_fails():
    rows = [
        (dt.datetime(2026, 9, 18, 0, 0, tzinfo=dt.UTC), row("2026-09-18T00:00:00Z")),
        (dt.datetime(2026, 9, 18, 0, 5, tzinfo=dt.UTC), row("2026-09-18T00:05:00Z")),
    ]
    report = validate({"RAVGOUSDT": rows}, [], max_gap_seconds=120)
    assert report["status"] == "FAIL"
    assert report["symbols"]["RAVGOUSDT"]["gaps_over_limit"] == 1


def test_missing_expected_symbol_fails():
    report = validate({}, [], expected_symbols=["RVSTUSDT"])
    assert report["status"] == "FAIL"
    assert "RVSTUSDT: no rows" in report["errors"]


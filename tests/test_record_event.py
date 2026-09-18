import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import record_event  # noqa: E402


class FakeAPI:
    def market_states(self):
        return {"market": "US"}

    def tickers(self):
        return [{"symbol": "RXUSDT", "bid1Price": "1", "ask1Price": "2"}]

    def orderbook(self, symbol, limit=1000):
        return {"asks": [["2", "1"]], "bids": [["1", "1"]], "ts": "0"}


def test_sample_and_append_are_append_only(tmp_path, monkeypatch):
    monkeypatch.setattr(record_event, "RAW", tmp_path)
    now = dt.datetime(2026, 9, 18, 23, 59, tzinfo=dt.UTC)
    rows = record_event.sample(FakeAPI(), ["RXUSDT", "RYUSDT"], now)
    assert [r["symbol"] for r in rows] == ["RXUSDT", "RYUSDT"] and rows[1]["ticker"] is None
    p = record_event.append("evt", rows, now)
    record_event.append("evt", rows, now)
    lines = [json.loads(l) for l in p.read_text().splitlines()]
    assert p.name == "20260918.jsonl" and len(lines) == 2 and lines[0]["orderbook"]["bids"] == [["1", "1"]]


def test_window_parsing_requires_timezone():
    import pytest
    with pytest.raises(ValueError):
        record_event._utc("2026-09-18T00:00:00")
    assert record_event._utc("2026-09-18T00:00:00Z").tzinfo is dt.UTC

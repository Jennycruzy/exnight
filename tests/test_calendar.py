"""The ledger regenerates byte-for-byte from the saved sources (offline)."""
import datetime as dt
import json
from decimal import Decimal

from exnight.calendar import (LEDGER_PATH, build_ledger, build_reality_ledger,
                              parse_dividend_notice_2026_07_24, parse_weekend_list_2026_07_17)
from exnight.market import SpotSymbol
from exnight.events import EventType


def _universe_from_ledger():
    # Offline stand-in for the live symbol list: the spot symbols recorded in the ledger.
    import datetime as dt
    out = {}
    for line in LEDGER_PATH.read_text().splitlines():
        e = json.loads(line)
        out[e["symbol"]] = SpotSymbol(
            symbol=e["spot_symbol"], base_coin=e["symbol"], quote_coin="USDT",
            maker_fee=Decimal("0.001"), taker_fee=Decimal("0.001"), price_precision=2,
            quantity_precision=4, min_trade_usdt=Decimal(10), status="online",
            open_time=dt.datetime(2026, 6, 10, tzinfo=dt.UTC))
    return out


def test_notice_parses_63_rows_59_tickers():
    rows = parse_dividend_notice_2026_07_24()
    assert len(rows) == 63
    assert len({r["symbol"] for r in rows}) == 59
    assert sum(r["symbol"] == "rSATA" for r in rows) == 5
    mu = [r for r in rows if r["symbol"] == "rMU"][0]
    assert str(mu["gross_dividend_per_share"]) == "0.15"
    assert mu["exchange_ex_date"].isoformat() == "2026-07-06"


def test_weekend_list_has_61():
    w = parse_weekend_list_2026_07_17()
    assert len(w) == 61 and {"rMU", "rQQQ", "rTSM", "rVOO"} <= w


def test_ledger_regenerates_identically():
    events = build_ledger(_universe_from_ledger())
    regenerated = "".join(json.dumps(e.model_dump(mode="json"), sort_keys=True) + "\n" for e in events)
    assert regenerated == LEDGER_PATH.read_text()


def test_no_event_is_eligibility_verified_yet():
    for e in build_ledger(_universe_from_ledger()):
        assert e.eligibility_verified is False
        assert e.bitget_snapshot_time is None
        assert e.net_dividend_per_share == e.gross_dividend_per_share * Decimal("0.70")
        assert e.ex_dividend_date == e.exchange_ex_date
        assert e.cash_dividend_per_share == e.gross_dividend_per_share
        assert e.cash_dividend_basis == "GROSS"
        assert e.status == "completed"


def test_reality_ledger_uses_api_rows_and_keeps_unresolved_basis(tmp_path):
    class FakeAPI:
        def __init__(self):
            self.last_fetch_at = dt.datetime(2026, 9, 16, 12, tzinfo=dt.UTC)
            self.last_request = {"path": "/api/v3/reality/market/dividends", "params": {"code": "ASSET"}}
            self.last_raw_response = "{\"code\":\"00000\"}"

        def reality_stock_info(self, symbol):
            self.last_request = {"path": "/api/v3/reality/market/stock-info", "params": {"symbol": symbol}}
            return {"symbol": symbol, "code": "ASSET"}

        def iter_reality_dividends(self, code, limit=100):
            rows = [
                {"type": "cash_dividend", "announcementDate": "1782230400000",
                 "recordDate": "1783267200000", "exrightDate": "1783267200000",
                 "dividendDate": "1784563200000", "dividendPerShare": "0.15"},
                {"type": "stock_split", "announcementDate": "1782230400000",
                 "recordDate": None, "exrightDate": "1783267200000",
                 "dividendDate": None, "splitNumerator": "2", "splitDenominator": "1"},
            ]
            yield {"list": rows, "cursor": None}, rows

    spot = SpotSymbol(
        symbol="ASSETUSDT", base_coin="asset-token", quote_coin="USDT",
        maker_fee=Decimal("0.001"), taker_fee=Decimal("0.001"),
        price_precision=2, quantity_precision=4, min_trade_usdt=Decimal("10"),
        status="online", open_time=dt.datetime(2026, 6, 2, tzinfo=dt.UTC),
    )
    events = build_reality_ledger(
        FakeAPI(), {spot.base_coin: spot}, dt.date(2026, 6, 1),
        as_of=dt.datetime(2026, 9, 16, tzinfo=dt.UTC), raw_dir=tmp_path, notice_rows=[],
    )
    assert [e.event_type for e in events] == [EventType.CASH_DIV, EventType.SPLIT]
    assert events[0].exchange_ex_date == dt.date(2026, 7, 6)
    cash = events[0]
    assert cash.symbol == "asset-token" and cash.underlying == "ASSET"
    assert cash.cash_dividend_per_share == Decimal("0.15")
    assert cash.cash_dividend_basis == "UNRESOLVED"
    assert cash.gross_dividend_per_share is None
    assert events[1].adjustment_ratio == Decimal("2")
    assert list(tmp_path.rglob("*.json"))


def test_ledger_writer_is_append_only(tmp_path):
    event = build_ledger(_universe_from_ledger())[0]
    path = tmp_path / "events.jsonl"
    from exnight.calendar import write_ledger
    write_ledger([event], path)
    before = path.read_bytes()
    write_ledger([event], path)
    assert path.read_bytes() == before

    changed = event.model_copy(update={"notes": event.notes + ["changed"]})
    import pytest
    with pytest.raises(ValueError, match="append-only"):
        write_ledger([changed], path)

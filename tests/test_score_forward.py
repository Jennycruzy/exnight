import datetime as dt
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from score_forward import score_event  # noqa: E402

from exnight.events import CorporateAction, EventType  # noqa: E402


def test_score_forward_uses_cutoff_prices_and_labels_ticker_only():
    event = CorporateAction(
        event_id="rX-2026-09-21-1", symbol="rX", underlying="X", spot_symbol="RXUSDT",
        event_type=EventType.CASH_DIV, announcement_date=None, exchange_ex_date=dt.date(2026, 9, 21),
        exchange_record_date=None, bitget_snapshot_time=None, payment_date=None,
        gross_dividend_per_share=Decimal("1"), withholding_rate=Decimal("0.30"),
        net_dividend_per_share=Decimal("0.7"), cash_dividend_per_share=Decimal("1"),
        cash_dividend_basis="GROSS", net_dividend_verified=True, eligibility_verified=False,
        weekend_list_2026_07_17=None, source_key="test", source_url="test", label="OBSERVED",
        instrument_snapshot={"symbol": "RXUSDT", "taker_fee": "0.001", "open_time": "2026-06-01T00:00:00+00:00",
                             "base_coin": "rX", "quote_coin": "USDT", "maker_fee": "0.001",
                             "price_precision": 2, "quantity_precision": 2, "min_trade_usdt": "10",
                             "status": "online"},
    )
    pre = dt.datetime(2026, 9, 21, 0, 0, tzinfo=dt.UTC)  # Sunday 20:00 ET
    post = dt.datetime(2026, 9, 21, 8, 0, tzinfo=dt.UTC)  # Monday 04:00 ET
    rows = [
        (pre - dt.timedelta(seconds=30), {"ticker": {"lastPrice": "100", "bid1Price": "99.9", "ask1Price": "100.1", "bid1Size": "100", "ask1Size": "100"}, "orderbook": {"bids": [], "asks": []}}),
        (post, {"ticker": {"lastPrice": "99", "bid1Price": "98.9", "ask1Price": "99.1", "bid1Size": "100", "ask1Size": "100"}, "orderbook": {"bids": [], "asks": []}}),
    ]
    rule = {"rung": "premarket_0400", "rule_id": "test", "estimate": {"pdr_hat": 0.96, "se": 0.18}, "notionals_usd": [1000]}
    result = score_event(event, rows, rule, {}, max_lateness_seconds=60, notionals=(1000,))
    assert result["complete"] and result["realized_pdr"] == 1.0
    assert result["notionals"][0]["sell_book_source"] == "ticker_only"

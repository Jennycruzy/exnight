from decimal import Decimal
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from paper_trade import sized_qty  # noqa: E402


def test_sized_qty_uses_executable_side_and_exchange_precision():
    book = {
        "orderbook": {
            "asks": [["100.01", "20"], ["101.00", "20"]],
            "bids": [["100.00", "20"], ["99.50", "20"]],
        },
        "ticker": None,
    }
    price, qty, visible, source = sized_qty(
        book, "buy", 1000, 0.005, 2, 2, Decimal("10"), "ioc"
    )
    assert (price, qty, source) == ("100.01", "9.99", "public_book")
    assert visible == 20


def test_sized_qty_accepts_complete_ticker_only_quote():
    book = {
        "orderbook": {"asks": [], "bids": []},
        "ticker": {"ask1Price": "1.01", "bid1Price": "1.00", "ask1Size": "100", "bid1Size": "100"},
    }
    price, qty, visible, source = sized_qty(
        book, "sell", 10, 0.005, 2, 2, Decimal("5"), "ioc"
    )
    assert (price, qty, source) == ("1.00", "10.00", "ticker_only")
    assert visible == 100

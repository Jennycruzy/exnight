"""The ledger regenerates byte-for-byte from the saved sources (offline)."""
import json
from decimal import Decimal

from exnight.calendar import (LEDGER_PATH, build_ledger, parse_dividend_notice_2026_07_24,
                              parse_weekend_list_2026_07_17)
from exnight.market import SpotSymbol


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

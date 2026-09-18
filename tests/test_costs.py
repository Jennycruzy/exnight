import pandas as pd
import pytest

from exnight.costs import cost_rows, walk_cost, latest_samples


def _depth():
    cols = dict(levels_ask=5, levels_bid=5, ticker_spread_bp=None, ticker_ask1_notional=None, ticker_bid1_notional=None,
                **{f"{s}_walk_bp_{n}": None for s in ("buy", "sell") for n in (1000, 5000, 25000)})
    rows = [
        # after-hours public book: 10 bp to sell $1k/$5k, cannot fill $25k on the bid side
        dict(cols, ts="2026-09-16T20:11:00+00:00", session="after_hours", symbol="RXUSDT", book_source="public_book",
             sell_walk_bp_1000=10.0, sell_walk_bp_5000=10.0, buy_walk_bp_1000=10.0, buy_walk_bp_5000=10.0, buy_walk_bp_25000=30.0),
        # older after-hours sample must be ignored in favour of the newer one above
        dict(cols, ts="2026-09-15T20:11:00+00:00", session="after_hours", symbol="RXUSDT", book_source="public_book",
             sell_walk_bp_1000=99.0, sell_walk_bp_5000=99.0, buy_walk_bp_1000=99.0, buy_walk_bp_5000=99.0),
        # regular session, ticker-only: 4 bp spread, $8k visible on each side
        dict(cols, ts="2026-09-16T19:19:00+00:00", session="regular", symbol="RXUSDT", book_source="ticker_only",
             ticker_spread_bp=4.0, ticker_ask1_notional=8000.0, ticker_bid1_notional=8000.0),
    ]
    return pd.DataFrame(rows)


def _result():
    return {"event_id": "rX-2026-06-22-1", "symbol": "rX", "ex_date": "2026-06-22", "usable": True,
            "gross_dividend": 1.0, "net_dividend": 0.7, "p_pre": 100.0, "p_pre_ts": "2026-06-18T23:59:00+00:00",
            "fee_rate": 0.0005, "fee_label": "DOCUMENTED promotional",
            "p_post": {"overnight_2000": None, "premarket_0400": None, "open_0930": 99.0, "open_1000": 99.5, "close_1600": 98.0},
            "p_post_ts": {"open_0930": "2026-06-22T13:30:00+00:00", "open_1000": "2026-06-22T14:00:00+00:00",
                          "close_1600": "2026-06-22T20:00:00+00:00"}}


LEDGER = {"rX-2026-06-22-1": {"spot_symbol": "RXUSDT", "withholding_rate": "0.30"}}


def test_latest_sample_wins():
    s = latest_samples(_depth())[("RXUSDT", "after_hours")]
    assert s.sell_walk_bp_1000 == 10.0


def test_latest_samples_can_reject_stale_rows():
    s = latest_samples(_depth(), as_of=pd.Timestamp("2026-09-18T00:00:00Z"), max_age_seconds=3600)
    assert s == {}


def test_walk_cost_surfaces():
    s = latest_samples(_depth())
    assert walk_cost(s[("RXUSDT", "after_hours")], "sell", 1000) == (0.001, None)
    assert walk_cost(s[("RXUSDT", "after_hours")], "sell", 25000)[0] is None
    assert walk_cost(s[("RXUSDT", "regular")], "buy", 5000) == (0.0002, None)      # half of 4 bp
    v, why = walk_cost(s[("RXUSDT", "regular")], "buy", 25000)
    assert v is None and "exceeds visible top-of-book" in why
    assert walk_cost(None, "buy", 1000)[0] is None


def test_exit_arithmetic_and_labels():
    rows = cost_rows([_result()], _depth(), LEDGER)
    by = {(r["rung"], r["notional_usd"]): r for r in rows}
    r = by[("open_0930", 1000)]
    # sell 100 in after-hours book (10 bp), buy back 99 via ticker (2 bp), fee 5 bp each leg
    fee = 0.0005 * (100 + 99); walk = 0.001 * 100 + 0.0002 * 99
    assert r["fee_per_share"] == pytest.approx(fee)
    assert r["walk_per_share"] == pytest.approx(walk)
    assert r["exit_net_per_share"] == pytest.approx(1.0 - 0.7 - fee - walk)
    assert r["exit_breakeven_pdr"] == pytest.approx((0.7 + fee + walk) / 1.0)
    assert r["buy_net_per_share"] == pytest.approx(0.7 - 1.0 - fee - walk)
    assert r["buy_suppressed"] and r["withholding_rate"] == 0.30 and r["holding_hours"] == pytest.approx(85.5167, abs=1e-3)
    assert r["pre_book_source"] == "public_book" and r["post_book_source"] == "ticker_only"
    # sell side cannot fill $25k -> nothing priced, reason attached, no default
    r25 = by[("open_0930", 25000)]
    assert r25["exit_net_per_share"] is None and "sell:" in r25["cost_reason"] and "buy:" in r25["cost_reason"]
    # missing rung price -> reason only
    assert by[("overnight_2000", 1000)]["cost_reason"] == "no overnight_2000 price"
    # close_1600 maps to after_hours, so both legs price from the public book at 10 bp
    c = by[("close_1600", 5000)]
    assert c["walk_per_share"] == pytest.approx(0.001 * 100 + 0.001 * 98)
    assert len(rows) == 5 * 3


def test_unusable_events_are_skipped():
    bad = dict(_result(), usable=False)
    assert cost_rows([bad], _depth(), LEDGER) == []

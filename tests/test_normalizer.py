import datetime as dt
from decimal import Decimal

import pandas as pd
import pytest

from exnight.events import CorporateAction, EventType
from exnight.normalizer import UnadjustedSeriesError, UnverifiedRuleError, expected_impact, normalize


def _candles():
    return pd.DataFrame([
        {"ts": pd.Timestamp("2026-09-16T11:59:00Z"), "open": 200.0, "high": 201.0, "low": 199.0, "close": 200.0},
        {"ts": pd.Timestamp("2026-09-16T12:30:00Z"), "open": 200.0, "high": 201.0, "low": 199.0, "close": 200.0},
        {"ts": pd.Timestamp("2026-09-16T13:00:00Z"), "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0},
    ])


def _split(ratio=Decimal("2"), event_type=EventType.SPLIT, with_halt=True, ex_date=dt.date(2026, 9, 16)):
    return CorporateAction(
        event_id="TEST-SPLIT", symbol="rTEST", spot_symbol="RTESTUSDT",
        underlying="TEST", event_type=event_type, announcement_date=None,
        exchange_ex_date=ex_date, exchange_record_date=None, bitget_snapshot_time=None,
        payment_date=None, gross_dividend_per_share=None, withholding_rate=None,
        net_dividend_per_share=None, eligibility_verified=False, weekend_list_2026_07_17=None,
        source_key="test", source_url="https://example.test", label="OBSERVED",
        adjustment_ratio=ratio,
        trading_halt_start=dt.datetime(2026, 9, 16, 12, tzinfo=dt.UTC) if with_halt else None,
        trading_halt_end=dt.datetime(2026, 9, 16, 13, tzinfo=dt.UTC) if with_halt else None,
    )


def test_normalize_applies_ratio_and_removes_halt_bars():
    result = normalize("RTESTUSDT", _candles(), [_split()])
    assert result.dropped_halt_bars == 1
    assert result.applied_splits == ["TEST-SPLIT"]
    assert result.bars["ts"].tolist() == [pd.Timestamp("2026-09-16T11:59:00Z"), pd.Timestamp("2026-09-16T13:00:00Z")]
    assert result.bars.iloc[0]["close"] == 100.0
    assert result.bars.iloc[1]["open"] == 100.0


def test_normalize_fails_when_ratio_does_not_remove_boundary_move():
    with pytest.raises(UnadjustedSeriesError, match="leaves"):
        normalize("RTESTUSDT", _candles(), [_split(Decimal("3"))])


def test_reverse_split_uses_inverse_price_factor():
    candles = _candles().assign(
        open=[10.0, 10.0, 100.0], high=[11.0, 11.0, 101.0],
        low=[9.0, 9.0, 99.0], close=[10.0, 10.0, 100.0])
    result = normalize("RTESTUSDT", candles, [_split(Decimal("0.1"), EventType.REVERSE_SPLIT)])
    assert result.bars.iloc[0]["close"] == 100.0
    assert result.bars.iloc[1]["open"] == 100.0


def test_missing_halt_is_rejected_for_an_in_listing_split():
    with pytest.raises(UnverifiedRuleError, match="halt timestamps"):
        normalize("RTESTUSDT", _candles(), [_split(with_halt=False)])


def test_prior_listing_split_without_halt_is_not_applied():
    event = _split(with_halt=False, ex_date=dt.date(2026, 9, 15))
    candles = _candles().copy()
    candles.loc[1:, ["open", "high", "low", "close"]] = [100.0, 101.0, 99.0, 100.0]
    result = normalize("RTESTUSDT", candles, [event],
                       dt.datetime(2026, 9, 16, 12, tzinfo=dt.UTC))
    assert result.applied_splits == []


def test_expected_impact_uses_real_new_york_timezone():
    event = CorporateAction(
        event_id="TEST-DIV", symbol="rTEST", underlying="TEST", spot_symbol="RTESTUSDT",
        event_type=EventType.CASH_DIV, announcement_date=None,
        exchange_ex_date=dt.date(2026, 1, 6), exchange_record_date=None,
        bitget_snapshot_time=None, payment_date=None,
        gross_dividend_per_share=Decimal("0.15"), withholding_rate=Decimal("0.30"),
        net_dividend_per_share=Decimal("0.105"), cash_dividend_per_share=Decimal("0.15"),
        cash_dividend_basis="GROSS", net_dividend_verified=True, eligibility_verified=False, weekend_list_2026_07_17=None,
        source_key="test", source_url="https://example.test", label="OBSERVED",
    )
    assert expected_impact("RTESTUSDT", dt.datetime(2026, 1, 6, 4, 30, tzinfo=dt.UTC), [event]) == Decimal(0)
    assert expected_impact("RTESTUSDT", dt.datetime(2026, 1, 6, 5, 30, tzinfo=dt.UTC), [event]) == Decimal("0.15")

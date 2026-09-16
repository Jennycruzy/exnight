import datetime as dt
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd
import pytest

from exnight.events import EventType
from exnight.normalizer import UnadjustedSeriesError, expected_impact, normalize


def _candles():
    return pd.DataFrame([
        {"ts": pd.Timestamp("2026-09-16T11:59:00Z"), "open": 200.0, "high": 201.0, "low": 199.0, "close": 200.0},
        {"ts": pd.Timestamp("2026-09-16T12:30:00Z"), "open": 200.0, "high": 201.0, "low": 199.0, "close": 200.0},
        {"ts": pd.Timestamp("2026-09-16T13:00:00Z"), "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0},
    ])


def _split(ratio=Decimal("0.5")):
    return SimpleNamespace(
        event_id="TEST-SPLIT", symbol="rTEST", spot_symbol="RTESTUSDT",
        event_type=EventType.SPLIT, adjustment_ratio=ratio,
        trading_halt_start=dt.datetime(2026, 9, 16, 12, tzinfo=dt.UTC),
        trading_halt_end=dt.datetime(2026, 9, 16, 13, tzinfo=dt.UTC),
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
        normalize("RTESTUSDT", _candles(), [_split(Decimal("2"))])


def test_expected_impact_uses_real_new_york_timezone():
    event = SimpleNamespace(
        event_id="TEST-DIV", symbol="rTEST", spot_symbol="RTESTUSDT",
        event_type=EventType.CASH_DIV, exchange_ex_date=dt.date(2026, 1, 6),
        gross_dividend_per_share=Decimal("0.15"),
    )
    assert expected_impact("RTESTUSDT", dt.datetime(2026, 1, 6, 4, 30, tzinfo=dt.UTC), [event]) == Decimal(0)
    assert expected_impact("RTESTUSDT", dt.datetime(2026, 1, 6, 5, 30, tzinfo=dt.UTC), [event]) == Decimal("0.15")

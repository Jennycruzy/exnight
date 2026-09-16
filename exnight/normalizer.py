"""Corporate-action normalisation at ingestion.

Split records carry an adjustment ratio and an explicit trading halt. A continuous
price drop across that window is not a valid observation: the halt bars are removed,
pre-halt OHLC values are put on the post-halt scale, and the boundary is checked.
The legacy datetime call remains accepted while the event-study caller is migrated.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal
from zoneinfo import ZoneInfo

import pandas as pd

from .errors import DataGapError, ExnightError, UnverifiedRuleError
from .events import CorporateAction, EventType

ET = ZoneInfo("America/New_York")
SPLIT_GAP_RATIO = 0.6
STALE_EXTREME_RATIO = 0.25
SPLIT_RESIDUAL_TOLERANCE = 0.05
PRICE_COLUMNS = ("open", "high", "low", "close")


class UnadjustedSeriesError(ExnightError):
    """A split-shaped discontinuity remains after normalisation."""


@dataclass
class Normalized:
    symbol: str
    bars: pd.DataFrame
    dropped_before_open: int
    stale_extremes: list[pd.Timestamp] = field(default_factory=list)
    dropped_halt_bars: int = 0
    applied_splits: list[str] = field(default_factory=list)


def _event_matches(symbol: str, event: CorporateAction) -> bool:
    needle = symbol.casefold()
    for name in ("symbol", "spot_symbol"):
        value = getattr(event, name, None)
        if value and str(value).casefold() == needle:
            return True
    return False


def _as_aware_timestamp(value: dt.datetime, field_name: str) -> pd.Timestamp:
    if value.tzinfo is None:
        raise UnverifiedRuleError(f"{field_name} must be timezone-aware")
    return pd.Timestamp(value)


def _split_events(symbol: str, events: list[CorporateAction]) -> list[CorporateAction]:
    return [
        e for e in events
        if _event_matches(symbol, e)
        and getattr(e, "event_type", None) in (EventType.SPLIT, EventType.REVERSE_SPLIT, "SPLIT", "REVERSE_SPLIT")
    ]


def normalize(
    symbol: str,
    candles: pd.DataFrame,
    events: list[CorporateAction] | dt.datetime,
    open_time: dt.datetime | None = None,
) -> Normalized:
    """Normalise candles using matching split records and halt windows.

    The third argument is the event list. Passing an aware datetime is the temporary
    compatibility form used by the older event-study caller and applies only the
    listing-time filter. No split adjustment is inferred when event data is absent.
    """
    if isinstance(events, dt.datetime):
        if open_time is not None:
            raise ValueError("open_time supplied twice")
        open_time = events
        event_list: list[CorporateAction] = []
    else:
        event_list = list(events)
    if open_time is not None and open_time.tzinfo is None:
        raise ValueError("open_time must be timezone-aware")
    if candles.empty:
        return Normalized(symbol, candles.copy(), 0)

    df = candles.sort_values("ts").reset_index(drop=True).copy()
    if df["ts"].dt.tz is None:
        raise ValueError("candle timestamps must be timezone-aware")
    before = 0
    if open_time is not None:
        open_ts = pd.Timestamp(open_time)
        before = int((df["ts"] < open_ts).sum())
        df = df[df["ts"] >= open_ts].reset_index(drop=True)
    if df.empty:
        return Normalized(symbol, df, before)

    dropped_halt = 0
    applied_splits: list[str] = []
    split_events = sorted(
        _split_events(symbol, event_list),
        key=lambda e: getattr(e, "trading_halt_start", None) or dt.datetime.min.replace(tzinfo=dt.UTC),
    )
    for event in split_events:
        ratio_value = getattr(event, "adjustment_ratio", None)
        halt_start_value = getattr(event, "trading_halt_start", None)
        halt_end_value = getattr(event, "trading_halt_end", None)
        if ratio_value is None or halt_start_value is None or halt_end_value is None:
            raise UnverifiedRuleError(
                f"{getattr(event, 'event_id', symbol)}: split ratio and both halt timestamps are required"
            )
        ratio = Decimal(str(ratio_value))
        if ratio <= 0:
            raise UnverifiedRuleError(f"{getattr(event, 'event_id', symbol)}: split ratio must be positive")
        halt_start = _as_aware_timestamp(halt_start_value, "trading_halt_start")
        halt_end = _as_aware_timestamp(halt_end_value, "trading_halt_end")
        if halt_start >= halt_end:
            raise UnverifiedRuleError(f"{getattr(event, 'event_id', symbol)}: halt end must be after halt start")

        pre = df[df["ts"] < halt_start]
        post = df[df["ts"] >= halt_end]
        if pre.empty or post.empty:
            raise DataGapError(
                f"{symbol}: split {getattr(event, 'event_id', symbol)} lacks candles on both sides of the halt"
            )
        pre_close = float(pre.iloc[-1]["close"])
        post_open = float(post.iloc[0]["open"])
        if pre_close <= 0 or post_open <= 0:
            raise UnadjustedSeriesError(f"{symbol}: non-positive split boundary price")

        before_halt = df["ts"] < halt_start
        for column in PRICE_COLUMNS:
            if column in df:
                df.loc[before_halt, column] = df.loc[before_halt, column] * float(ratio)
        normalised_pre = pre_close * float(ratio)
        residual = post_open / normalised_pre - 1.0
        if abs(residual) > SPLIT_RESIDUAL_TOLERANCE:
            raise UnadjustedSeriesError(
                f"{symbol}: split {getattr(event, 'event_id', symbol)} leaves "
                f"{residual:.2%} boundary move after ratio {ratio}"
            )

        in_halt = (df["ts"] >= halt_start) & (df["ts"] < halt_end)
        dropped_halt += int(in_halt.sum())
        df = df[~in_halt].reset_index(drop=True)
        applied_splits.append(getattr(event, "event_id", symbol))

    ratio = df["open"] / df["close"].shift(1)
    gaps = df.index[(ratio < SPLIT_GAP_RATIO) | (ratio > 1 / SPLIT_GAP_RATIO)]
    if len(gaps):
        i = int(gaps[0])
        raise UnadjustedSeriesError(
            f"{symbol}: open/prev_close = {ratio[i]:.3f} at {df['ts'][i]}; "
            "split-shaped gap remains after normalisation"
        )

    env_hi = df[["open", "close"]].max(axis=1)
    env_lo = df[["open", "close"]].min(axis=1)
    stale = (df["high"] > env_hi * (1 + STALE_EXTREME_RATIO)) | (df["low"] < env_lo * (1 - STALE_EXTREME_RATIO))
    df["stale_extreme"] = stale.to_numpy()
    return Normalized(symbol, df, before, list(df.loc[stale, "ts"]), dropped_halt, applied_splits)


def expected_impact(symbol: str, ts: dt.datetime, ledger: list[CorporateAction]) -> Decimal:
    """Return the scheduled cash amount for the ET date containing ts.

    The timestamp conversion uses the IANA New York zone so winter dates do not get
    shifted by a fixed daylight-saving offset. Unresolved cash amounts are an error;
    they are never replaced with a literature estimate.
    """
    if ts.tzinfo is None:
        raise ValueError("ts must be timezone-aware")
    et_date = ts.astimezone(ET).date()
    total = Decimal(0)
    for event in ledger:
        if not _event_matches(symbol, event):
            continue
        if getattr(event, "event_type", None) is not EventType.CASH_DIV:
            continue
        if event.exchange_ex_date != et_date:
            continue
        amount = event.gross_dividend_per_share
        if amount is None:
            raise UnverifiedRuleError(f"{event.event_id}: cash amount is unresolved")
        total += amount
    return total

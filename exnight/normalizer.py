"""C4: corporate-action normalisation at ingestion.

What Bitget actually does (OBSERVED 2026-09-16, docs/verification.md): historical candles
are already back-adjusted for splits, and a token is re-listed around the action so that
its `openTime` moves. So this module does NOT re-scale prices. It:

  1. verifies the series contains no split-shaped discontinuity that would indicate a raw,
     un-adjusted feed (which would mean Bitget changed behaviour and every downstream
     number is suspect);
  2. flags bars whose high/low sit far outside the open/close range, the signature of a
     stale un-adjusted print surviving an adjustment (RAPHUSDT 2026-09-02, high 146.784 vs
     close 80.997);
  3. drops bars before the symbol's live `openTime`, because bars before it are a
     backfilled reference series, not rToken trading.

It knows nothing about the strategy. `expected_impact` returns the scheduled mechanical
move for a symbol at a timestamp from the ledger and nothing else.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal

import numpy as np
import pandas as pd

from .errors import ExnightError
from .events import CorporateAction, EventType

SPLIT_GAP_RATIO = 0.6        # open/prev_close outside [0.6, 1/0.6] is treated as a split gap
STALE_EXTREME_RATIO = 0.25   # high or low more than 25% beyond the open/close envelope


class UnadjustedSeriesError(ExnightError):
    """A split-shaped gap was found: the feed is not adjusted the way we verified."""


@dataclass
class Normalized:
    symbol: str
    bars: pd.DataFrame            # bars at/after open_time, with `stale_extreme` flag column
    dropped_before_open: int
    stale_extremes: list[pd.Timestamp] = field(default_factory=list)


def normalize(symbol: str, candles: pd.DataFrame, open_time: dt.datetime) -> Normalized:
    if candles.empty:
        return Normalized(symbol, candles.copy(), 0)
    df = candles.sort_values("ts").reset_index(drop=True)
    before = int((df["ts"] < open_time).sum())
    df = df[df["ts"] >= open_time].reset_index(drop=True)
    if df.empty:
        return Normalized(symbol, df, before)

    ratio = df["open"] / df["close"].shift(1)
    gaps = df.index[(ratio < SPLIT_GAP_RATIO) | (ratio > 1 / SPLIT_GAP_RATIO)]
    if len(gaps):
        i = int(gaps[0])
        raise UnadjustedSeriesError(
            f"{symbol}: open/prev_close = {ratio[i]:.3f} at {df['ts'][i]}; "
            "split-shaped gap in a series Bitget is expected to have adjusted"
        )

    env_hi = df[["open", "close"]].max(axis=1)
    env_lo = df[["open", "close"]].min(axis=1)
    stale = (df["high"] > env_hi * (1 + STALE_EXTREME_RATIO)) | (df["low"] < env_lo * (1 - STALE_EXTREME_RATIO))
    df["stale_extreme"] = stale.to_numpy()
    return Normalized(symbol, df, before, list(df.loc[stale, "ts"]))


def expected_impact(symbol: str, ts: dt.datetime, ledger: list[CorporateAction]) -> Decimal:
    """Scheduled mechanical price impact (gross dividend per share, in USDT) for `symbol`
    whose ex-date is the ET calendar day containing `ts`. Zero if no event. Splits do not
    contribute because Bitget's series is already adjusted for them."""
    et = ts.astimezone(dt.timezone(dt.timedelta(hours=-4))).date()
    total = Decimal(0)
    for e in ledger:
        if e.symbol == symbol and e.event_type is EventType.CASH_DIV and e.exchange_ex_date == et:
            total += e.gross_dividend_per_share
    return total

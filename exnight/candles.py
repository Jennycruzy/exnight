"""Raw candle cache. Bars are stored exactly as returned by Bitget (no adjustment, no
gap filling) under data/raw/candles/<SYMBOL>/<interval>/<start>_<end>.parquet.
Normalisation happens downstream in the normaliser, never here."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pandas as pd

from .market import BitgetPublic

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw" / "candles"


def window_for_event(ex_date: dt.date, days_before: int = 3, days_after: int = 2) -> tuple[dt.datetime, dt.datetime]:
    """UTC window around a US ex-date wide enough to cover the prior close and the next
    US open regardless of DST: from midnight UTC `days_before` days earlier to midnight
    UTC `days_after` days later."""
    start = dt.datetime.combine(ex_date - dt.timedelta(days=days_before), dt.time(), dt.UTC)
    end = dt.datetime.combine(ex_date + dt.timedelta(days=days_after), dt.time(), dt.UTC)
    return start, end


def fetch_cached(api: BitgetPublic, symbol: str, interval: str, start: dt.datetime, end: dt.datetime) -> pd.DataFrame:
    p = RAW_DIR / symbol / interval / f"{start:%Y%m%dT%H%M}_{end:%Y%m%dT%H%M}.parquet"
    if p.exists():
        return pd.read_parquet(p)
    df = api.candles_v3(symbol, interval, start, end)
    p.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(p, index=False)
    return df

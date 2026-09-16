"""Underlying (US-listed) prices for the baseline comparison.

Source: Yahoo Finance chart endpoint, unauthenticated. This is a third-party source and is
labelled as such in results; it is used only for the underlying share, never for anything
about Bitget. Daily bars are cached raw under data/raw/underlying/<TICKER>.json.

Yahoo also reports the dividend event (amount, ex-date) which is used to cross-check the
amount and ex-date Bitget published. Disagreements are recorded on the event, not resolved.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import httpx
import pandas as pd

from .errors import ExnightError

RAW_DIR = Path(__file__).resolve().parent.parent / "data" / "raw" / "underlying"
_UA = {"User-Agent": "Mozilla/5.0"}


class UnderlyingDataError(ExnightError):
    pass


def _fetch(ticker: str, start: dt.date, end: dt.date) -> dict:
    p = RAW_DIR / f"{ticker}_{start:%Y%m%d}_{end:%Y%m%d}.json"
    if p.exists():
        return json.loads(p.read_text())
    p1 = int(dt.datetime.combine(start, dt.time(), dt.UTC).timestamp())
    p2 = int(dt.datetime.combine(end, dt.time(), dt.UTC).timestamp())
    r = httpx.get(
        f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}",
        params=dict(period1=p1, period2=p2, interval="1d", events="div,splits"),
        headers=_UA, timeout=30,
    )
    body = r.json()
    res = (body.get("chart") or {}).get("result")
    if not res:
        raise UnderlyingDataError(f"{ticker}: {body.get('chart', {}).get('error')}")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(res[0]))
    return res[0]


def daily(ticker: str, start: dt.date, end: dt.date) -> pd.DataFrame:
    res = _fetch(ticker, start, end)
    q = res["indicators"]["quote"][0]
    df = pd.DataFrame(
        dict(ts=pd.to_datetime(res["timestamp"], unit="s", utc=True),
             open=q["open"], high=q["high"], low=q["low"], close=q["close"], volume=q["volume"])
    ).dropna(subset=["open", "close"])
    df["date"] = df["ts"].dt.tz_convert("America/New_York").dt.date
    return df.reset_index(drop=True)


def dividends(ticker: str, start: dt.date, end: dt.date) -> list[dict]:
    res = _fetch(ticker, start, end)
    out = []
    for v in (res.get("events") or {}).get("dividends", {}).values():
        d = dt.datetime.fromtimestamp(v["date"], dt.UTC).astimezone(
            dt.timezone(dt.timedelta(hours=-4))).date()
        out.append(dict(ex_date=d, amount=float(v["amount"])))
    return sorted(out, key=lambda x: x["ex_date"])


def splits(ticker: str, start: dt.date, end: dt.date) -> list[dict]:
    res = _fetch(ticker, start, end)
    return [dict(date=dt.datetime.fromtimestamp(v["date"], dt.UTC).date(),
                 numerator=v["numerator"], denominator=v["denominator"])
            for v in (res.get("events") or {}).get("splits", {}).values()]

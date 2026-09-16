"""Sample executable depth for every symbol in the ledger and append to data/results/depth_samples.csv.

Run during US regular hours (09:30-16:00 ET) and again off-hours; the `session` column is
derived from the sample time. Depth = resting notional within ±0.5% and ±2% of mid; walk
cost = average fill price premium over mid for a market order of $1k / $5k / $25k, or NaN
if the book cannot fill it. OBSERVED-at-sample-time only; never a statement about any event.
"""
import datetime as dt
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from exnight.calendar import read_ledger
from exnight.market import BitgetPublic

ET = ZoneInfo("America/New_York")
OUT = Path(__file__).resolve().parent.parent / "data" / "results" / "depth_samples.csv"


def vwap_for(levels, notional):
    remaining = notional; qty_total = 0.0
    for px, qty in levels:
        px, qty = float(px), float(qty)
        take_notional = min(qty * px, remaining)
        qty_total += take_notional / px
        remaining -= take_notional
        if remaining <= 1e-9:
            return notional / qty_total
    return None


def main():
    api = BitgetPublic()
    now = dt.datetime.now(dt.UTC); et = now.astimezone(ET)
    regular = et.weekday() < 5 and dt.time(9, 30) <= et.time() < dt.time(16, 0)
    rows = []
    for sym in sorted({e.spot_symbol for e in read_ledger()}):
        ob = api._get("/api/v3/market/orderbook", dict(category="SPOT", symbol=sym, limit=1000))
        a, b = ob["a"], ob["b"]
        r = dict(ts=now.isoformat(), session="us_regular" if regular else "off_hours", symbol=sym,
                 levels_ask=len(a), levels_bid=len(b))
        if a and b:
            mid = (float(a[0][0]) + float(b[0][0])) / 2
            r["spread_bp"] = 1e4 * (float(a[0][0]) - float(b[0][0])) / mid
            for band in (0.005, 0.02):
                r[f"ask_depth_{band}"] = sum(float(p) * float(q) for p, q in a if float(p) <= mid * (1 + band))
                r[f"bid_depth_{band}"] = sum(float(p) * float(q) for p, q in b if float(p) >= mid * (1 - band))
            for n in (1_000, 5_000, 25_000):
                v = vwap_for(a, n); r[f"buy_walk_bp_{n}"] = None if v is None else 1e4 * (v / mid - 1)
                v = vwap_for(b, n); r[f"sell_walk_bp_{n}"] = None if v is None else 1e4 * (1 - v / mid)
        rows.append(r)
    df = pd.DataFrame(rows)
    df.to_csv(OUT, mode="a", header=not OUT.exists(), index=False)
    q = df.dropna(subset=["spread_bp"]) if "spread_bp" in df else df.iloc[0:0]
    print(f"{et:%Y-%m-%d %H:%M ET} {df.session.iloc[0]}: {len(df)} symbols, {len(df) - len(q)} empty books")
    if len(q):
        print("median spread bp", round(q.spread_bp.median(), 1),
              "| median ±2% two-sided depth $", round((q["ask_depth_0.02"] + q["bid_depth_0.02"]).median()),
              "| can fill $5k buy:", int(q["buy_walk_bp_5000"].notna().sum()), "| $25k:", int(q["buy_walk_bp_25000"].notna().sum()))


if __name__ == "__main__":
    main()

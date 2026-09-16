"""Sample executable depth for every symbol in the ledger and append to data/results/depth_samples.csv.

Run in several windows (regular, pre-market, after-hours, overnight, weekend, holiday). The
`session` column is derived from the live Reality `market/states` and `market/calendar`
responses at sample time, never from a hardcoded clock. Depth = resting notional within
±0.5% and ±2% of mid; walk cost = average fill price premium over mid for a market order of
$1k / $5k / $25k, or NaN if the book cannot fill it. OBSERVED-at-sample-time only; never a
statement about any event.
"""
import datetime as dt
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from exnight.calendar import read_ledger
from exnight.market import BitgetPublic

ET = ZoneInfo("America/New_York")  # Bitget labels the zone "EST"; OBSERVED to mean US Eastern wall clock
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "results" / "depth_samples.csv"
RAW = ROOT / "data" / "raw" / "depth"
BANDS = (0.005, 0.02)
NOTIONALS = (1_000, 5_000, 25_000)


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


def _hm(s: str) -> dt.time:
    h, m = s.split(":"); return dt.time(int(h), int(m))


def session_label(et: dt.datetime, states: dict, calendar: dict) -> str:
    """Label from live config. Holiday and weekend take precedence over intraday states."""
    for cfg in calendar.get("specificConfig", []):
        start = dt.datetime.strptime(cfg["startTime"], "%Y-%m-%d %H:%M").replace(tzinfo=ET)
        end = dt.datetime.strptime(cfg["endTime"], "%Y-%m-%d %H:%M").replace(tzinfo=ET)
        if start <= et < end:
            return "holiday"
    if et.strftime("%A").upper() in set(calendar.get("regularConfig", [])):
        return "weekend"
    t = et.time()
    for st in states["stateList"]:
        a, b = _hm(st["startTime"]), _hm(st["endTime"])
        if (a <= t < b) if a < b else (t >= a or t < b):
            return st["state"]
    raise RuntimeError(f"no live session state covers {et:%H:%M} ET")


def sample_book(api: BitgetPublic, sym: str, ticker: dict | None) -> tuple[dict, dict]:
    """Public book plus the ticker's top-of-book. OBSERVED 2026-09-16: most rTokens return an
    empty public book while the ticker still carries bid1/ask1 with sizes (routed liquidity,
    cf. platformTurnover24h). ``book_source`` records which surface the quote came from."""
    ob = api.orderbook(sym, limit=1000)
    a, b = ob["asks"], ob["bids"]
    r = dict(symbol=sym, book_ts=ob.get("ts"), levels_ask=len(a), levels_bid=len(b),
             book_source="public_book" if (a and b) else ("ticker_only" if ticker and ticker.get("bid1Price") else "none"))
    if ticker:
        tb, ta = ticker.get("bid1Price"), ticker.get("ask1Price")
        r.update(ticker_bid1=tb, ticker_ask1=ta, ticker_bid1_size=ticker.get("bid1Size"),
                 ticker_ask1_size=ticker.get("ask1Size"), ticker_last=ticker.get("lastPrice"),
                 platform_turnover_24h=ticker.get("platformTurnover24h"))
        if tb and ta and float(tb) > 0 and float(ta) > 0:
            tmid = (float(ta) + float(tb)) / 2
            r["ticker_spread_bp"] = 1e4 * (float(ta) - float(tb)) / tmid
            r["ticker_ask1_notional"] = float(ta) * float(ticker.get("ask1Size") or 0)
            r["ticker_bid1_notional"] = float(tb) * float(ticker.get("bid1Size") or 0)
    if a and b:
        best_a, best_b = float(a[0][0]), float(b[0][0])
        mid = (best_a + best_b) / 2
        r.update(best_ask=best_a, best_bid=best_b, spread_bp=1e4 * (best_a - best_b) / mid)
        for band in BANDS:
            r[f"ask_depth_{band}"] = sum(float(p) * float(q) for p, q in a if float(p) <= mid * (1 + band))
            r[f"bid_depth_{band}"] = sum(float(p) * float(q) for p, q in b if float(p) >= mid * (1 - band))
        for n in NOTIONALS:
            v = vwap_for(a, n); r[f"buy_walk_bp_{n}"] = None if v is None else 1e4 * (v / mid - 1)
            v = vwap_for(b, n); r[f"sell_walk_bp_{n}"] = None if v is None else 1e4 * (1 - v / mid)
    return r, ob


def main():
    api = BitgetPublic()
    now = dt.datetime.now(dt.UTC); et = now.astimezone(ET)
    states, calendar = api.market_states(), api.market_calendar()
    session = session_label(et, states, calendar)
    run_dir = RAW / now.strftime("%Y%m%dT%H%M%SZ"); run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "market_states.json").write_text(json.dumps(states))
    (run_dir / "market_calendar.json").write_text(json.dumps(calendar))
    tickers = {t["symbol"]: t for t in api.tickers()}
    (run_dir / "tickers.json").write_text(json.dumps(tickers))
    rows = []
    for sym in sorted({e.spot_symbol for e in read_ledger() if e.spot_symbol}):
        r, ob = sample_book(api, sym, tickers.get(sym))
        (run_dir / f"{sym}.json").write_text(json.dumps(ob))
        rows.append(dict(ts=now.isoformat(), et=et.strftime("%Y-%m-%d %H:%M"), session=session, **r))
    df = pd.DataFrame(rows)
    df.to_csv(OUT, mode="a", header=not OUT.exists(), index=False)
    q = df.dropna(subset=["spread_bp"]) if "spread_bp" in df else df.iloc[0:0]
    print(f"{et:%Y-%m-%d %H:%M ET} session={session}: {len(df)} symbols; book_source: {df.book_source.value_counts().to_dict()}; raw -> {run_dir}")
    if "ticker_spread_bp" in df:
        print("ticker spread bp median", round(df.ticker_spread_bp.median(), 1),
              "| median ask1 notional $", round(df.ticker_ask1_notional.median()))
    if len(q):
        print("median spread bp", round(q.spread_bp.median(), 1),
              "| median ±2% two-sided depth $", round((q["ask_depth_0.02"] + q["bid_depth_0.02"]).median()),
              "| can fill $5k buy:", int(q["buy_walk_bp_5000"].notna().sum()), "| $25k:", int(q["buy_walk_bp_25000"].notna().sum()),
              f"| median $5k buy walk bp {q['buy_walk_bp_5000'].median():.1f}")


if __name__ == "__main__":
    main()

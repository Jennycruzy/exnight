"""Sample executable depth for every symbol in the ledger and append to data/results/depth_samples.csv.

Run in several windows (regular, pre-market, after-hours, overnight, weekend, holiday). The
`session` column is derived from the live Reality `market/states` and `market/calendar`
responses at sample time, never from a hardcoded clock. Depth = resting notional within
±0.5% and ±2% of mid; walk cost = average fill price premium over mid for a market order of
$1k / $5k / $25k, or NaN if the book cannot fill it. OBSERVED-at-sample-time only; never a
statement about any event.
"""
import datetime as dt
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from exnight.calendar import read_ledger
from exnight.market import BitgetPublic

ET = ZoneInfo("America/New_York")  # Bitget labels the zone "EST"; OBSERVED to mean US Eastern wall clock
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "results" / "depth_samples.csv"
RAW = ROOT / "data" / "raw" / "depth"
SCHEDULE = ROOT / "data" / "forward" / "v3_schedule.json"
BANDS = (0.005, 0.02)
NOTIONALS = (1_000, 5_000, 25_000)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_manifest(run_dir: Path, *, sampled_at: dt.datetime, session: str, symbols: list[str]) -> Path:
    """Link every raw response to its run metadata with a small replay manifest."""
    files = []
    for path in sorted(run_dir.iterdir()):
        if path.name == "manifest.json" or not path.is_file():
            continue
        files.append(dict(path=path.name, bytes=path.stat().st_size, sha256=file_sha256(path)))
    manifest = dict(run_id=run_dir.name, sampled_at=sampled_at.isoformat(), session=session,
                    symbols=symbols, files=files)
    path = run_dir / "manifest.json"
    path.write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    return path


def vwap_for(levels, notional):
    remaining = notional; qty_total = 0.0
    for px, qty in levels:
        try:
            px, qty = float(px), float(qty)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(px) or not math.isfinite(qty) or px <= 0 or qty <= 0:
            continue
        take_notional = min(qty * px, remaining)
        qty_total += take_notional / px
        remaining -= take_notional
        if remaining <= 1e-9:
            return notional / qty_total
    return None


def _valid_levels(levels) -> list[tuple[float, float]]:
    out = []
    for level in levels or []:
        if not isinstance(level, (list, tuple)) or len(level) < 2:
            continue
        try:
            price, quantity = float(level[0]), float(level[1])
        except (TypeError, ValueError):
            continue
        if math.isfinite(price) and math.isfinite(quantity) and price > 0 and quantity > 0:
            out.append((price, quantity))
    return out


def _positive(value) -> bool:
    try:
        return math.isfinite(float(value)) and float(value) > 0
    except (TypeError, ValueError):
        return False


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
    a, b = _valid_levels(ob["asks"]), _valid_levels(ob["bids"])
    tb, ta = (ticker or {}).get("bid1Price"), (ticker or {}).get("ask1Price")
    ticker_valid = (_positive(tb) and _positive(ta) and float(ta) >= float(tb)
                    and _positive((ticker or {}).get("bid1Size"))
                    and _positive((ticker or {}).get("ask1Size")))
    r = dict(symbol=sym, book_ts=ob.get("ts"), levels_ask=len(a), levels_bid=len(b),
             book_source="public_book" if (a and b) else ("ticker_only" if ticker_valid else "none"))
    if ticker:
        r.update(ticker_bid1=tb, ticker_ask1=ta, ticker_bid1_size=ticker.get("bid1Size"),
                 ticker_ask1_size=ticker.get("ask1Size"), ticker_last=ticker.get("lastPrice"),
                 platform_turnover_24h=ticker.get("platformTurnover24h"))
        if _positive(tb) and _positive(ta):
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


def sampled_symbols(schedule: Path = SCHEDULE) -> list[str]:
    """Study-ledger symbols plus every symbol in the forward schedule, if one exists."""
    symbols = {e.spot_symbol for e in read_ledger() if e.spot_symbol}
    if schedule.exists():
        symbols |= {s for g in json.loads(schedule.read_text())["groups"] for s in g["symbols"]}
    return sorted(symbols)


def main():
    api = BitgetPublic()
    now = dt.datetime.now(dt.UTC); et = now.astimezone(ET)
    states, calendar = api.market_states(), api.market_calendar()
    session = session_label(et, states, calendar)
    run_dir = RAW / now.strftime("%Y%m%dT%H%M%S.%fZ"); run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "market_states.json").write_text(json.dumps(states))
    (run_dir / "market_calendar.json").write_text(json.dumps(calendar))
    tickers = {t["symbol"]: t for t in api.tickers()}
    (run_dir / "tickers.json").write_text(json.dumps(tickers))
    rows = []
    for sym in sampled_symbols():
        r, ob = sample_book(api, sym, tickers.get(sym))
        (run_dir / f"{sym}.json").write_text(json.dumps(ob))
        rows.append(dict(ts=now.isoformat(), et=et.strftime("%Y-%m-%d %H:%M"), session=session, **r))
    write_manifest(run_dir, sampled_at=now, session=session, symbols=[r["symbol"] for r in rows])
    df = pd.DataFrame(rows)
    if not df.empty:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        lock_path = OUT.with_name(OUT.name + ".lock")
        with lock_path.open("a+") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            prior = pd.read_csv(OUT) if OUT.exists() else pd.DataFrame()
            combined = pd.concat([prior, df], ignore_index=True)
            combined = combined.drop_duplicates(subset=["ts", "symbol", "session"], keep="last")
            tmp = OUT.with_name(f".{OUT.name}.{os.getpid()}.tmp")
            combined.to_csv(tmp, index=False)
            tmp.replace(OUT)
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    q = df.dropna(subset=["spread_bp"]) if "spread_bp" in df else df.iloc[0:0]
    sources = df["book_source"].value_counts().to_dict() if "book_source" in df else {}
    print(f"{et:%Y-%m-%d %H:%M ET} session={session}: {len(df)} symbols; book_source: {sources}; raw -> {run_dir}")
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

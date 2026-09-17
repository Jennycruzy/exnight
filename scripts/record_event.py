"""Append-only forward recorder for the symbols of an upcoming event.

Each invocation takes one sample: the market state, the ticker (bid1/ask1 with sizes,
last price, platform turnover) and the public order book of every symbol, and appends one
JSON line per symbol to data/raw/recorder/<label>/<UTC date>.jsonl. Nothing is derived
here and nothing is rewritten; a scheduler (cron, every minute) supplies the cadence, so
a crash or reboot loses at most one sample. Outside [--start, --end) the script exits
without touching the disk, which lets the cron line stay in place across events.

Example crontab line (UTC):

    * * * * * cd /home/ubuntu/exnight && .venv/bin/python scripts/record_event.py \
        --label 20260921_rAVGO_rVST --symbols RAVGOUSDT RVSTUSDT RSATAUSDT \
        --start 2026-09-17T10:00:00Z --end 2026-09-21T14:30:00Z >> data/raw/recorder/cron.log 2>&1
"""
from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import json
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from exnight.market import BitgetAPIError, BitgetPublic  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "recorder"
ET = ZoneInfo("America/New_York")


def _utc(s: str) -> dt.datetime:
    t = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    if t.tzinfo is None:
        raise ValueError("timestamps must carry a timezone")
    return t.astimezone(dt.UTC)


def sample(api: BitgetPublic, symbols: list[str], now: dt.datetime) -> list[dict]:
    try:
        states = api.market_states()
    except BitgetAPIError as exc:
        states = {"error": str(exc)}
    tickers = {t["symbol"]: t for t in api.tickers()}
    rows = []
    for sym in symbols:
        row = dict(ts=now.isoformat(), et=now.astimezone(ET).isoformat(), symbol=sym,
                   market_state=states, ticker=tickers.get(sym))
        try:
            row["orderbook"] = api.orderbook(sym, limit=1000)
        except BitgetAPIError as exc:
            row["orderbook"] = None
            row["orderbook_error"] = str(exc)
        rows.append(row)
    return rows


def append(label: str, rows: list[dict], now: dt.datetime) -> Path:
    d = RAW / label
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{now:%Y%m%d}.jsonl"
    with p.open("a", encoding="utf-8") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        for r in rows:
            f.write(json.dumps(r, separators=(",", ":")) + "\n")
        f.flush()
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    return p


def main() -> int:
    ap = argparse.ArgumentParser(description="Record ticker and book for event symbols (one sample per call)")
    ap.add_argument("--label", required=True, help="directory name under data/raw/recorder/")
    ap.add_argument("--symbols", nargs="+", required=True, help="spot symbols, e.g. RAVGOUSDT")
    ap.add_argument("--start", type=_utc, required=True)
    ap.add_argument("--end", type=_utc, required=True)
    args = ap.parse_args()
    now = dt.datetime.now(dt.UTC).replace(microsecond=0)
    if not args.start <= now < args.end:
        return 0
    rows = sample(BitgetPublic(), args.symbols, now)
    p = append(args.label, rows, now)
    brief = ", ".join(f"{r['symbol']} {((r.get('ticker') or {}).get('bid1Price'))}/{((r.get('ticker') or {}).get('ask1Price'))}"
                      f" book={len((r.get('orderbook') or {}).get('bids') or [])}b/{len((r.get('orderbook') or {}).get('asks') or [])}a"
                      for r in rows)
    print(f"{now.isoformat()} {p.name}: {brief}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

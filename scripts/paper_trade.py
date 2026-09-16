"""C5: place one paper (demo) order through Bitget Agent Hub and save the evidence chain.

Every run writes data/raw/paper/<UTC ts>/ containing, in order:
  00_context.json        symbol, side, size, session label, verdict row it acts on (if any)
  01_book_pre.json       public order book + ticker immediately before the order (adapter)
  02_dry_run.json        bgc --dry-run payload (`wouldSend`) — what will be submitted
  03_order.json          bgc response to the real --paper-trading placement (absent in dry-run)
  04_order_status.json   bgc order query after placement (absent in dry-run)
  05_book_post.json      public order book + ticker immediately after

Credentials are read from the environment / .env (BITGET_API_KEY, BITGET_SECRET_KEY,
BITGET_PASSPHRASE — *demo* keys, per Bitget's demo-trading docs). The script never prints
them. Without --live-paper it stops after the dry run, which needs no credentials.
Quantity is derived from the visible book: never more than the resting size inside the
±0.5% band at sample time, so the order is one the book could actually fill.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent))
from depth_snapshot import session_label  # noqa: E402

from exnight.market import BitgetPublic  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw" / "paper"
ET = dt.timezone(dt.timedelta(hours=-4), "ET")  # display only; session_label uses America/New_York


def bgc(args: list[str], env: dict) -> dict:
    exe = shutil.which("bgc")
    if exe is None:
        raise SystemExit("bgc not on PATH (source ~/.nvm/nvm.sh)")
    p = subprocess.run([exe, *args], capture_output=True, text=True, env=env, timeout=60)
    if p.returncode != 0:
        raise BgcError(p.stderr.strip() or p.stdout.strip())
    return json.loads(p.stdout)


class BgcError(RuntimeError):
    pass


def book_with_ticker(api: BitgetPublic, symbol: str) -> dict:
    ob = api.orderbook(symbol, limit=1000)
    tk = [t for t in api.tickers(symbol)]
    return dict(fetched_at=dt.datetime.now(dt.UTC).isoformat(), orderbook=ob, ticker=tk[0] if tk else None)


def sized_qty(book: dict, side: str, notional: float, band: float, qty_precision: int) -> tuple[str, str, float]:
    """Limit price at the touch on our side; qty = min(notional/price, resting size within band on the other side)."""
    asks, bids = book["orderbook"]["asks"], book["orderbook"]["bids"]
    if not asks or not bids:
        raise SystemExit("empty public book; refuse to size an order from nothing")
    best_a, best_b = float(asks[0][0]), float(bids[0][0])
    mid = (best_a + best_b) / 2
    if side == "buy":
        price = best_b                       # join the bid (maker); fills only if the market comes to us
        resting = sum(float(q) for p, q in asks if float(p) <= mid * (1 + band))
    else:
        price = best_a
        resting = sum(float(q) for p, q in bids if float(p) >= mid * (1 - band))
    qty = min(notional / price, resting)
    qty = round(qty, qty_precision)
    if qty <= 0:
        raise SystemExit(f"book cannot support any {side} inside ±{band:.1%}")
    return f"{price:.2f}", f"{qty:.{qty_precision}f}", resting


def main() -> None:
    ap = argparse.ArgumentParser(description="One paper order with an evidence chain")
    ap.add_argument("--symbol", required=True, help="API spot symbol, e.g. RAVGOUSDT")
    ap.add_argument("--side", choices=("buy", "sell"), required=True)
    ap.add_argument("--notional", type=float, default=1000.0)
    ap.add_argument("--band", type=float, default=0.005)
    ap.add_argument("--time-in-force", default="post_only", choices=("gtc", "post_only", "ioc", "fok"))
    ap.add_argument("--live-paper", action="store_true", help="actually submit with --paper-trading (demo keys required)")
    ap.add_argument("--note", default="")
    args = ap.parse_args()

    load_dotenv(ROOT / ".env")
    env = dict(os.environ)
    if args.live_paper:
        missing = [k for k in ("BITGET_API_KEY", "BITGET_SECRET_KEY", "BITGET_PASSPHRASE") if not env.get(k)]
        if missing:
            raise SystemExit(f"demo credentials missing: {missing} (put them in .env)")

    api = BitgetPublic()
    live = api.rtoken_symbol(args.symbol)
    run = RAW / dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    run.mkdir(parents=True, exist_ok=True)
    now_et = dt.datetime.now(dt.UTC).astimezone(dt.timezone.utc)
    session = session_label(dt.datetime.now(dt.UTC).astimezone(__import__("zoneinfo").ZoneInfo("America/New_York")),
                            api.market_states(), api.market_calendar())

    pre = book_with_ticker(api, args.symbol)
    price, qty, resting = sized_qty(pre, args.side, args.notional, args.band, live.quantity_precision)
    ctx = dict(symbol=args.symbol, base_coin=live.base_coin, side=args.side, notional_requested=args.notional,
               band=args.band, session=session, price=price, qty=qty, resting_in_band=resting,
               time_in_force=args.time_in_force, mode="paper-trading" if args.live_paper else "dry-run",
               taker_fee=str(live.taker_fee), maker_fee=str(live.maker_fee), note=args.note)
    (run / "00_context.json").write_text(json.dumps(ctx, indent=1))
    (run / "01_book_pre.json").write_text(json.dumps(pre))

    order_args = ["order", "--action", "place", "--category", "SPOT", "--symbol", args.symbol, "--side", args.side,
                  "--orderType", "limit", "--qty", qty, "--price", price, "--timeInForce", args.time_in_force]
    dry = bgc([*order_args, "--paper-trading", "--dry-run"], env)
    (run / "02_dry_run.json").write_text(json.dumps(dry, indent=1))
    print(f"{session}: {args.side} {qty} {args.symbol} @ {price} ({args.time_in_force}); resting in band {resting:.4f}; wouldSend={dry['data'].get('wouldSend')}")

    if args.live_paper:
        try:
            placed = bgc([*order_args, "--paper-trading"], env)
        except BgcError as exc:   # a rejection is evidence too; keep it (no credentials appear in bgc errors)
            (run / "03_order_error.json").write_text(str(exc))
            print("REJECTED:", str(exc).splitlines()[0] if "\n" not in str(exc) else json.loads(str(exc))["error"]["message"])
            placed = None
        (run / "03_order.json").write_text(json.dumps(placed, indent=1)) if placed else None
        oid = (placed.get("data") or {}).get("orderId") if placed else None
        if placed:
            print("placed:", json.dumps(placed.get("data")))
        if oid:
            status = bgc(["order", "--action", "detail", "--category", "SPOT", "--symbol", args.symbol, "--orderId", str(oid), "--paper-trading"], env)
            (run / "04_order_status.json").write_text(json.dumps(status, indent=1))
            print("status:", json.dumps(status.get("data"))[:400])

    post = book_with_ticker(api, args.symbol)
    (run / "05_book_post.json").write_text(json.dumps(post))
    print("evidence ->", run)


if __name__ == "__main__":
    main()

"""C5: preview or place one tightly bounded Bitget spot order and save the evidence chain.

Every run writes data/raw/paper/<UTC ts>/ containing, in order:
  00_context.json        symbol, side, size, session label, verdict row it acts on (if any)
  01_book_pre.json       public order book + ticker immediately before the order (adapter)
  02_dry_run.json        bgc --dry-run payload (`wouldSend`) — what will be submitted
  03_order.json          bgc response to the real --paper-trading placement (absent in dry-run)
  04_order_status.json   bgc order query after placement (absent in dry-run)
  05_book_post.json      public order book + ticker immediately after

Credentials are read from the environment / .env (BITGET_API_KEY, BITGET_SECRET_KEY,
BITGET_PASSPHRASE). The script never prints them. Without --live-paper or --live it stops
after the dry run, which needs no credentials. Real orders require --live plus an exact
confirmation string containing the computed quantity.
Quantity is derived from the visible book: never more than the resting size inside the
±0.5% band at sample time, so the order is one the book could actually fill.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import shutil
import subprocess
import sys
import time
from decimal import Decimal, ROUND_DOWN, ROUND_UP
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
    try:
        p = subprocess.run([exe, *args], capture_output=True, text=True, env=env, timeout=60)
    except subprocess.TimeoutExpired as exc:
        raise BgcError("bgc timed out") from exc
    if p.returncode != 0:
        raise BgcError(p.stderr.strip() or p.stdout.strip())
    try:
        return json.loads(p.stdout)
    except json.JSONDecodeError as exc:
        raise BgcError(f"bgc returned non-JSON output: {p.stdout[:200]!r}") from exc


class BgcError(RuntimeError):
    pass


def book_with_ticker(api: BitgetPublic, symbol: str) -> dict:
    ob = api.orderbook(symbol, limit=1000)
    tk = [t for t in api.tickers(symbol)]
    return dict(fetched_at=dt.datetime.now(dt.UTC).isoformat(), orderbook=ob, ticker=tk[0] if tk else None)


def _levels(raw) -> list[tuple[float, float]]:
    out = []
    for level in raw or []:
        if not isinstance(level, (list, tuple)) or len(level) < 2:
            continue
        try:
            price, qty = float(level[0]), float(level[1])
        except (TypeError, ValueError):
            continue
        if math.isfinite(price) and math.isfinite(qty) and price > 0 and qty > 0:
            out.append((price, qty))
    return out


def _quantize(value: float, precision: int, rounding) -> Decimal:
    step = Decimal(1).scaleb(-precision)
    return Decimal(str(value)).quantize(step, rounding=rounding)


def sized_qty(book: dict, side: str, notional: float, band: float, qty_precision: int,
              price_precision: int, min_trade_usdt: Decimal, time_in_force: str) -> tuple[str, str, float, str]:
    """Size a limit order from executable opposite-side liquidity.

    IOC/FOK orders use the opposite touch; GTC/post-only orders join our own touch.
    A ticker-only quote is accepted only when both prices and both displayed sizes are
    positive. Quantity is always rounded down to exchange precision.
    """
    if side not in {"buy", "sell"}:
        raise ValueError("side must be buy or sell")
    if not math.isfinite(notional) or notional <= 0 or not math.isfinite(band) or band < 0:
        raise ValueError("notional must be positive and band must be non-negative")
    raw_ob = book.get("orderbook") or {}
    asks, bids = _levels(raw_ob.get("asks")), _levels(raw_ob.get("bids"))
    source = "public_book" if asks and bids else "ticker_only"
    if not asks or not bids:
        ticker = book.get("ticker") or {}
        try:
            tb, ta = float(ticker["bid1Price"]), float(ticker["ask1Price"])
            bq, aq = float(ticker["bid1Size"]), float(ticker["ask1Size"])
        except (KeyError, TypeError, ValueError):
            raise SystemExit("no complete public book or ticker quote; refuse to size an order")
        if not all(math.isfinite(v) and v > 0 for v in (tb, ta, bq, aq)) or ta < tb:
            raise SystemExit("ticker quote is invalid or crossed; refuse to size an order")
        asks, bids = [(ta, aq)], [(tb, bq)]
    asks.sort(key=lambda x: x[0])
    bids.sort(key=lambda x: x[0], reverse=True)
    best_a, best_b = asks[0][0], bids[0][0]
    if best_a < best_b:
        raise SystemExit("order book is crossed; refuse to size an order")
    mid = (best_a + best_b) / 2
    maker = time_in_force in {"gtc", "post_only"}
    if side == "buy":
        price = best_b if maker else best_a
        liquidity = [(p, q) for p, q in asks if p <= mid * (1 + band)]
        rounding = ROUND_DOWN if maker else ROUND_UP
    else:
        price = best_a if maker else best_b
        liquidity = [(p, q) for p, q in bids if p >= mid * (1 - band)]
        rounding = ROUND_UP if maker else ROUND_DOWN
    if not liquidity:
        raise SystemExit(f"book cannot support any {side} inside ±{band:.1%}")
    price_d = _quantize(price, price_precision, rounding)
    if price_d <= 0:
        raise SystemExit("quantized order price is not positive")
    visible_qty = sum(q for _, q in liquidity)
    qty_d = _quantize(min(notional / float(price_d), visible_qty), qty_precision, ROUND_DOWN)
    if qty_d <= 0:
        raise SystemExit("quantity rounds to zero at exchange precision")
    actual_notional = price_d * qty_d
    if actual_notional < Decimal(str(min_trade_usdt)):
        raise SystemExit(f"order notional {actual_notional} is below exchange minimum {min_trade_usdt}")
    return f"{price_d:.{price_precision}f}", f"{qty_d:.{qty_precision}f}", visible_qty, source


def _safe_env() -> dict[str, str]:
    """Pass only the runtime and Bitget credentials to the order CLI."""
    allowed = {"PATH", "HOME", "USER", "SHELL", "LANG", "LC_ALL", "NVM_DIR", "NPM_CONFIG_PREFIX", "NODE_PATH"}
    return {k: v for k, v in os.environ.items() if k in allowed or k.startswith("BITGET_")}


def _status_name(payload: dict) -> str:
    data = payload.get("data") or {}
    return str(data.get("status") or data.get("orderStatus") or data.get("state") or "").lower()


def _error_text(exc: Exception) -> str:
    raw = str(exc)
    try:
        payload = json.loads(raw)
        return str(((payload.get("error") or {}).get("message") or payload.get("message") or raw))
    except (TypeError, ValueError, AttributeError):
        return raw.splitlines()[0] if raw else exc.__class__.__name__


def main() -> None:
    ap = argparse.ArgumentParser(description="One paper order with an evidence chain")
    ap.add_argument("--symbol", required=True, help="API spot symbol, e.g. RAVGOUSDT")
    ap.add_argument("--side", choices=("buy", "sell"), required=True)
    ap.add_argument("--notional", type=float, default=1000.0)
    ap.add_argument("--band", type=float, default=0.005)
    ap.add_argument("--time-in-force", default="ioc", choices=("gtc", "post_only", "ioc", "fok"))
    ap.add_argument("--live-paper", action="store_true", help="actually submit with --paper-trading (demo keys required)")
    ap.add_argument("--live", action="store_true", help="submit one real order; requires --confirm-live")
    ap.add_argument("--confirm-live", default="", help="must equal '<symbol> <side> <computed-quantity>' for --live")
    ap.add_argument("--note", default="")
    args = ap.parse_args()

    load_dotenv(ROOT / ".env")
    if args.live_paper and args.live:
        raise SystemExit("choose either --live-paper or --live, not both")
    env = _safe_env()
    if args.live_paper or args.live:
        missing = [k for k in ("BITGET_API_KEY", "BITGET_SECRET_KEY", "BITGET_PASSPHRASE") if not env.get(k)]
        if missing:
            raise SystemExit(f"Bitget credentials missing: {missing} (put them in .env)")

    api = BitgetPublic()
    live = api.rtoken_symbol(args.symbol)
    if live.status.lower() != "online":
        raise SystemExit(f"{live.symbol} is not online (status={live.status!r})")
    run = RAW / dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    run.mkdir(parents=True, exist_ok=False)
    session = session_label(dt.datetime.now(dt.UTC).astimezone(__import__("zoneinfo").ZoneInfo("America/New_York")),
                            api.market_states(), api.market_calendar())

    pre = book_with_ticker(api, args.symbol)
    price, qty, resting, liquidity_source = sized_qty(
        pre, args.side, args.notional, args.band, live.quantity_precision,
        live.price_precision, live.min_trade_usdt, args.time_in_force,
    )
    if args.live and args.confirm_live != f"{args.symbol} {args.side} {qty}":
        raise SystemExit(f"refusing real order; repeat with --confirm-live '{args.symbol} {args.side} {qty}'")
    ctx = dict(symbol=args.symbol, base_coin=live.base_coin, side=args.side, notional_requested=args.notional,
               actual_notional=float(Decimal(price) * Decimal(qty)), band=args.band, session=session,
               price=price, qty=qty, resting_in_band=resting, liquidity_source=liquidity_source,
               time_in_force=args.time_in_force,
               mode="paper-trading" if args.live_paper else ("live" if args.live else "dry-run"),
               taker_fee=str(live.taker_fee), maker_fee=str(live.maker_fee), note=args.note)
    (run / "00_context.json").write_text(json.dumps(ctx, indent=1))
    (run / "01_book_pre.json").write_text(json.dumps(pre))

    order_args = ["order", "--action", "place", "--category", "SPOT", "--symbol", args.symbol, "--side", args.side,
                  "--orderType", "limit", "--qty", qty, "--price", price, "--timeInForce", args.time_in_force]
    mode_flags = ["--paper-trading"] if args.live_paper else []
    dry = bgc([*order_args, *mode_flags, "--dry-run"], env)
    (run / "02_dry_run.json").write_text(json.dumps(dry, indent=1))
    print(f"{session}: {args.side} {qty} {args.symbol} @ {price} ({args.time_in_force}); "
          f"visible {liquidity_source} qty {resting:.4f}; wouldSend={dry.get('data', {}).get('wouldSend')}")

    if args.live_paper or args.live:
        mode_label = "demo" if args.live_paper else "LIVE"
        try:
            placed = bgc([*order_args, *mode_flags], env)
        except BgcError as exc:   # a rejection is evidence too; keep it (no credentials appear in bgc errors)
            (run / "03_order_error.json").write_text(str(exc))
            print(f"{mode_label} REJECTED:", _error_text(exc))
            placed = None
        (run / "03_order.json").write_text(json.dumps(placed, indent=1)) if placed else None
        oid = (placed.get("data") or {}).get("orderId") if placed else None
        if placed:
            print("placed:", json.dumps(placed.get("data")))
        if oid:
            status_args = ["order", "--action", "detail", "--orderId", str(oid), *mode_flags]
            status = None
            terminal = {"filled", "canceled", "cancelled", "rejected", "expired", "failed"}
            for _ in range(8):
                try:
                    status = bgc(status_args, env)
                except BgcError as exc:
                    (run / "04_order_status_error.json").write_text(str(exc))
                    break
                if _status_name(status) in terminal:
                    break
                time.sleep(1)
            (run / "04_order_status.json").write_text(json.dumps(status, indent=1))
            if status:
                print("status:", json.dumps(status.get("data"))[:400])
            if status is None or _status_name(status) not in terminal:
                cancel_args = ["order", "--action", "cancel", "--category", "SPOT", "--orderId", str(oid), *mode_flags]
                try:
                    canceled = bgc(cancel_args, env)
                    (run / "04_order_cancel.json").write_text(json.dumps(canceled, indent=1))
                    print("unfilled order canceled:", json.dumps(canceled.get("data"))[:400])
                except BgcError as exc:
                    (run / "04_order_cancel_error.json").write_text(str(exc))
                    print("CANCEL ERROR:", _error_text(exc))

    post = book_with_ticker(api, args.symbol)
    (run / "05_book_post.json").write_text(json.dumps(post))
    print("evidence ->", run)


if __name__ == "__main__":
    main()

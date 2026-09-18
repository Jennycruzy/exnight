"""Score a completed forward recorder window against a frozen strategy rule.

This script is deliberately offline: it reads the append-only recorder, the immutable
ledger row and the frozen pre-event signals. It never fetches a replacement price and never
places an order. Missing or late samples stay incomplete; ticker-only quotes are labelled
and never presented as public-depth execution evidence.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import sys
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from exnight.calendar import read_ledger  # noqa: E402
from exnight.strategy import load_rule  # noqa: E402
from validate_recording import read_rows, validate  # noqa: E402

ET = ZoneInfo("America/New_York")
RUNG_TIME = {
    "overnight_2000": dt.time(20, 0),
    "premarket_0400": dt.time(4, 0),
    "open_0930": dt.time(9, 30),
    "open_1000": dt.time(10, 0),
    "close_1600": dt.time(16, 0),
}


def _number(value) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) and result > 0 else None


def _price(row: dict) -> tuple[float | None, str | None]:
    ticker = row.get("ticker") or {}
    last = _number(ticker.get("lastPrice"))
    if last is not None:
        return last, "ticker_last"
    bid, ask = _number(ticker.get("bid1Price")), _number(ticker.get("ask1Price"))
    if bid is not None and ask is not None and ask >= bid:
        return (bid + ask) / 2, "ticker_mid"
    return None, None


def _levels(row: dict, side: str) -> tuple[list[tuple[float, float]], str]:
    book = row.get("orderbook") or {}
    raw = book.get("asks" if side == "buy" else "bids") or []
    levels = []
    for level in raw:
        if not isinstance(level, (list, tuple)) or len(level) < 2:
            continue
        price, quantity = _number(level[0]), _number(level[1])
        if price is not None and quantity is not None:
            levels.append((price, quantity))
    if levels:
        return (sorted(levels) if side == "buy" else sorted(levels, reverse=True)), "public_book"
    ticker = row.get("ticker") or {}
    price_key = "ask1Price" if side == "buy" else "bid1Price"
    size_key = "ask1Size" if side == "buy" else "bid1Size"
    price, quantity = _number(ticker.get(price_key)), _number(ticker.get(size_key))
    if price is not None and quantity is not None:
        return [(price, quantity)], "ticker_only"
    return [], "none"


def walk(row: dict | None, side: str, notional: int) -> tuple[float | None, str | None, str]:
    if row is None:
        return None, "missing sample", "none"
    levels, source = _levels(row, side)
    if not levels:
        return None, "no executable quote", source
    remaining, quantity_total = float(notional), 0.0
    for price, quantity in levels:
        take = min(remaining, price * quantity)
        quantity_total += take / price
        remaining -= take
        if remaining <= 1e-9:
            mid = _price(row)[0]
            if mid is None or mid <= 0:
                return None, "no valid mid price", source
            return (notional / quantity_total / mid - 1) if side == "buy" else (1 - notional / quantity_total / mid), None, source
    return None, f"${notional:,} exceeds visible {side} liquidity", source


def _at(rows: list[tuple[dt.datetime, dict]], cutoff: dt.datetime, *, before: bool,
        max_lateness_seconds: int) -> tuple[dict | None, float | None, str | None]:
    chosen = [item for item in rows if item[0] < cutoff] if before else [item for item in rows if item[0] >= cutoff]
    if not chosen:
        return None, None, "no sample at requested cutoff"
    ts, row = chosen[-1] if before else chosen[0]
    distance = (cutoff - ts).total_seconds() if before else (ts - cutoff).total_seconds()
    if distance > max_lateness_seconds:
        return row, distance, f"sample is {distance:.0f}s from cutoff (limit {max_lateness_seconds}s)"
    return row, distance, None


def _frozen_rows(path: Path) -> dict[tuple[str, str, int], dict]:
    if not path.exists():
        return {}
    with path.open(newline="") as f:
        rows = list(csv.DictReader(f))
    out = {}
    for row in rows:
        try:
            key = (row["symbol"], row["ex_date"], int(row["notional_usd"]))
        except (KeyError, TypeError, ValueError):
            continue
        out[key] = row
    return out


def score_event(event, rows: list[tuple[dt.datetime, dict]], rule: dict, frozen: dict,
                *, max_lateness_seconds: int, notionals: tuple[int, ...]) -> dict:
    ex_date = event.exchange_ex_date
    pre_cutoff = dt.datetime.combine(ex_date - dt.timedelta(days=1), dt.time(20, 0), ET)
    post_cutoff = dt.datetime.combine(ex_date, RUNG_TIME[rule["rung"]], ET)
    pre_row, pre_distance, pre_error = _at(rows, pre_cutoff, before=True,
                                           max_lateness_seconds=max_lateness_seconds)
    post_row, post_distance, post_error = _at(rows, post_cutoff, before=False,
                                              max_lateness_seconds=max_lateness_seconds)
    pre_price, pre_price_source = _price(pre_row or {})
    post_price, post_price_source = _price(post_row or {})
    gross = float(event.gross_dividend_per_share) if event.gross_dividend_per_share is not None else None
    net = float(event.net_dividend_per_share) if event.net_dividend_per_share is not None else None
    pdr = (pre_price - post_price) / gross if None not in (pre_price, post_price, gross) and gross else None
    try:
        fee = float(event.instrument_snapshot["taker_fee"])
    except (KeyError, TypeError, ValueError):
        fee = None
    notionals_out = []
    for notional in notionals:
        sell_walk, sell_error, sell_source = walk(pre_row, "sell", notional)
        buy_walk, buy_error, buy_source = walk(post_row, "buy", notional)
        cost = None
        edge = None
        if None not in (pre_price, post_price, net, fee, sell_walk, buy_walk):
            cost = fee * (pre_price + post_price) + sell_walk * pre_price + buy_walk * post_price
            edge = (pre_price - post_price) - net - cost
        frozen_row = frozen.get((event.symbol, event.exchange_ex_date.isoformat(), notional))
        notionals_out.append(dict(
            notional_usd=notional, frozen_verdict=frozen_row.get("verdict") if frozen_row else None,
            frozen_reason=frozen_row.get("reason") if frozen_row else None,
            realized_edge_per_share=edge, realized_verdict=("EXIT" if edge is not None and edge > 0 else "HOLD" if edge is not None else "NO_SIGNAL"),
            cost_per_share=cost, sell_book_source=sell_source, buy_book_source=buy_source,
            sell_error=sell_error, buy_error=buy_error,
        ))
    return dict(
        event_id=event.event_id, symbol=event.symbol, ex_date=event.exchange_ex_date.isoformat(),
        rung=rule["rung"], pre_cutoff=pre_cutoff.isoformat(), post_cutoff=post_cutoff.isoformat(),
        pre_distance_seconds=pre_distance, post_distance_seconds=post_distance,
        pre_error=pre_error, post_error=post_error, pre_price=pre_price, post_price=post_price,
        pre_price_source=pre_price_source, post_price_source=post_price_source, gross_dividend=gross,
        net_dividend=net, realized_pdr=pdr, frozen_pdr_hat=rule["estimate"]["pdr_hat"],
        frozen_se=rule["estimate"]["se"], notionals=notionals_out,
        complete=pre_error is None and post_error is None and pdr is not None,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Score a completed EXNIGHT forward recorder window")
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--symbols", nargs="+", required=True)
    parser.add_argument("--event-date", required=True, type=dt.date.fromisoformat)
    parser.add_argument("--rule", type=Path, default=ROOT / "strategy" / "strategy_v1.json")
    parser.add_argument("--ledger", type=Path, default=ROOT / "data" / "ledger" / "reality_notice59_resolved.jsonl")
    parser.add_argument("--signals", type=Path, default=ROOT / "data" / "results" / "signals_v1.csv")
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "results" / "forward_score_v1.json")
    parser.add_argument("--max-gap-seconds", type=int, default=180)
    parser.add_argument("--max-lateness-seconds", type=int, default=180)
    args = parser.parse_args()

    rule = load_rule(args.rule)
    by_symbol, errors = read_rows(args.paths)
    all_times = [ts for rows in by_symbol.values() for ts, _ in rows]
    report = validate(by_symbol, errors, expected_symbols=args.symbols,
                      max_gap_seconds=args.max_gap_seconds, now=max(all_times) if all_times else None)
    frozen = _frozen_rows(args.signals)
    wanted = set(args.symbols)
    events = [e for e in read_ledger(args.ledger)
              if e.spot_symbol in wanted and e.exchange_ex_date == args.event_date]
    scored = [score_event(e, sorted(by_symbol.get(e.spot_symbol or "", [])), rule, frozen,
                          max_lateness_seconds=args.max_lateness_seconds,
                          notionals=tuple(rule["notionals_usd"])) for e in events]
    report.update(rule_id=rule["rule_id"], results=scored,
                  status="PASS" if report["status"] == "PASS" and all(r["complete"] for r in scored) else "INCOMPLETE")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    tmp = args.output.with_name(args.output.name + ".tmp")
    tmp.write_text(json.dumps(report, indent=1, default=str) + "\n")
    tmp.replace(args.output)
    print(json.dumps(dict(status=report["status"], validation=report["errors"],
                          events=[dict(symbol=r["symbol"], realized_pdr=r["realized_pdr"],
                                       frozen_verdict=(r["notionals"][0]["frozen_verdict"] if r["notionals"] else None))
                                  for r in scored]), indent=1))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Validate cadence and freshness of append-only forward recorder files.

This is a gate for forward scoring. It does not alter signals or infer a fill from
an empty order book: routed-liquidity symbols are reported separately.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from collections import defaultdict
from pathlib import Path


def parse_ts(value: object) -> dt.datetime:
    if not isinstance(value, str):
        raise ValueError("ts must be an ISO-8601 string")
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("ts must include a timezone")
    return parsed.astimezone(dt.UTC)


def read_rows(paths: list[Path]) -> tuple[dict[str, list[tuple[dt.datetime, dict]]], list[str]]:
    by_symbol: dict[str, list[tuple[dt.datetime, dict]]] = defaultdict(list)
    errors: list[str] = []
    for path in paths:
        try:
            handle = path.open(encoding="utf-8")
        except OSError as exc:
            errors.append(f"{path}: {exc}")
            continue
        with handle:
            for line_no, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                    ts = parse_ts(row.get("ts"))
                    symbol = row.get("symbol")
                    if not isinstance(symbol, str) or not symbol:
                        raise ValueError("symbol is missing")
                    by_symbol[symbol].append((ts, row))
                except (ValueError, TypeError, json.JSONDecodeError) as exc:
                    errors.append(f"{path}:{line_no}: {exc}")
    return by_symbol, errors


def validate(
    by_symbol: dict[str, list[tuple[dt.datetime, dict]]],
    errors: list[str],
    *,
    expected_symbols: list[str] = (),
    interval_seconds: int = 60,
    max_gap_seconds: int = 180,
    max_age_seconds: int | None = None,
    now: dt.datetime | None = None,
) -> dict:
    now = (now or dt.datetime.now(dt.UTC)).astimezone(dt.UTC)
    symbols = sorted(set(by_symbol) | set(expected_symbols))
    details: dict[str, dict] = {}
    failures = list(errors)
    for symbol in symbols:
        rows = by_symbol.get(symbol, [])
        timestamps = [ts for ts, _ in rows]
        gaps = [int((right - left).total_seconds()) for left, right in zip(timestamps, timestamps[1:])]
        duplicate_count = len(timestamps) - len(set(timestamps))
        out_of_order = sum(right < left for left, right in zip(timestamps, timestamps[1:]))
        last = max(timestamps) if timestamps else None
        ticker_rows = sum(bool(row.get("ticker")) for _, row in rows)
        nonempty_books = sum(bool((row.get("orderbook") or {}).get("bids") or (row.get("orderbook") or {}).get("asks")) for _, row in rows)
        detail = {
            "rows": len(rows),
            "first_ts": timestamps[0].isoformat() if timestamps else None,
            "last_ts": last.isoformat() if last else None,
            "max_gap_seconds": max(gaps, default=None),
            "gaps_over_limit": sum(gap > max_gap_seconds for gap in gaps),
            "duplicate_timestamps": duplicate_count,
            "out_of_order": out_of_order,
            "ticker_rows": ticker_rows,
            "nonempty_book_rows": nonempty_books,
            "last_age_seconds": (now - last).total_seconds() if last else None,
        }
        details[symbol] = detail
        if not rows:
            failures.append(f"{symbol}: no rows")
        if duplicate_count:
            failures.append(f"{symbol}: duplicate timestamps={duplicate_count}")
        if out_of_order:
            failures.append(f"{symbol}: out-of-order timestamps={out_of_order}")
        if detail["gaps_over_limit"]:
            failures.append(f"{symbol}: gaps over {max_gap_seconds}s={detail['gaps_over_limit']}")
        if max_age_seconds is not None and (last is None or detail["last_age_seconds"] > max_age_seconds):
            failures.append(f"{symbol}: latest sample is older than {max_age_seconds}s")
    return {
        "status": "PASS" if not failures else "FAIL",
        "checked_at": now.isoformat(),
        "expected_interval_seconds": interval_seconds,
        "max_gap_seconds": max_gap_seconds,
        "max_age_seconds": max_age_seconds,
        "symbols": details,
        "errors": failures,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate forward recorder cadence and freshness")
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--symbols", nargs="*", default=[])
    parser.add_argument("--interval-seconds", type=int, default=60)
    parser.add_argument("--max-gap-seconds", type=int, default=180)
    parser.add_argument("--max-age-seconds", type=int)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    by_symbol, errors = read_rows(args.paths)
    report = validate(
        by_symbol,
        errors,
        expected_symbols=args.symbols,
        interval_seconds=args.interval_seconds,
        max_gap_seconds=args.max_gap_seconds,
        max_age_seconds=args.max_age_seconds,
    )
    text = json.dumps(report, indent=2)
    print(text)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())

"""Select V3 forward-validation targets and write the recording schedule.

Selection is mechanical and happens before any target is recorded:

  - cash dividend with GROSS basis (tier 1-3) in the forward ledger;
  - ex-date after the plan date and within the horizon;
  - gross yield at the saved V3 reference price >= MIN_YIELD_BP.

MIN_YIELD_BP = 20 bp minimum round trip (0.1% taker on both legs) / 0.30 withholding. Below it,
EXIT is impossible under V3 even with a perfect estimate and documented 30% withholding, so
recording such an event cannot test the rule's EXIT side.

Windows (US Eastern): the sell cutoff is 20:00 ET on the previous weekday, the last moment
to step out before the ex-date. Recording runs from 16:00 ET that day to 10:30 ET on the
ex-date, which covers the cutoff, the overnight session and the 04:00 ET rung.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ET = ZoneInfo("America/New_York")
LEDGER = ROOT / "data" / "ledger" / "reality_forward_20260923_resolved.jsonl"
SIGNALS = ROOT / "data" / "results" / "signals_v3.csv"
OUTPUT = ROOT / "data" / "forward" / "v3_schedule.json"
MIN_YIELD_BP = 20 / 0.30
HORIZON_DAYS = 21
RECORD_FROM = dt.time(16, 0)
RECORD_TO = dt.time(10, 30)
SELL_CUTOFF = dt.time(20, 0)


def previous_weekday(day: dt.date) -> dt.date:
    day -= dt.timedelta(days=1)
    while day.weekday() >= 5:
        day -= dt.timedelta(days=1)
    return day


def window(ex_date: dt.date) -> dict:
    prior = previous_weekday(ex_date)
    return dict(
        sell_cutoff=dt.datetime.combine(prior, SELL_CUTOFF, ET).isoformat(),
        rung_0400=dt.datetime.combine(ex_date, dt.time(4, 0), ET).isoformat(),
        start=dt.datetime.combine(prior, RECORD_FROM, ET).astimezone(dt.UTC).isoformat(),
        end=dt.datetime.combine(ex_date, RECORD_TO, ET).astimezone(dt.UTC).isoformat(),
    )


def select(ledger: list[dict], prices: dict[str, float], plan_date: dt.date,
           horizon_days: int = HORIZON_DAYS) -> list[dict]:
    last = plan_date + dt.timedelta(days=horizon_days)
    out = []
    for e in ledger:
        ex = dt.date.fromisoformat(e["exchange_ex_date"])
        if (e["event_type"] != "CASH_DIV" or e["cash_dividend_basis"] != "GROSS"
                or e.get("basis_tier") not in (1, 2, 3) or not plan_date < ex <= last):
            continue
        price = prices.get(e["event_id"])
        gross = float(e["gross_dividend_per_share"])
        if price is None or price <= 0:
            continue
        yield_bp = 1e4 * gross / price
        if yield_bp >= MIN_YIELD_BP:
            out.append(dict(event_id=e["event_id"], symbol=e["symbol"], spot_symbol=e["spot_symbol"],
                            ex_date=ex.isoformat(), gross_dividend=gross, reference_price=price,
                            gross_yield_bp=round(yield_bp, 3)))
    return sorted(out, key=lambda r: (r["ex_date"], r["spot_symbol"]))


def groups(targets: list[dict]) -> list[dict]:
    by_date: dict[str, list[dict]] = {}
    for t in targets:
        by_date.setdefault(t["ex_date"], []).append(t)
    out = []
    for ex, items in sorted(by_date.items()):
        symbols = sorted(t["spot_symbol"] for t in items)
        label = "v3_" + ex.replace("-", "") + "_" + "_".join(s.removesuffix("USDT") for s in symbols)
        out.append(dict(label=label, ex_date=ex, symbols=symbols,
                        event_ids=sorted(t["event_id"] for t in items), **window(dt.date.fromisoformat(ex))))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Plan V3 forward recordings")
    ap.add_argument("--plan-date", type=dt.date.fromisoformat, required=True)
    ap.add_argument("--ledger", type=Path, default=LEDGER)
    ap.add_argument("--signals", type=Path, default=SIGNALS)
    ap.add_argument("--output", type=Path, default=OUTPUT)
    args = ap.parse_args()
    ledger = [json.loads(l) for l in args.ledger.read_text().splitlines() if l.strip()]
    sig = pd.read_csv(args.signals).drop_duplicates("event_id")
    prices = {r.event_id: float(r.price) for r in sig.itertuples() if pd.notna(r.price)}
    targets = select(ledger, prices, args.plan_date)
    plan = dict(
        rule_id="exnight-strategy-v3", planned_at=dt.datetime.now(dt.UTC).isoformat(),
        plan_date=args.plan_date.isoformat(), min_gross_yield_bp=MIN_YIELD_BP, horizon_days=HORIZON_DAYS,
        selection="GROSS basis tier 1-3, ex-date within horizon, gross yield at reference price >= min",
        reference_prices=f"{args.signals.relative_to(ROOT)} (V3 forward run)",
        ledger=str(args.ledger.relative_to(ROOT)), targets=targets, groups=groups(targets),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(plan, indent=1) + "\n")
    for g in plan["groups"]:
        print(g["label"], g["start"], "->", g["end"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

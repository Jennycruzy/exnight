"""Score a completed V3 forward recording against the V3 decision frozen before the cutoff.

Offline only. It reads the append-only recorder, the forward ledger, the schedule and the
frozen `signals_v3_<stamp>.csv` files. It never fetches a replacement price and never places
an order. The frozen decision used is the latest one whose `decided_at` precedes the event's
sell cutoff; if none exists, the event is scored but flagged NO_FROZEN_DECISION.

Realised EXIT edge per share, for the holder keeping share (1 - w) of the gross dividend:

    edge(w) = (P_pre - P_post) - gross * (1 - w) - cost

with P_pre the last sample before the sell cutoff, P_post the first sample at or after
04:00 ET, and cost = fee on both legs plus the book walk of each sample (ticker-only walks
are labelled). The realised verdict uses the frozen entitlement range: EXIT if edge(w_low) > 0,
HOLD if edge(w_high) <= 0, otherwise ENTITLEMENT_AMBIGUOUS.

When the recorded quotes cannot absorb a notional, the book-walk edge is undefined. Each event
therefore also carries the same edge at the walk-forward scorecard's MODELED_EXECUTION cost
(taker fee on both legs plus 25 bps round trip), labelled as modeled.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from score_forward import _at, _price, walk  # noqa: E402
from validate_recording import read_rows, validate  # noqa: E402

SCHEDULE = ROOT / "data" / "forward" / "v3_schedule.json"
RESULTS = ROOT / "data" / "results"
RECORDER = ROOT / "data" / "raw" / "recorder"
NOTIONALS = (1000, 5000, 25000)
MODELED_SLIPPAGE_BPS = 25   # the walk-forward scorecard's base MODELED_EXECUTION assumption


def frozen_decision(event_id: str, cutoff: dt.datetime, signal_files: list[Path]) -> tuple[pd.DataFrame, str | None]:
    """Rows of the latest frozen decision file decided before the cutoff that has the event."""
    best: tuple[dt.datetime, pd.DataFrame, str] | None = None
    for path in signal_files:
        frame = pd.read_csv(path)
        rows = frame[frame.event_id == event_id]
        if rows.empty:
            continue
        decided = dt.datetime.fromisoformat(str(rows.decided_at.iloc[0]))
        if decided < cutoff and (best is None or decided > best[0]):
            best = (decided, rows, path.name)
    return (best[1], best[2]) if best else (pd.DataFrame(), None)


def realised_verdict(edge_low: float | None, edge_high: float | None) -> str:
    if edge_low is None or edge_high is None:
        return "NO_SIGNAL"
    if edge_low > 0:
        return "EXIT"
    if edge_high <= 0:
        return "HOLD"
    return "ENTITLEMENT_AMBIGUOUS"


def score_event(target: dict, group: dict, event: dict, rows: list, signal_files: list[Path],
                *, max_lateness_seconds: int) -> dict:
    cutoff = dt.datetime.fromisoformat(group["sell_cutoff"])
    rung = dt.datetime.fromisoformat(group["rung_0400"])
    pre_row, pre_distance, pre_error = _at(rows, cutoff, before=True, max_lateness_seconds=max_lateness_seconds)
    post_row, post_distance, post_error = _at(rows, rung, before=False, max_lateness_seconds=max_lateness_seconds)
    pre, pre_source = _price(pre_row or {})
    post, post_source = _price(post_row or {})
    gross = float(event["gross_dividend_per_share"])
    fee = float(event["instrument_snapshot"]["taker_fee"])
    drop = pre - post if None not in (pre, post) else None
    decision, decision_file = frozen_decision(target["event_id"], cutoff, signal_files)
    notionals = []
    for notional in NOTIONALS:
        frozen = decision[decision.notional_usd == notional] if not decision.empty else decision
        f = frozen.iloc[0].to_dict() if not frozen.empty else {}
        sell, sell_error, sell_source = walk(pre_row, "sell", notional)
        buy, buy_error, buy_source = walk(post_row, "buy", notional)
        cost = edge0 = edge30 = edge_low = edge_high = None
        if None not in (drop, sell, buy):
            cost = fee * (pre + post) + sell * pre + buy * post
            edge0 = drop - gross - cost
            edge30 = drop - 0.70 * gross - cost
            if f:
                edge_low = drop - gross * (1 - float(f["w_low"])) - cost
                edge_high = drop - gross * (1 - float(f["w_high"])) - cost
        notionals.append(dict(
            notional_usd=notional, frozen_verdict=f.get("verdict"), frozen_reason=f.get("reason"),
            frozen_tier=f.get("entitlement_tier"), frozen_w_low=f.get("w_low"), frozen_w_high=f.get("w_high"),
            cost_per_share=cost, realised_edge_keep_gross=edge0, realised_edge_keep_70pct=edge30,
            realised_verdict=realised_verdict(edge_low, edge_high) if f else None,
            sell_book_source=sell_source, buy_book_source=buy_source, sell_error=sell_error, buy_error=buy_error,
        ))
    modeled = None
    if drop is not None:
        cost = pre * (2 * fee + MODELED_SLIPPAGE_BPS / 10_000)
        w_low = float(decision.w_low.iloc[0]) if not decision.empty else None
        w_high = float(decision.w_high.iloc[0]) if not decision.empty else None
        low = drop - gross * (1 - w_low) - cost if w_low is not None else None
        high = drop - gross * (1 - w_high) - cost if w_high is not None else None
        modeled = dict(label="MODELED_EXECUTION", slippage_bps=MODELED_SLIPPAGE_BPS, cost_per_share=cost,
                       edge_keep_gross=drop - gross - cost, edge_keep_70pct=drop - 0.70 * gross - cost,
                       realised_verdict=realised_verdict(low, high) if not decision.empty else None)
    complete = pre_error is None and post_error is None and drop is not None
    return dict(
        event_id=target["event_id"], spot_symbol=target["spot_symbol"], ex_date=target["ex_date"],
        sell_cutoff=cutoff.isoformat(), rung_0400=rung.isoformat(),
        pre_price=pre, post_price=post, pre_price_source=pre_source, post_price_source=post_source,
        pre_distance_seconds=pre_distance, post_distance_seconds=post_distance,
        pre_error=pre_error, post_error=post_error, gross_dividend=gross, taker_fee=fee,
        realised_pdr=drop / gross if drop is not None else None,
        frozen_decision_file=decision_file, notionals=notionals, modeled=modeled, complete=complete,
        has_frozen_decision=decision_file is not None,
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Score one V3 forward recording group")
    ap.add_argument("label", help="group label from data/forward/v3_schedule.json")
    ap.add_argument("--schedule", type=Path, default=SCHEDULE)
    ap.add_argument("--max-gap-seconds", type=int, default=180)
    ap.add_argument("--max-lateness-seconds", type=int, default=180)
    args = ap.parse_args()
    plan = json.loads(args.schedule.read_text())
    group = next((g for g in plan["groups"] if g["label"] == args.label), None)
    if group is None:
        raise SystemExit(f"unknown group {args.label}")
    ledger = {json.loads(l)["event_id"]: json.loads(l)
              for l in (ROOT / plan["ledger"]).read_text().splitlines() if l.strip()}
    targets = [t for t in plan["targets"] if t["event_id"] in group["event_ids"]]
    paths = sorted((RECORDER / group["label"]).glob("*.jsonl"))
    by_symbol, errors = read_rows(paths)
    times = [ts for rows in by_symbol.values() for ts, _ in rows]
    report = validate(by_symbol, errors, expected_symbols=group["symbols"],
                      max_gap_seconds=args.max_gap_seconds, now=max(times) if times else None)
    signal_files = sorted(RESULTS.glob("signals_v3_*.csv"))
    scored = [score_event(t, group, ledger[t["event_id"]], sorted(by_symbol.get(t["spot_symbol"], [])),
                          signal_files, max_lateness_seconds=args.max_lateness_seconds) for t in targets]
    passed = (report["status"] == "PASS" and all(r["complete"] and r["has_frozen_decision"] for r in scored))
    report.update(rule_id=plan["rule_id"], label=group["label"], results=scored,
                  status="PASS" if passed else "INCOMPLETE")
    out = RESULTS / f"forward_score_{group['label']}.json"
    tmp = out.with_name(out.name + ".tmp")
    tmp.write_text(json.dumps(report, indent=1, default=str) + "\n")
    tmp.replace(out)
    print(json.dumps(dict(status=report["status"], validation=report["errors"],
                          events=[dict(event=r["event_id"], pdr=r["realised_pdr"],
                                       frozen=r["notionals"][0]["frozen_verdict"],
                                       realised=r["notionals"][0]["realised_verdict"],
                                       realised_modeled=(r["modeled"] or {}).get("realised_verdict")) for r in scored]), indent=1))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())

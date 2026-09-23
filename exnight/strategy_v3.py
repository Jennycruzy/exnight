"""Strategy V3: the dividend-withholding wedge, traded only where entitlement is documented.

Registered in strategy/strategy_v3.json before any V3 figure was computed (docs/v3.md).

  lower_drop = min(pdr_hat - Z * se, CAP) * gross          (no credit for overshoot)
  EXIT       lower_drop - gross * (1 - w_low)  - cost > 0   (wins at the most the holder keeps)
  HOLD       lower_drop - gross * (1 - w_high) - cost <= 0  (loses at the least the holder keeps)
  NO_SIGNAL  otherwise (ENTITLEMENT_UNCERTAIN) or any unresolved input

Entitlement tiers:
  E1_DOCUMENTED_PRECEDENT  a registered Bitget distribution notice, available before the
                           decision, applied the 30% rule to the same symbol at an amount equal
                           to that past event's resolved gross -> withholding exactly 0.30
  E0_RANGE                 otherwise withholding in [0, 0.30]

`historical` is a POST_HOC_DIAGNOSTIC: V3 was designed after V1's walk-forward was seen, so
none of it is OOS evidence. `forward` issues the decisions that count.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import re
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from . import basis
from .analysis import slope_pdr
from .calendar import _text_lines, parse_dividend_notice_2026_07_24
from .sources import SOURCES

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "data" / "results"
RULE = ROOT / "strategy" / "strategy_v3.json"
LEDGER = ROOT / "data" / "ledger" / "reality_notice59_resolved.jsonl"
EVENT_RESULTS = RESULTS / "event_results_resolved.json"
PENDING_LEDGER = ROOT / "data" / "ledger" / "reality_forward_20260923_resolved.jsonl"
KNOWLEDGE = RESULTS / "competition_knowledge_time.csv"
PROVENANCE = RESULTS / "dividend_provenance_candidates_20260923.csv"

ET = ZoneInfo("America/New_York")
PAGE_ZONE = ZoneInfo("Asia/Shanghai")   # Bitget support pages print UTC+8
Z = 2.0
CAP = 1.0
RUNG = "premarket_0400"
MIN_EVENTS = 15
NOTICE_WITHHOLDING = 0.30
RANGE = (float(basis.WITHHOLDING_LOW), float(basis.WITHHOLDING_HIGH))
AMOUNT_TOL = 0.005
BASIS_TIERS = (1, 2, 3)
AVAILABILITY_MODES = ("primary", "content_bound")


def load_rule(path: Path = RULE) -> dict:
    """The registered rule must mean what this code does."""
    rule = json.loads(path.read_text())
    for key, actual in (("rule_id", "exnight-strategy-v3"), ("z", Z), ("rung", RUNG),
                        ("lower_bound_cap", CAP)):
        if rule[key] != actual:
            raise ValueError(f"{path.name}: {key}={rule[key]!r} but the code uses {actual!r}")
    if rule["estimate_procedure"]["min_events"] != MIN_EVENTS:
        raise ValueError(f"{path.name}: min_events differs from the code")
    return rule


# --- entitlement -------------------------------------------------------------------------

def _parse_notice_89() -> list[dict]:
    src = SOURCES["dividends_89_2026_09_23"]
    lines = _text_lines(src.read())
    hdr = ["Ticker", "Ex-Dividend Date", "Payment Date", "Dividend per Share"]
    for i in range(len(lines) - 3):
        if lines[i: i + 4] == hdr:
            i += 4
            break
    else:
        raise RuntimeError("dividend table header not found in saved 89-stock notice")
    rows = []
    while i + 3 < len(lines) and re.fullmatch(r"r[A-Z]+", lines[i]):
        tk, ex, pay, dps = lines[i: i + 4]
        # The table prints dates without a year; every listed payment is in 2026.
        rows.append(dict(symbol=tk,
                         ex_date=dt.datetime.strptime(f"{ex} 2026", "%b %d %Y").date(),
                         payment_date=dt.datetime.strptime(f"{pay} 2026", "%b %d %Y").date(),
                         amount=Decimal(dps)))
        i += 4
    if len(rows) != 89:
        raise RuntimeError(f"notice title says 89 stocks; parsed {len(rows)} rows")
    return rows


def _availability(key: str, rows: list[dict]) -> dict[str, dt.datetime]:
    src = SOURCES[key]
    if not src.available_by:
        raise RuntimeError(f"source {key} has no provable availability time")
    displayed = dt.datetime.strptime(src.published, "%Y-%m-%d %H:%M").replace(tzinfo=PAGE_ZONE)
    last_payment = dt.datetime.combine(max(r["payment_date"] for r in rows), dt.time.min, ET)
    return {"primary": dt.datetime.fromisoformat(src.available_by),
            "content_bound": max(displayed, last_payment)}


def notice_rows() -> list[dict]:
    """Every row of every registered notice that states the 30% rule."""
    out = []
    n63 = [dict(symbol=r["symbol"], ex_date=r["exchange_ex_date"], payment_date=r["payment_date"],
                amount=r["gross_dividend_per_share"]) for r in parse_dividend_notice_2026_07_24()]
    for key, rows in (("dividends_2026_07_24", n63), ("dividends_89_2026_09_23", _parse_notice_89())):
        available = _availability(key, rows)
        out += [r | {"source_key": key, "available": available} for r in rows]
    return out


def _gross_index(ledger: list[dict]) -> dict[tuple[str, dt.date], float]:
    return {(e["symbol"], dt.date.fromisoformat(e["exchange_ex_date"])): float(e["gross_dividend_per_share"])
            for e in ledger
            if e["event_type"] == "CASH_DIV" and e["cash_dividend_basis"] == "GROSS"
            and e.get("basis_tier") in BASIS_TIERS and e.get("gross_dividend_per_share") is not None}


def precedents(ledger: list[dict], rows: list[dict] | None = None) -> list[dict]:
    """Notice rows whose printed amount equals the resolved gross of that past event.

    A mismatch (the NXPI/MDT home-country-net case) or an event without resolved gross is not
    a precedent: the notice would not show that the 30% rule applied to the gross amount.
    """
    gross = _gross_index(ledger)
    valid = []
    for r in rows if rows is not None else notice_rows():
        g = gross.get((r["symbol"], r["ex_date"]))
        if g is not None and g > 0 and abs(float(r["amount"]) - g) / g <= AMOUNT_TOL:
            valid.append(r)
    return valid


def entitlement(symbol: str, ex_date: dt.date, decision_ts: dt.datetime, prior: list[dict],
                mode: str = "primary") -> dict:
    if mode not in AVAILABILITY_MODES:
        raise ValueError(f"unknown availability mode {mode}")
    hits = [p for p in prior if p["symbol"] == symbol and p["ex_date"] < ex_date
            and p["available"][mode] <= decision_ts]
    if hits:
        best = max(hits, key=lambda p: p["ex_date"])
        return dict(tier="E1_DOCUMENTED_PRECEDENT", w_low=NOTICE_WITHHOLDING, w_high=NOTICE_WITHHOLDING,
                    evidence=f"{best['source_key']}: {symbol} ex {best['ex_date']} {best['amount']} at 30%, "
                             f"available {best['available'][mode].isoformat()} ({mode})")
    return dict(tier="E0_RANGE", w_low=RANGE[0], w_high=RANGE[1], evidence="no pre-decision precedent")


# --- decision ----------------------------------------------------------------------------

def decide(*, pdr: float, se: float, gross: float, price: float, cost_per_share: float,
           w_low: float, w_high: float) -> dict:
    """Pure V3 arithmetic. Inputs are per share; returns verdict, edges and break-even yield."""
    for name, value in (("pdr", pdr), ("se", se), ("gross", gross), ("price", price),
                        ("cost_per_share", cost_per_share)):
        if value is None or not math.isfinite(value):
            raise ValueError(f"{name} must be finite")
    if se < 0 or gross <= 0 or price <= 0 or cost_per_share < 0 or not 0 <= w_low <= w_high <= 1:
        raise ValueError("invalid decision inputs")
    lower_ratio = min(pdr - Z * se, CAP)
    lower_drop = lower_ratio * gross
    edge_most_kept = lower_drop - gross * (1 - w_low) - cost_per_share
    edge_least_kept = lower_drop - gross * (1 - w_high) - cost_per_share
    if edge_most_kept > 0:
        verdict, reason = "EXIT", ""
    elif edge_least_kept <= 0:
        verdict, reason = "HOLD", ""
    else:
        verdict, reason = "NO_SIGNAL", "ENTITLEMENT_UNCERTAIN"
    denominator = lower_ratio - (1 - w_low)
    breakeven = cost_per_share / price / denominator if denominator > 0 else math.inf
    return dict(verdict=verdict, reason=reason, lower_ratio=lower_ratio,
                edge_most_kept=edge_most_kept, edge_least_kept=edge_least_kept,
                gross_yield=gross / price, breakeven_yield=breakeven)


# --- estimate ----------------------------------------------------------------------------

def _frame(results: list[dict], allowed: set[str] | None = None) -> pd.DataFrame:
    rows = []
    for r in results:
        if not r["usable"] or (allowed is not None and r["event_id"] not in allowed):
            continue
        post, post_ts = (r["p_post"] or {}).get(RUNG), (r["p_post_ts"] or {}).get(RUNG)
        if r["p_pre"] is None or post is None or post_ts is None or r["gross_dividend"] is None:
            continue
        rows.append(dict(event_id=r["event_id"], symbol=r["symbol"], ex_date=dt.date.fromisoformat(r["ex_date"]),
                         decision_ts=pd.Timestamp(r["p_pre_ts"]), p_pre=float(r["p_pre"]),
                         p_post=float(post), outcome_ts=pd.Timestamp(post_ts),
                         gross=float(r["gross_dividend"]), fee_rate=float(r["fee_rate"])))
    return pd.DataFrame(rows).sort_values(["decision_ts", "event_id"]).reset_index(drop=True)


def estimate(frame: pd.DataFrame, before: dt.datetime) -> dict:
    training = frame[frame.outcome_ts < pd.Timestamp(before)]
    if len(training) < MIN_EVENTS:
        raise RuntimeError(f"only {len(training)} estimation events before {before}; need {MIN_EVENTS}")
    fit = slope_pdr(training.p_pre, training.p_post, training.gross, training.symbol)
    if fit["pdr"] is None or fit["se"] is None:
        raise RuntimeError(f"no {RUNG} slope before {before}")
    return dict(pdr=float(fit["pdr"]), se=float(fit["se"]), n=int(fit["n"]),
                lower_ratio=min(float(fit["pdr"]) - Z * float(fit["se"]), CAP),
                last_event=max(training.ex_date).isoformat())


def _read_ledger(path: Path = LEDGER) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _forward_estimation_ids(ledger: list[dict]) -> set[str]:
    return {e["event_id"] for e in ledger if e["event_type"] == "CASH_DIV"
            and e["cash_dividend_basis"] == "GROSS" and e.get("basis_tier") in BASIS_TIERS}


def _historical_ids() -> tuple[set[str], set[str]]:
    knowledge = pd.read_csv(KNOWLEDGE, keep_default_na=False)
    frozen = set(knowledge.loc[knowledge.eligible_ex_ante == "YES", "event_id"])
    with PROVENANCE.open(newline="") as stream:
        added = {r["event_id"] for r in csv.DictReader(stream)
                 if r["primary_review_status"] == "MATCHED_PRE_DECISION_PRIMARY"}
    return frozen, added


# --- historical diagnostic ---------------------------------------------------------------

FOLDS = (("OOS_2026_08", dt.date(2026, 8, 1), dt.date(2026, 8, 31)),
         ("OOS_2026_09", dt.date(2026, 9, 1), dt.date(2026, 9, 16)))
SLIPPAGE_BPS = 25


def _evaluate(test: pd.DataFrame, est: dict, prior: list[dict], *, fold: str, mode: str,
              slippage_bps: int, realised_withholding: str) -> list[dict]:
    from .competition import CAPITAL, NOTIONAL
    rows = []
    for r in test.itertuples(index=False):
        ent = entitlement(r.symbol, r.ex_date, r.decision_ts.to_pydatetime(), prior, mode)
        cost = r.p_pre * (2 * r.fee_rate + slippage_bps / 10_000)
        d = decide(pdr=est["pdr"], se=est["se"], gross=r.gross, price=r.p_pre, cost_per_share=cost,
                   w_low=ent["w_low"], w_high=ent["w_high"])
        rows.append((r, ent, d))
    # Same concurrency rule as the competition manifest: best edge first, 25 per ex-date.
    selected: set[str] = set()
    by_date: dict[dt.date, list] = {}
    for item in rows:
        by_date.setdefault(item[0].ex_date, []).append(item)
    for items in by_date.values():
        items.sort(key=lambda x: (-x[2]["edge_most_kept"], x[0].decision_ts, x[0].event_id))
        selected.update(x[0].event_id for x in items[: int(CAPITAL // NOTIONAL)])
    out = []
    for r, ent, d in rows:
        verdict = d["verdict"] if r.event_id in selected else "NO_SIGNAL"
        # HOLD's retained dividend: the documented 30% where E1, else the stated assumption.
        w = ent["w_low"] if ent["tier"] == "E1_DOCUMENTED_PRECEDENT" else (
            RANGE[0] if realised_withholding == "hardest" else RANGE[1])
        benchmark = (r.p_post - r.p_pre + r.gross * (1 - w)) / r.p_pre
        fee, slip = 2 * r.fee_rate, slippage_bps / 10_000
        policy = -(fee + slip) if verdict == "EXIT" else benchmark
        out.append(dict(fold=fold, event_id=r.event_id, symbol=r.symbol, ex_date=r.ex_date.isoformat(),
                        decision_ts=r.decision_ts.isoformat(), availability=mode, pdr_hat=est["pdr"],
                        pdr_se=est["se"], estimation_events=est["n"], lower_ratio=d["lower_ratio"],
                        entitlement_tier=ent["tier"], w_low=ent["w_low"], w_high=ent["w_high"],
                        gross_yield_bp=1e4 * d["gross_yield"],
                        breakeven_yield_bp=1e4 * d["breakeven_yield"] if math.isfinite(d["breakeven_yield"]) else None,
                        verdict=verdict, reason=d["reason"], edge_most_kept=d["edge_most_kept"],
                        edge_least_kept=d["edge_least_kept"], retained_withholding=w,
                        policy_return=policy, benchmark_return=benchmark, active_return=policy - benchmark,
                        fee_drag_return=fee if verdict == "EXIT" else 0.0,
                        slippage_drag_return=slip if verdict == "EXIT" else 0.0))
    return out


def historical() -> dict:
    from .competition import OOS_END, OOS_START, _score_period
    ledger = _read_ledger()
    prior = precedents(ledger)
    frozen, added = _historical_ids()
    frame = _frame(json.loads(EVENT_RESULTS.read_text()), frozen | added)
    report = {"label": "POST_HOC_DIAGNOSTIC_NOT_OOS", "execution": "MODELED_EXECUTION",
              "rule_id": load_rule()["rule_id"], "rung": RUNG, "z": Z, "cap": CAP,
              "sample": {"frozen_ex_ante": len(frozen & set(frame.event_id)),
                         "verified_additions": len(added & set(frame.event_id)), "total": len(frame)},
              "valid_notice_precedents": len(prior), "runs": {}}
    decisions = []
    for mode in AVAILABILITY_MODES:
        for assumption in ("hardest", "notice_rate"):
            rows, folds = [], []
            for name, start, end in FOLDS:
                first_decision = dt.datetime.combine(start, dt.time(20), ET) - dt.timedelta(days=1)
                est = estimate(frame, first_decision)
                test = frame[(frame.ex_date >= start) & (frame.ex_date <= end)]
                fold_rows = _evaluate(test, est, prior, fold=name, mode=mode, slippage_bps=SLIPPAGE_BPS,
                                      realised_withholding=assumption)
                rows += fold_rows
                folds.append({"fold": name, "estimate": est, "test_events": len(test),
                              "exit": sum(r["verdict"] == "EXIT" for r in fold_rows),
                              "hold": sum(r["verdict"] == "HOLD" for r in fold_rows),
                              "no_signal": sum(r["verdict"] == "NO_SIGNAL" for r in fold_rows),
                              "e1_events": sum(r["entitlement_tier"] == "E1_DOCUMENTED_PRECEDENT" for r in fold_rows)})
            key = f"{mode}__{assumption}"
            report["runs"][key] = {"folds": folds, "score": _score_period(rows, OOS_START, OOS_END)}
            decisions += [r | {"run": key} for r in rows]
    out = RESULTS / "v3_historical_diagnostic.json"
    out.write_text(json.dumps(report, indent=2, default=str) + "\n")
    pd.DataFrame(decisions).to_csv(RESULTS / "v3_historical_decisions.csv", index=False)
    return report


# --- forward ------------------------------------------------------------------------------

def forward(now: dt.datetime | None = None, pending_ledger: Path = PENDING_LEDGER) -> pd.DataFrame:
    """Ex-ante V3 decisions for every pending cash dividend in `pending_ledger`.

    The estimate and notice precedents come from the resolved study ledger; pending events
    come from the broader full-universe ledger, whose resolved rows use the same basis tiers.
    """
    from .costs import NOTIONALS, latest_samples, load_depth
    from .market import BitgetPublic
    from .strategy import MAX_DEPTH_AGE_SECONDS, round_trip_cost, write_run_manifest

    rule = load_rule()
    now = now or dt.datetime.now(dt.UTC)
    ledger = _read_ledger()
    prior = precedents(ledger)
    est = estimate(_frame(json.loads(EVENT_RESULTS.read_text()), _forward_estimation_ids(ledger)), now)
    samples = latest_samples(load_depth(), as_of=now, max_age_seconds=MAX_DEPTH_AGE_SECONDS)
    api = BitgetPublic()
    universe = {s.symbol: s for s in api.rtokens().values()}
    tickers = {t["symbol"]: t for t in api.tickers()}
    today = now.astimezone(ET).date()
    rows = []
    for e in _read_ledger(pending_ledger):
        ex = dt.date.fromisoformat(e["exchange_ex_date"])
        if e["event_type"] != "CASH_DIV" or ex <= today:
            continue
        spot = e.get("spot_symbol")
        base = dict(rule=rule["rule_id"], event_id=e["event_id"], symbol=e["symbol"], spot_symbol=spot,
                    ex_date=ex.isoformat(), decided_at=now.isoformat(), pdr_hat=est["pdr"], pdr_se=est["se"],
                    estimation_events=est["n"], lower_ratio=est["lower_ratio"])
        gross = e.get("gross_dividend_per_share")
        ent = entitlement(e["symbol"], ex, now, prior)
        base |= dict(entitlement_tier=ent["tier"], w_low=ent["w_low"], w_high=ent["w_high"],
                     entitlement_evidence=ent["evidence"], gross_dividend=gross)
        ticker = tickers.get(spot or "", {})
        price = float(ticker["lastPrice"]) if ticker.get("lastPrice") else None
        for notional in NOTIONALS:
            row = base | dict(notional_usd=notional, price=price, verdict="NO_SIGNAL", reason="")
            if e["cash_dividend_basis"] != "GROSS" or e.get("basis_tier") not in BASIS_TIERS or gross is None:
                row["reason"] = f"cash basis {e['cash_dividend_basis']}; gross basis required"
            elif spot not in universe:
                row["reason"] = "symbol not in the live Reality universe"
            elif price is None or not math.isfinite(price) or price <= 0:
                row["reason"] = "no valid reference price"
            else:
                g = float(gross)
                cost, why, meta = round_trip_cost(samples, spot, price, float(universe[spot].taker_fee), notional,
                                                  price - min(est["pdr"], CAP) * g)
                row |= meta
                if cost is None:
                    row["reason"] = why
                else:
                    d = decide(pdr=est["pdr"], se=est["se"], gross=g, price=price, cost_per_share=cost,
                               w_low=ent["w_low"], w_high=ent["w_high"])
                    row |= dict(cost_per_share=cost, verdict=d["verdict"], reason=d["reason"],
                                edge_most_kept=d["edge_most_kept"], edge_least_kept=d["edge_least_kept"],
                                gross_yield_bp=1e4 * d["gross_yield"],
                                breakeven_yield_bp=1e4 * d["breakeven_yield"] if math.isfinite(d["breakeven_yield"]) else None)
            rows.append(row)
    frame = pd.DataFrame(rows)
    out = RESULTS / "signals_v3.csv"
    frame.to_csv(out, index=False)
    write_run_manifest(rule, rule_path=RULE, inputs=[LEDGER, pending_ledger, EVENT_RESULTS], outputs=[out], tag="_v3",
                       forward_signals=frame)
    return frame


def main() -> None:
    parser = argparse.ArgumentParser(description="Strategy V3: entitlement-aware dividend wedge")
    parser.add_argument("action", choices=("historical", "forward"))
    parser.add_argument("--pending-ledger", type=Path, default=PENDING_LEDGER,
                        help="ledger supplying upcoming events (forward only)")
    args = parser.parse_args()
    if args.action == "historical":
        report = historical()
        for key, run in report["runs"].items():
            print(key, [(f["fold"], f["estimate"]["pdr"], f["estimate"]["se"], f["exit"], f["hold"],
                         f["no_signal"], f["e1_events"]) for f in run["folds"]],
                  "active", run["score"]["active"]["total_return"])
    else:
        frame = forward(pending_ledger=args.pending_ledger)
        print(frame.groupby(["verdict", "entitlement_tier"]).size().to_string())


if __name__ == "__main__":
    main()

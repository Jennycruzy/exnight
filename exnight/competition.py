"""Leakage-resistant Alpha Factory walk-forward and scorecard.

This module deliberately has two phases. ``prepare`` writes the knowledge-time table and
the frozen manifest; ``score`` refuses to run unless the manifest hash still matches. That
ordering makes it difficult to change a convention after seeing OOS performance.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import hashlib
import json
import math
import re
import subprocess
from collections import Counter
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from .analysis import RUNG_ORDER, slope_pdr

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "data" / "results"
LEDGER = ROOT / "data" / "ledger" / "reality_notice59_resolved.jsonl"
EVENT_RESULTS = RESULTS / "event_results_resolved.json"
BASIS = RESULTS / "basis_resolution.csv"
KNOWLEDGE = RESULTS / "competition_knowledge_time.csv"
MANIFEST = RESULTS / "competition_backtest_manifest.json"
MANIFEST_HASH = RESULTS / "competition_backtest_manifest.sha256"
SCORECARD = RESULTS / "competition_scorecard.json"
DECISIONS = RESULTS / "competition_decisions.csv"

ET = ZoneInfo("America/New_York")
UTC = dt.timezone.utc
WITHHOLDING_GRID = (0.00, 0.15, 0.25, 0.30)
SLIPPAGE_GRID = (10, 25, 50, 100)
Z = 2.0
INITIAL_END = dt.date(2026, 7, 31)
OOS_START = dt.date(2026, 8, 1)
OOS_END = dt.date(2026, 9, 16)
MIN_TRAINING_EVENTS = 15
MIN_SUBPERIOD_EVENTS = 3
NOTIONAL = 1_000.0
CAPITAL = 25_000.0
BASE_SLIPPAGE_BPS = 25
PRIMARY_WITHHOLDING = 0.00


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _parse_ts(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def _declaration_date(record: dict) -> dt.date | None:
    match = re.search(r"declared (\d{2}/\d{2}/\d{4})", record.get("evidence") or "")
    return dt.datetime.strptime(match.group(1), "%m/%d/%Y").date() if match else None


def _write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else []
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(path)


def build_knowledge_table() -> list[dict]:
    """Create one auditable knowledge-time row for every historical result row."""
    ledger = {r["event_id"]: r for r in map(json.loads, LEDGER.read_text().splitlines())}
    basis = {r["event_id"]: r for r in csv.DictReader(BASIS.open())}
    results = json.loads(EVENT_RESULTS.read_text())
    rows: list[dict] = []
    notice_published = dt.datetime(2026, 7, 23, 17, 42, tzinfo=UTC)
    for result in results:
        event = ledger[result["event_id"]]
        resolved = basis.get(result["event_id"], {})
        decision = _parse_ts(result.get("p_pre_ts"))
        declaration = _declaration_date(resolved)
        source = "other"
        published: dt.datetime | None = None
        if declaration is not None:
            # The saved Nasdaq declaration record contains amount, ex-date and declaration
            # date. It is pre-event declaration evidence, not realised dividend data.
            source = "other:nasdaq_declared"
            published = dt.datetime.combine(declaration, dt.time.min, ET)
        elif event.get("basis_tier") == 1:
            source = "bitget_notice"
            published = notice_published
        elif resolved.get("issuer_realised"):
            source = "yahoo_realised"
            published = _parse_ts(event.get("source_fetched_at"))

        gross_known = bool(decision and published and published <= decision and declaration is not None)
        withholding_source = "other:robust_range"
        withholding_published: dt.datetime | None = None
        withholding_status = "RANGE_USED"
        if event.get("net_dividend_verified") and event.get("basis_tier") == 1:
            withholding_source = "bitget_notice"
            withholding_published = notice_published
            withholding_status = "YES" if decision and notice_published <= decision else "NO"

        reasons: list[str] = []
        if event.get("event_type") != "CASH_DIV":
            reasons.append("NON_CASH_ACTION")
        if not result.get("usable"):
            reasons.append("DISCOVERY_EVENT_UNUSABLE")
        if decision is None:
            reasons.append("NO_VALID_T0_OBSERVATION")
        if not gross_known:
            reasons.append("NO_PRE_DECISION_GROSS_DECLARATION")
        eligible = not reasons
        rows.append({
            "event_id": result["event_id"],
            "symbol": result["symbol"],
            "event_type": event["event_type"],
            "ex_date": result["ex_date"],
            "decision_ts": decision.isoformat() if decision else "",
            "t0_price": result.get("p_pre") if result.get("p_pre") is not None else "",
            "t1_overnight_2000_ts": (result.get("p_post_ts") or {}).get("overnight_2000") or "",
            "t1_premarket_0400_ts": (result.get("p_post_ts") or {}).get("premarket_0400") or "",
            "gross_dividend": result.get("gross_dividend") if result.get("gross_dividend") is not None else "",
            "gross_dividend_source": source,
            "gross_dividend_published_ts": published.isoformat() if published else "",
            "gross_known_before_decision": "YES" if gross_known else "NO",
            "withholding_source": withholding_source,
            "withholding_published_ts": withholding_published.isoformat() if withholding_published else "",
            "withholding_known_before_decision": withholding_status,
            "fee_schedule_in_force": result.get("fee_label") or "",
            "fee_rate": result.get("fee_rate") if result.get("fee_rate") is not None else "",
            "cost_assumption": f"MODELED_EXECUTION:{BASE_SLIPPAGE_BPS}_BPS_ROUND_TRIP",
            "eligible_ex_ante": "YES" if eligible else "NO",
            "exclusion_reason": ";".join(reasons),
        })
    _write_csv(KNOWLEDGE, rows)
    return rows


def _git_head() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, check=True,
                          capture_output=True, text=True).stdout.strip()


def prepare() -> dict:
    rows = build_knowledge_table()
    eligible = [r for r in rows if r["eligible_ex_ante"] == "YES"]
    exclusions = Counter(reason for r in rows for reason in r["exclusion_reason"].split(";") if reason)
    inputs = [LEDGER, EVENT_RESULTS, BASIS, KNOWLEDGE, ROOT / "exnight" / "competition.py",
              ROOT / "docs" / "m2.md", ROOT / "strategy" / "strategy_v1.json"]
    manifest = {
        "procedure": "expanding-window walk-forward selection; initial development window then non-overlapping monthly test folds",
        "v1_provenance": "Case B — V1 coefficient fit on all 127 usable events; no historical V1 OOS window exists",
        "candidate_rungs": RUNG_ORDER,
        "rung_selection_rule": (
            "On training data only, estimate each candidate by calendar subperiods with at least 3 events. "
            "A rung is stable when its point estimate remains above the documented 0.70 retained-dividend "
            "alternative and PDR=1 lies within pdr_hat ± 2*SE in every eligible subperiod; "
            "choose the earliest stable rung in market-clock order. If none passes, use premarket_0400 "
            "as the documented V1 robust fallback."
        ),
        "rung_rule_derived_from": [
            "c7463451532fd346c27526029a39f6625640c0f9",
            "docs/m2.md sections 2–3",
        ],
        "rung_rule_written_after_v1_freeze": True,
        "fold_scheme": "initial development through 2026-07-31; test 2026-08-01..08-31; refit; test 2026-09-01..09-16",
        "min_training_events": MIN_TRAINING_EVENTS,
        "min_subperiod_events": MIN_SUBPERIOD_EVENTS,
        "oos_start": OOS_START.isoformat(),
        "oos_end": OOS_END.isoformat(),
        "oos_calendar_days": (OOS_END - OOS_START).days + 1,
        "portfolio_definition": (
            "Holder overlay from T0, the final valid Bitget observation at/before the V1 pre-event cutoff, "
            "to T1, the first valid observation at/after the selected rung. decision_ts=T0. HOLD accrues "
            "retained dividend at T1; EXIT holds USDT and pays modeled round-trip cost; active=policy-HOLD."
        ),
        "notional_usdt": int(NOTIONAL),
        "capital_base_usdt": int(CAPITAL),
        "concurrency_rule": "highest ex-ante lower-bound edge first; ties by decision_ts then event_id; maximum 25 concurrent events",
        "fee_source": "per-event documented 0.05% taker rate through 2026-08-31; saved symbol taker rate thereafter; both legs",
        "slippage_base_bps": BASE_SLIPPAGE_BPS,
        "slippage_base_justification": "fixed a priori before OOS computation; uncertainty reported at 10/25/50/100 bps",
        "slippage_sensitivity_bps": list(SLIPPAGE_GRID),
        "withholding_handling": "event-specific only if published pre-decision, else range [0.00, 0.15, 0.25, 0.30]; EXIT must survive 0.00",
        "primary_reporting_withholding": PRIMARY_WITHHOLDING,
        "knowledge_time_rows": len(rows),
        "eligible_ex_ante_rows": len(eligible),
        "exclusion_counts": dict(sorted(exclusions.items())),
        "input_hashes": {str(p.relative_to(ROOT)): _sha256(p) for p in inputs},
        "code_commit": _git_head(),
        "written_at": dt.datetime.now(UTC).isoformat(),
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    digest = _sha256(MANIFEST)
    MANIFEST_HASH.write_text(f"{digest}  {MANIFEST.name}\n")
    print(json.dumps({"manifest_sha256": digest, "eligible_ex_ante": len(eligible),
                      "total_rows": len(rows)}, indent=2))
    return manifest


def _verify_frozen_manifest() -> dict:
    manifest = json.loads(MANIFEST.read_text())
    expected = MANIFEST_HASH.read_text().split()[0]
    if _sha256(MANIFEST) != expected:
        raise RuntimeError("competition manifest changed after it was hashed")
    for name, digest in manifest["input_hashes"].items():
        if _sha256(ROOT / name) != digest:
            raise RuntimeError(f"frozen input changed: {name}")
    return manifest


def _eligible_frame() -> pd.DataFrame:
    knowledge = pd.read_csv(KNOWLEDGE, keep_default_na=False)
    allowed = set(knowledge.loc[knowledge.eligible_ex_ante == "YES", "event_id"])
    rows = []
    for result in json.loads(EVENT_RESULTS.read_text()):
        if result["event_id"] not in allowed:
            continue
        row = {
            "event_id": result["event_id"], "symbol": result["symbol"],
            "ex_date": pd.Timestamp(result["ex_date"]).date(), "decision_ts": pd.Timestamp(result["p_pre_ts"]),
            "p_pre": float(result["p_pre"]), "gross": float(result["gross_dividend"]),
            "fee_rate": float(result["fee_rate"]),
        }
        outcome_times = []
        for rung in RUNG_ORDER:
            row[f"p_{rung}"] = (result["p_post"] or {}).get(rung)
            row[f"ts_{rung}"] = (result["p_post_ts"] or {}).get(rung)
            if row[f"ts_{rung}"]:
                outcome_times.append(pd.Timestamp(row[f"ts_{rung}"]))
        row["outcome_observable_ts"] = max(outcome_times)
        rows.append(row)
    return pd.DataFrame(rows).sort_values(["decision_ts", "event_id"]).reset_index(drop=True)


def _estimate(frame: pd.DataFrame, rung: str) -> dict:
    return slope_pdr(frame.p_pre, frame[f"p_{rung}"], frame.gross, frame.symbol)


def select_rung(training: pd.DataFrame) -> tuple[str, dict]:
    diagnostics: dict = {}
    stable: list[str] = []
    periods = training.assign(period=training.ex_date.map(lambda d: d.strftime("%Y-%m"))).groupby("period")
    for rung in RUNG_ORDER:
        cuts = []
        for period, cut in periods:
            if len(cut) < MIN_SUBPERIOD_EVENTS:
                continue
            estimate = _estimate(cut, rung)
            passed = bool(estimate["pdr"] is not None and estimate["se"] is not None
                          and estimate["pdr"] > 0.70
                          and estimate["pdr"] - 2 * estimate["se"] <= 1
                          <= estimate["pdr"] + 2 * estimate["se"])
            cuts.append({"period": period, **estimate, "gross_pdr_not_rejected": passed})
        diagnostics[rung] = cuts
        if cuts and all(c["gross_pdr_not_rejected"] for c in cuts):
            stable.append(rung)
    selected = stable[0] if stable else "premarket_0400"
    return selected, {"stable_rungs": stable, "subperiods": diagnostics,
                      "fallback_used": not bool(stable)}


def _decision(estimate: dict, row, slippage_bps: int, withholding: float | None) -> tuple[str, float]:
    expected_drop = (estimate["pdr"] - Z * estimate["se"]) * row.gross
    cost = row.p_pre * (2 * row.fee_rate + slippage_bps / 10_000)
    if withholding is not None:
        edge = expected_drop - row.gross * (1 - withholding) - cost
        return ("EXIT" if edge > 0 else "HOLD"), edge
    edge_best_holder = expected_drop - row.gross - cost
    edge_worst_holder = expected_drop - row.gross * 0.70 - cost
    if edge_best_holder > 0:
        return "EXIT", edge_best_holder
    if edge_worst_holder <= 0:
        return "HOLD", edge_worst_holder
    return "NO_SIGNAL", edge_best_holder


def _evaluate(frame: pd.DataFrame, rung: str, estimate: dict, *, fold: str,
              slippage_bps: int, withholding: float, robust: bool) -> list[dict]:
    candidates = []
    for row in frame.itertuples(index=False):
        verdict, edge = _decision(estimate, row, slippage_bps, None if robust else withholding)
        candidates.append((row, verdict, edge))
    # The interval is overnight and each event ends at T1; same-ex-date events are the
    # concurrency set. Capacity is 25 at $1k/$25k.
    selected: set[str] = set()
    by_date: dict[dt.date, list] = {}
    for item in candidates:
        by_date.setdefault(item[0].ex_date, []).append(item)
    for items in by_date.values():
        items.sort(key=lambda x: (-x[2], x[0].decision_ts, x[0].event_id))
        selected.update(x[0].event_id for x in items[: int(CAPITAL // NOTIONAL)])
    out = []
    for row, verdict, edge in candidates:
        if row.event_id not in selected:
            verdict = "NO_SIGNAL"
        p1 = float(getattr(row, f"p_{rung}"))
        retained = row.gross * (1 - withholding)
        benchmark = (p1 - row.p_pre + retained) / row.p_pre
        fee_return = 2 * row.fee_rate
        slip_return = slippage_bps / 10_000
        policy = -(fee_return + slip_return) if verdict == "EXIT" else benchmark
        out.append({
            "fold": fold, "event_id": row.event_id, "symbol": row.symbol,
            "ex_date": row.ex_date.isoformat(), "decision_ts": row.decision_ts.isoformat(),
            "selected_rung": rung, "pdr_hat": estimate["pdr"], "pdr_se": estimate["se"],
            "withholding": withholding, "slippage_bps": slippage_bps,
            "verdict": verdict, "reason": "ENTITLEMENT_UNCERTAIN" if verdict == "NO_SIGNAL" else "",
            "lower_bound_edge_per_share": edge, "policy_return": policy,
            "benchmark_return": benchmark, "active_return": policy - benchmark,
            "fee_drag_return": fee_return if verdict == "EXIT" else 0.0,
            "slippage_drag_return": slip_return if verdict == "EXIT" else 0.0,
        })
    return out


def _daily(rows: list[dict], start: dt.date, end: dt.date, field: str) -> pd.Series:
    index = pd.date_range(start, end, freq="D")
    values = pd.Series(0.0, index=index)
    for row in rows:
        values[pd.Timestamp(row["ex_date"])] += NOTIONAL * row[field] / CAPITAL
    return values


def _max_drawdown(series: pd.Series) -> float:
    nav = (1 + series).cumprod()
    return float((nav / nav.cummax() - 1).min()) if len(nav) else 0.0


def _series_metrics(series: pd.Series, *, active: bool = False) -> dict:
    total = float((1 + series).prod() - 1)
    std = float(series.std(ddof=1))
    downside = float(series[series < 0].std(ddof=1))
    sharpe = None if not math.isfinite(std) or std == 0 else float(series.mean() / std * math.sqrt(365))
    sortino = None if not math.isfinite(downside) or downside == 0 else float(series.mean() / downside * math.sqrt(365))
    return {
        "total_return": total,
        "annualized_return": float((1 + total) ** (365 / len(series)) - 1) if len(series) and total > -1 else None,
        "information_ratio" if active else "sharpe": sharpe,
        "sortino": sortino,
        "maximum_drawdown": _max_drawdown(series),
    }


def _rolling_30(rows: list[dict], start: dt.date, end: dt.date) -> list[dict]:
    daily = _daily(rows, start, end, "policy_return")
    out = []
    for finish in daily.index[29:]:
        begin = finish - pd.Timedelta(days=29)
        window = daily.loc[begin:finish]
        events = [r for r in rows if begin.date() <= dt.date.fromisoformat(r["ex_date"]) <= finish.date()
                  and r["verdict"] == "EXIT"]
        std = float(window.std(ddof=1))
        if len(events) < 3 or std == 0 or not math.isfinite(std):
            out.append({"end": finish.date().isoformat(), "status": "INSUFFICIENT_EVENTS", "trade_count": len(events)})
        else:
            out.append({"end": finish.date().isoformat(), "status": "OK", "trade_count": len(events),
                        "sharpe": float(window.mean() / std * math.sqrt(365))})
    return out


def _score_period(rows: list[dict], start: dt.date, end: dt.date) -> dict:
    policy = _daily(rows, start, end, "policy_return")
    benchmark = _daily(rows, start, end, "benchmark_return")
    active = _daily(rows, start, end, "active_return")
    exits = [r for r in rows if r["verdict"] == "EXIT"]
    uncertain = [r for r in rows if r["reason"] == "ENTITLEMENT_UNCERTAIN"]
    p = _series_metrics(policy)
    p.update({
        "turnover": 2 * NOTIONAL * len(exits) / CAPITAL,
        "win_rate": (sum(r["policy_return"] > 0 for r in rows) / len(rows)) if rows else None,
        "trade_count": len(exits), "event_count": len(rows),
        "entitlement_uncertain_count": len(uncertain),
        "fee_drag": sum(NOTIONAL * r["fee_drag_return"] for r in rows) / CAPITAL,
        "slippage_drag_MODELED_EXECUTION": sum(NOTIONAL * r["slippage_drag_return"] for r in rows) / CAPITAL,
    })
    a = _series_metrics(active, active=True)
    a["win_rate"] = (sum(r["active_return"] > 0 for r in rows) / len(rows)) if rows else None
    return {"policy": p, "benchmark": _series_metrics(benchmark), "active": a,
            "rolling_30_day_sharpe": _rolling_30(rows, start, end)}


def score() -> dict:
    manifest = _verify_frozen_manifest()
    frame = _eligible_frame()
    initial = frame[frame.ex_date <= INITIAL_END]
    if len(initial) < MIN_TRAINING_EVENTS:
        raise RuntimeError(f"only {len(initial)} initial training events; need {MIN_TRAINING_EVENTS}")

    folds = [
        ("OOS_2026_08", dt.date(2026, 8, 1), dt.date(2026, 8, 31)),
        ("OOS_2026_09", dt.date(2026, 9, 1), OOS_END),
    ]
    initial_rung, initial_diag = select_rung(initial)
    initial_estimate = _estimate(initial, initial_rung)
    is_rows = _evaluate(initial, initial_rung, initial_estimate, fold="IS_INITIAL",
                        slippage_bps=BASE_SLIPPAGE_BPS, withholding=PRIMARY_WITHHOLDING, robust=True)
    oos_rows: list[dict] = []
    fold_diagnostics = []
    fold_models = []
    for name, start, end in folds:
        first_decision = pd.Timestamp(dt.datetime.combine(start, dt.time(20, 0), ET) - dt.timedelta(days=1))
        training = frame[frame.outcome_observable_ts < first_decision]
        test = frame[(frame.ex_date >= start) & (frame.ex_date <= end)]
        if len(training) < MIN_TRAINING_EVENTS:
            raise RuntimeError(f"{name}: only {len(training)} training events")
        rung, diagnostics = select_rung(training)
        estimate = _estimate(training, rung)
        fold_rows = _evaluate(test, rung, estimate, fold=name, slippage_bps=BASE_SLIPPAGE_BPS,
                              withholding=PRIMARY_WITHHOLDING, robust=True)
        oos_rows.extend(fold_rows)
        fold_models.append((name, start, end, training, test, rung, estimate))
        fold_sharpe = _score_period(fold_rows, start, end)["policy"]["sharpe"]
        fold_diagnostics.append({
            "fold": name, "training_end": max(training.ex_date).isoformat(),
            "test_period": f"{start.isoformat()}..{end.isoformat()}", "selected_rung": rung,
            "pdr_estimate": estimate["pdr"], "pdr_se": estimate["se"],
            "training_events": len(training), "test_events": len(test),
            "test_trades": sum(r["verdict"] == "EXIT" for r in fold_rows), "test_sharpe": fold_sharpe,
            "selection_diagnostics": diagnostics,
        })

    is_score = _score_period(is_rows, min(initial.ex_date), INITIAL_END)
    oos_score = _score_period(oos_rows, OOS_START, OOS_END)
    is_sharpe = is_score["policy"]["sharpe"]
    oos_sharpe = oos_score["policy"]["sharpe"]
    ratio = None if is_sharpe in (None, 0) else oos_sharpe / is_sharpe

    sensitivity = []
    for slip in SLIPPAGE_GRID:
        for withholding in WITHHOLDING_GRID:
            rows = []
            for name, start, end, training, test, rung, estimate in fold_models:
                rows += _evaluate(test, rung, estimate, fold=name, slippage_bps=slip,
                                  withholding=withholding, robust=False)
            sensitivity.append({"slippage_bps_MODELED_EXECUTION": slip, "withholding": withholding,
                                "score": _score_period(rows, OOS_START, OOS_END)})

    exclusions = Counter(pd.read_csv(KNOWLEDGE, keep_default_na=False).query("eligible_ex_ante == 'NO'").exclusion_reason)
    report = {
        "name": "walk-forward OOS performance of the Exnight selection procedure",
        "manifest_sha256": _sha256(MANIFEST),
        "labels": {"historical_execution": "MODELED_EXECUTION", "v1_oos": False},
        "sample": {"resolved_usable": 127, "eligible_ex_ante": len(frame),
                   "excluded": 127 - len(frame), "exclusion_reason_combinations": dict(exclusions)},
        "initial_model": {"selected_rung": initial_rung, "estimate": initial_estimate,
                          "selection_diagnostics": initial_diag},
        "is_initial_development_window": is_score,
        "oos_concatenated_non_overlapping_folds": oos_score,
        "oos_sharpe_over_is_sharpe": ratio,
        "oos_sharpe_decay_flag_below_0_5": ratio is not None and ratio < 0.5,
        "is_trade_count_for_ratio": is_score["policy"]["trade_count"],
        "folds": fold_diagnostics,
        "sensitivity": sensitivity,
        "notes": [
            "HOLD dividend is accrued as an entitlement receivable at T1, not represented as cash paid by T1.",
            "Unknown Bitget eligibility timing is modeled conservatively for EXIT as forfeiting retained dividend.",
            "NO_SIGNAL leaves the holder in the benchmark exposure.",
        ],
    }
    SCORECARD.write_text(json.dumps(report, indent=2, default=str) + "\n")
    _write_csv(DECISIONS, is_rows + oos_rows)
    print(json.dumps({"scorecard": str(SCORECARD.relative_to(ROOT)), "eligible": len(frame),
                      "oos_events": len(oos_rows), "oos_trades": oos_score["policy"]["trade_count"],
                      "oos_sharpe": oos_score["policy"]["sharpe"]}, indent=2))
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare or score the Alpha Factory walk-forward")
    parser.add_argument("action", choices=("prepare", "score"))
    args = parser.parse_args()
    prepare() if args.action == "prepare" else score()


if __name__ == "__main__":
    main()

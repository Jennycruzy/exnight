"""Dashboard view of V3's forward validation and the headline comparison.

Everything is read from committed result files; nothing is computed from live market data.

- `comparison`: Exnight versus always stepping out versus holding, from the walk-forward
  scorecard and `always_exit_baseline.json`.
- `v3`: each scheduled high-yield event with its latest decision made before the sell cutoff
  and, once the window has been scored, the realised outcome.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import math
from pathlib import Path
from typing import Any

from exnight import schedule


def _json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _float(value: object) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def comparison(project_root: Path) -> dict[str, Any]:
    results = project_root / "data" / "results"
    score = _json(results / "competition_scorecard.json") or {}
    exit_ = (_json(results / "always_exit_baseline.json") or {}).get("primary", {}).get("oos")
    oos = score.get("oos_concatenated_non_overlapping_folds")
    if not oos or not exit_:
        return {"status": "UNAVAILABLE"}
    manifest = _json(results / "competition_backtest_manifest.json") or {}
    return {
        "status": "AVAILABLE",
        "events": oos["policy"]["event_count"],
        "days": manifest.get("oos_calendar_days"),
        "rows": [
            {"name": "Exnight", "trades": oos["policy"]["trade_count"], "active_bps_per_event": 0.0,
             "beat_hold_share": None, "total_return": oos["policy"]["total_return"],
             "sharpe": oos["policy"]["sharpe"]},
            {"name": "Always step out", "trades": exit_["score"]["policy"]["trade_count"],
             "active_bps_per_event": exit_["mean_active_bps"], "beat_hold_share": exit_["share_exit_beat_hold"],
             "total_return": exit_["score"]["policy"]["total_return"], "sharpe": exit_["score"]["policy"]["sharpe"]},
            {"name": "Hold", "trades": 0, "active_bps_per_event": None, "beat_hold_share": None,
             "total_return": oos["benchmark"]["total_return"], "sharpe": oos["benchmark"]["sharpe"]},
        ],
    }


def _decision_files(results: Path) -> list[Path]:
    files = sorted(results.glob("signals_v3_*.csv"))
    plain = results / "signals_v3.csv"
    return files + ([plain] if plain.is_file() else [])


def _latest_decisions(results: Path, cutoffs: dict[str, dt.datetime]) -> dict[str, dict[str, Any]]:
    """Per event, the $1k row of the latest decision file decided before that event's cutoff."""
    best: dict[str, tuple[dt.datetime, dict[str, Any], str]] = {}
    for path in _decision_files(results):
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                event = row.get("event_id", "")
                if event not in cutoffs or row.get("notional_usd") not in ("1000", "1000.0"):
                    continue
                try:
                    decided = dt.datetime.fromisoformat(row["decided_at"])
                except (KeyError, ValueError):
                    continue
                if decided < cutoffs[event] and (event not in best or decided > best[event][0]):
                    best[event] = (decided, row, path.name)
    return {event: {**row, "decision_file": name} for event, (_, row, name) in best.items()}


def v3(project_root: Path) -> dict[str, Any]:
    results = project_root / "data" / "results"
    try:
        plan = schedule.load(project_root / "data" / "forward")
    except (OSError, ValueError, json.JSONDecodeError):
        return {"status": "UNAVAILABLE"}
    group_of = {event: g for g in plan["groups"] for event in g["event_ids"]}
    cutoffs = {event: dt.datetime.fromisoformat(g["sell_cutoff"]) for event, g in group_of.items()}
    decisions = _latest_decisions(results, cutoffs)
    events = []
    for target in plan["targets"]:
        event = target["event_id"]
        group = group_of[event]
        row = decisions.get(event, {})
        score = _json(results / f"forward_score_{group['label']}.json")
        realised = next((r for r in (score or {}).get("results", []) if r.get("event_id") == event), None)
        first = (realised or {}).get("notionals", [{}])[0] if realised else {}
        events.append({
            "event_id": event, "symbol": target["symbol"], "ex_date": target["ex_date"], "round": target["round"],
            "sell_cutoff": group["sell_cutoff"], "gross_dividend": target["gross_dividend"],
            "gross_yield_bp": target["gross_yield_bp"],
            "verdict": row.get("verdict") or "PENDING",
            "reason": row.get("reason") or ("" if row else "no decision frozen before the cutoff yet"),
            "entitlement_tier": row.get("entitlement_tier"),
            "breakeven_yield_bp": _float(row.get("breakeven_yield_bp")),
            "decided_at": row.get("decided_at"), "decision_file": row.get("decision_file"),
            "score_status": (score or {}).get("status", "NOT_SCORED"),
            "realised_pdr": _float((realised or {}).get("realised_pdr")),
            "price_discovery": (realised or {}).get("price_discovery"),
            "overnight_last_price_changes": (realised or {}).get("overnight_last_price_changes"),
            "realised_verdict": first.get("realised_verdict"),
            "realised_edge_keep_70pct": _float(first.get("realised_edge_keep_70pct")),
            "modeled_verdict": ((realised or {}).get("modeled") or {}).get("realised_verdict"),
            "modeled_edge_keep_gross": _float(((realised or {}).get("modeled") or {}).get("edge_keep_gross")),
            "modeled_edge_keep_70pct": _float(((realised or {}).get("modeled") or {}).get("edge_keep_70pct")),
        })
    first_row = next(iter(decisions.values()), {})
    return {
        "status": "AVAILABLE", "rule_id": plan.get("rule_id"),
        "min_gross_yield_bp": plan.get("min_gross_yield_bp"),
        "lower_ratio": _float(first_row.get("lower_ratio")),
        "pdr_hat": _float(first_row.get("pdr_hat")), "pdr_se": _float(first_row.get("pdr_se")),
        "scored": sum(e["score_status"] != "NOT_SCORED" for e in events),
        "rounds": plan["rounds"],
        "events": events,
    }


# The one real position: 0.2783 rTOWN bought 23 Sep and held through the 25 Sep ex-date.
RTOWN_SHARES = 0.2783
RTOWN_GROSS_PER_SHARE = 0.28
RTOWN_PAY_TIME = "2026-10-08T16:00:00+00:00"   # Bitget's dividend record (dividendDate)


def dividend(project_root: Path) -> dict[str, Any]:
    """Status of the rTOWN dividend owed to the live position, from committed checker output."""
    paper = project_root / "data" / "raw" / "paper"
    gross = round(RTOWN_SHARES * RTOWN_GROSS_PER_SHARE, 6)
    out = {"symbol": "rTOWN", "shares": RTOWN_SHARES, "gross_per_share": RTOWN_GROSS_PER_SHARE,
           "owed_gross_usdt": gross, "owed_after_30pct_usdt": round(gross * 0.7, 6), "due_at": RTOWN_PAY_TIME,
           "status": "WAITING", "last_checked": None}
    credits = sorted(paper.glob("*_rTOWN_position/07_credit.json"))
    if credits:
        credit = _json(credits[-1]) or {}
        paid = _float(credit.get("credited_usdt"))
        out |= {"status": "PAID", "credited_usdt": paid, "credited_at": credit.get("detected_at"),
                "evidence": credits[-1].parent.relative_to(project_root).as_posix(),
                "withheld_share": None if paid is None else round(1 - paid / gross, 4)}
        return out
    log = paper / "dividend_check.log"
    try:
        last = [line for line in log.read_text(encoding="utf-8").splitlines() if " not yet:" in line][-1]
        out["last_checked"] = last.split(" ", 1)[0]
    except (OSError, IndexError):
        pass
    return out

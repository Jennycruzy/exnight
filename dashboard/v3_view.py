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
    plan = _json(project_root / "data" / "forward" / "v3_schedule.json")
    if not plan:
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
            "event_id": event, "symbol": target["symbol"], "ex_date": target["ex_date"],
            "sell_cutoff": group["sell_cutoff"], "gross_dividend": target["gross_dividend"],
            "gross_yield_bp": target["gross_yield_bp"],
            "verdict": row.get("verdict") or "PENDING",
            "reason": row.get("reason") or ("" if row else "no decision frozen before the cutoff yet"),
            "entitlement_tier": row.get("entitlement_tier"),
            "breakeven_yield_bp": _float(row.get("breakeven_yield_bp")),
            "decided_at": row.get("decided_at"), "decision_file": row.get("decision_file"),
            "score_status": (score or {}).get("status", "NOT_SCORED"),
            "realised_pdr": _float((realised or {}).get("realised_pdr")),
            "realised_verdict": first.get("realised_verdict"),
            "realised_edge_keep_70pct": _float(first.get("realised_edge_keep_70pct")),
        })
    first_row = next(iter(decisions.values()), {})
    return {
        "status": "AVAILABLE", "rule_id": plan.get("rule_id"),
        "min_gross_yield_bp": plan.get("min_gross_yield_bp"),
        "lower_ratio": _float(first_row.get("lower_ratio")),
        "pdr_hat": _float(first_row.get("pdr_hat")), "pdr_se": _float(first_row.get("pdr_se")),
        "scored": sum(e["score_status"] != "NOT_SCORED" for e in events),
        "events": events,
    }

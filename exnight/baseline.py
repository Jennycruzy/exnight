"""Always-EXIT comparison for the frozen walk-forward scorecard.

Added on 2026-09-23, after the OOS results were known. It changes no frozen parameter,
decision or input: it reads the frozen decisions and the same eligible event frame, and asks
what a holder would have earned by stepping out of *every* event instead of following the
rule. Costs, T0/T1, notional, capital base and metrics are the scorecard's own
(`exnight.competition`), so the two are directly comparable.

Per event, with withholding w and round-trip slippage s:

    HOLD   = (P1 - P0 + gross * (1 - w)) / P0
    EXIT   = -(2 * taker_fee + s)
    active = EXIT - HOLD
"""
from __future__ import annotations

import json

import pandas as pd

from . import competition

OUTPUT = competition.RESULTS / "always_exit_baseline.json"
LABEL = "ADDED_AFTER_OOS_RESULTS_COMPARISON_NOT_A_STRATEGY_CHANGE"


def _rows(decisions: pd.DataFrame, frame: pd.DataFrame, *, slippage_bps: int, withholding: float) -> list[dict]:
    events = frame.set_index("event_id")
    rows = []
    for d in decisions.itertuples(index=False):
        e = events.loc[d.event_id]
        p1 = float(e[f"p_{d.selected_rung}"])
        hold = (p1 - e.p_pre + e.gross * (1 - withholding)) / e.p_pre
        fee, slip = 2 * e.fee_rate, slippage_bps / 10_000
        policy = -(fee + slip)
        rows.append(dict(fold=d.fold, event_id=d.event_id, ex_date=d.ex_date, verdict="EXIT", reason="",
                         policy_return=policy, benchmark_return=hold, active_return=policy - hold,
                         fee_drag_return=fee, slippage_drag_return=slip))
    return rows


def _summary(rows: list[dict], start, end) -> dict:
    active = pd.Series([r["active_return"] for r in rows])
    return dict(events=len(rows), mean_active_bps=float(1e4 * active.mean()),
                share_exit_beat_hold=float((active > 0).mean()),
                score=competition._score_period(rows, start, end))


def build() -> dict:
    frame = competition._eligible_frame()
    decisions = pd.read_csv(competition.DECISIONS)
    base = decisions[(decisions.slippage_bps == competition.BASE_SLIPPAGE_BPS)
                     & (decisions.withholding == competition.PRIMARY_WITHHOLDING)]
    oos = base[base.fold.str.startswith("OOS_")]
    initial = base[base.fold == "IS_INITIAL"]
    is_start = min(pd.to_datetime(initial.ex_date)).date()
    report = dict(
        label=LABEL,
        definition="step out of every eligible event at T0 and back in at T1; same costs, T0/T1, notional and metrics as the scorecard",
        primary=dict(slippage_bps=competition.BASE_SLIPPAGE_BPS, withholding=competition.PRIMARY_WITHHOLDING,
                     oos=_summary(_rows(oos, frame, slippage_bps=competition.BASE_SLIPPAGE_BPS,
                                        withholding=competition.PRIMARY_WITHHOLDING),
                                  competition.OOS_START, competition.OOS_END),
                     is_initial=_summary(_rows(initial, frame, slippage_bps=competition.BASE_SLIPPAGE_BPS,
                                               withholding=competition.PRIMARY_WITHHOLDING),
                                         is_start, competition.INITIAL_END)),
        sensitivity=[],
    )
    for slip in competition.SLIPPAGE_GRID:
        for w in competition.WITHHOLDING_GRID:
            s = _summary(_rows(oos, frame, slippage_bps=slip, withholding=w), competition.OOS_START, competition.OOS_END)
            report["sensitivity"].append(dict(slippage_bps=slip, withholding=w, mean_active_bps=s["mean_active_bps"],
                                              share_exit_beat_hold=s["share_exit_beat_hold"],
                                              active_total_return=s["score"]["active"]["total_return"]))
    OUTPUT.write_text(json.dumps(report, indent=2, default=str) + "\n")
    return report

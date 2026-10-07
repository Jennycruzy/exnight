"""One backtest record in the form the Alpha Factory judges score.

Added on 2026-10-07, after every result below was known. It changes no frozen parameter,
decision or input: it reads the frozen walk-forward decisions (`exnight.competition`), the
always-EXIT comparison (`exnight.baseline`) and the scored live windows, and reports them with
the judging metrics: Sharpe, Sortino, max drawdown, turnover, OOS/IS Sharpe decay and rolling
30-day Sharpe.

Three views, never merged:

* ``policy``: the rule as traded. It stepped out of nothing, so it equals holding.
* ``vs_always_exit``: the rule's value against the obvious alternative it replaces, stepping
  out of every event. Daily return = rule return - always-EXIT return, on the scorecard's own
  $1k-per-event / $25k capital base, costs and T0/T1.
* ``live``: the 16 pre-registered live events, scored per event (modeled execution).
"""
from __future__ import annotations

import csv
import datetime as dt
import json
from pathlib import Path

import pandas as pd

from . import baseline, competition as c

ROOT = c.ROOT
REPORTS = ROOT / "reports"
OUTPUT = REPORTS / "backtest.json"
MARKDOWN = REPORTS / "backtest.md"
DAILY = REPORTS / "backtest_daily.csv"
EVENTS = REPORTS / "backtest_events.csv"
LABEL = "ADDED_AFTER_OOS_RESULTS_REPORTING_ONLY"
DECAY_ALERT = 0.5


def _frozen_rows() -> tuple[pd.DataFrame, pd.DataFrame]:
    decisions = pd.read_csv(c.DECISIONS)
    return c._eligible_frame(), decisions


def _spread_rows(decisions: pd.DataFrame, frame: pd.DataFrame, *, slippage_bps: int, withholding: float) -> list[dict]:
    """Rule minus always-EXIT, per event, in the scorecard's row format.

    Verdicts are the frozen primary-case decisions; returns are recomputed at the given
    slippage and withholding, so the sensitivity grid never re-decides an event.
    """
    base = decisions[(decisions.slippage_bps == c.BASE_SLIPPAGE_BPS) & (decisions.withholding == c.PRIMARY_WITHHOLDING)]
    verdicts = base.set_index("event_id").verdict
    rows = []
    for r in baseline._rows(base, frame, slippage_bps=slippage_bps, withholding=withholding):
        verdict = verdicts.loc[r["event_id"]]
        exit_return, hold_return = r["policy_return"], r["benchmark_return"]
        rule_return = exit_return if verdict == "EXIT" else hold_return
        rows.append(dict(r, verdict="EXIT", reason="", rule_verdict=verdict,
                         rule_return=rule_return, hold_return=hold_return, always_exit_return=exit_return,
                         policy_return=rule_return - exit_return, benchmark_return=exit_return,
                         active_return=rule_return - exit_return))
    return rows


def _decay(is_sharpe, oos_sharpe) -> dict:
    if is_sharpe is None or oos_sharpe is None or is_sharpe <= 0:
        return {"ratio": None, "alert": None, "note": "undefined: in-sample Sharpe is not positive"}
    ratio = oos_sharpe / is_sharpe
    return {"ratio": ratio, "alert": ratio < DECAY_ALERT, "note": f"alert when OOS < {DECAY_ALERT} x IS"}


def _rolling_summary(rolling: list[dict]) -> dict:
    ok = [w["sharpe"] for w in rolling if w["status"] == "OK"]
    return {"windows": len(rolling), "scored": len(ok),
            "positive": sum(s > 0 for s in ok),
            "min": min(ok) if ok else None, "max": max(ok) if ok else None,
            "series": rolling}


def _periods(decisions: pd.DataFrame) -> dict:
    initial = decisions[decisions.fold == "IS_INITIAL"]
    return {"IS": (min(pd.to_datetime(initial.ex_date)).date(), c.INITIAL_END, ["IS_INITIAL"]),
            "OOS": (c.OOS_START, c.OOS_END, sorted(f for f in decisions.fold.unique() if f.startswith("OOS_")))}


def _view(rows: list[dict], periods: dict, *, comparison: bool = False) -> dict:
    out = {}
    for name, (start, end, folds) in periods.items():
        sub = [r for r in rows if r["fold"] in folds]
        score = c._score_period(sub, start, end)
        metrics = score["policy"]
        if comparison:
            # The rule itself never trades; these counts belong to the always-EXIT comparator.
            metrics["comparator_trade_count"] = metrics.pop("trade_count")
            metrics["comparator_turnover"] = metrics.pop("turnover")
            for key in ("fee_drag", "slippage_drag_MODELED_EXECUTION"):
                metrics["comparator_" + key] = metrics.pop(key)
        out[name] = {"start": start.isoformat(), "end": end.isoformat(), "days": (end - start).days + 1,
                     "events": len(sub), "metrics": metrics,
                     "rolling_30_day_sharpe": _rolling_summary(score["rolling_30_day_sharpe"])}
    out["oos_over_is_sharpe"] = _decay(out["IS"]["metrics"]["sharpe"], out["OOS"]["metrics"]["sharpe"])
    return out


def _symbol(event_id: str) -> str:
    return event_id.split("-")[0]


def _per_event(rows: list[dict]) -> dict:
    gaps = pd.Series([1e4 * r["policy_return"] for r in rows])
    n, mean = len(gaps), float(gaps.mean())
    std = float(gaps.std(ddof=1)) if n > 1 else None
    return {"events": n, "mean_bps": mean, "std_bps": std, "t_stat": mean / std * n ** 0.5 if std else None,
            "positive": int((gaps > 0).sum()), "worst_bps": float(gaps.min())}


def _concentration(rows: list[dict], period: tuple) -> dict:
    start, end, folds = period
    sub = [r for r in rows if r["fold"] in folds]
    symbols = sorted({_symbol(r["event_id"]) for r in sub})
    by_symbol = {sym: _per_event([r for r in sub if _symbol(r["event_id"]) == sym]) for sym in symbols}
    leave_one_out = {}
    for sym in symbols:
        rest = [r for r in sub if _symbol(r["event_id"]) != sym]
        if rest:
            leave_one_out[sym] = dict(_per_event(rest),
                                      sharpe=c._score_period(rest, start, end)["policy"]["sharpe"])
    return {"symbols": len(symbols), "by_symbol": by_symbol, "leave_one_symbol_out": leave_one_out}


def _live() -> dict:
    events = []
    for path in sorted(c.RESULTS.glob("forward_score_v3_*.json")):
        for e in json.loads(path.read_text())["results"]:
            modeled = e.get("modeled") or {}
            edge = modeled.get("edge_keep_70pct")
            pre = e.get("pre_price")
            events.append({
                "event_id": e["event_id"], "ex_date": e["ex_date"], "price_discovery": e.get("price_discovery"),
                "realised_pdr": e.get("realised_pdr"),
                "frozen_verdict_1k": next((n["frozen_verdict"] for n in e["notionals"] if n["notional_usd"] == 1000), None),
                "exit_minus_hold_bps": None if edge is None or not pre else 1e4 * edge / pre,
            })
    scored = [e for e in events if e["exit_minus_hold_bps"] is not None]
    priced = [e for e in scored if e["price_discovery"] == "PRICED"]

    def summary(items):
        return {"events": len(items), "hold_beat_exit": sum(e["exit_minus_hold_bps"] < 0 for e in items),
                "mean_hold_minus_exit_bps": (sum(-e["exit_minus_hold_bps"] for e in items) / len(items)) if items else None}

    return {"label": "MODELED_EXECUTION", "scheduled": 16, "graded": len(events),
            "all": summary(scored), "priced_overnight": summary(priced), "events": events}


def build() -> dict:
    frame, decisions = _frozen_rows()
    periods = _periods(decisions)
    primary = decisions[(decisions.slippage_bps == c.BASE_SLIPPAGE_BPS) & (decisions.withholding == c.PRIMARY_WITHHOLDING)]
    policy_rows = primary.to_dict("records")
    spread = _spread_rows(decisions, frame, slippage_bps=c.BASE_SLIPPAGE_BPS, withholding=c.PRIMARY_WITHHOLDING)
    sensitivity = []
    for slip in c.SLIPPAGE_GRID:
        for w in c.WITHHOLDING_GRID:
            rows = _spread_rows(decisions, frame, slippage_bps=slip, withholding=w)
            oos_rows = [r for r in rows if r["fold"] in periods["OOS"][2]]
            oos = c._score_period(oos_rows, *periods["OOS"][:2])["policy"]
            sensitivity.append({"slippage_bps": slip, "withholding": w, "oos_sharpe": oos["sharpe"],
                                "oos_sortino": oos["sortino"], "oos_total_return": oos["total_return"],
                                "oos_mean_bps_per_event": 1e4 * sum(r["policy_return"] for r in oos_rows) / len(oos_rows)})
    is_start, oos_end = periods["IS"][0], periods["OOS"][1]
    report = {
        "label": LABEL,
        "window": {"start": is_start.isoformat(), "end": oos_end.isoformat(),
                   "total_days": (oos_end - is_start).days + 1,
                   "oos_days": (c.OOS_END - c.OOS_START).days + 1,
                   "requirement": "total >= 60 days, out-of-sample >= 30 days"},
        "capital": {"notional_per_event_usd": c.NOTIONAL, "capital_base_usd": c.CAPITAL,
                    "taker_fee_each_side": "per-event Bitget fee in the frame",
                    "slippage_bps_round_trip": c.BASE_SLIPPAGE_BPS, "withholding": c.PRIMARY_WITHHOLDING,
                    "execution": "MODELED_EXECUTION", "annualisation": "daily series, sqrt(365)"},
        "policy": _view(policy_rows, periods),
        "vs_always_exit": _view(spread, periods, comparison=True),
        "vs_always_exit_sensitivity_oos": sensitivity,
        "live": _live(),
    }
    oos = [r for r in spread if r["fold"] in periods["OOS"][2]]
    report["vs_always_exit_per_event"] = {name: _per_event([r for r in spread if r["fold"] in period[2]])
                                         for name, period in periods.items()}
    report["vs_always_exit_oos_concentration"] = _concentration(spread, periods["OOS"])
    report["vs_always_exit_oos_decomposition"] = {
        "cost_bps": 1e4 * sum(r["fee_drag_return"] + r["slippage_drag_return"] for r in oos) / len(oos),
        "hold_bps": 1e4 * sum(r["hold_return"] for r in oos) / len(oos),
        "gap_bps": 1e4 * sum(r["policy_return"] for r in oos) / len(oos),
        "book_bps_per_30_days": 1e4 * report["vs_always_exit"]["OOS"]["metrics"]["total_return"]
                                * 30 / report["vs_always_exit"]["OOS"]["days"],
    }
    REPORTS.mkdir(exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2, default=str, allow_nan=False) + "\n")
    _write_daily(policy_rows, spread, is_start, oos_end)
    _write_events(spread)
    MARKDOWN.write_text(render_markdown(report))
    return report


def _pct(value) -> str:
    return "n/a" if value is None else f"{100 * value:.3f}%"


def _num(value) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def _rows_for(view: dict, rule_trades: bool) -> list[str]:
    i, o = view["IS"], view["OOS"]
    mi, mo = i["metrics"], o["metrics"]
    ri, ro = i["rolling_30_day_sharpe"], o["rolling_30_day_sharpe"]
    decay = view["oos_over_is_sharpe"]
    trades = (lambda m: str(m["trade_count"])) if rule_trades else (lambda m: f"0 (comparator: {m['comparator_trade_count']})")
    turnover = (lambda m: _num(m["turnover"])) if rule_trades else (lambda m: f"0 (comparator: {_num(m['comparator_turnover'])})")

    def rolling(r):
        return f"{r['positive']} of {r['scored']} windows positive" if r["scored"] else "too few trades to score"

    return [
        f"| Window | {i['start']} to {i['end']} ({i['days']} days) | {o['start']} to {o['end']} ({o['days']} days) |",
        f"| Events | {i['events']} | {o['events']} |",
        f"| Total return | {_pct(mi['total_return'])} | {_pct(mo['total_return'])} |",
        f"| Annualised return | {_pct(mi['annualized_return'])} | {_pct(mo['annualized_return'])} |",
        f"| Sharpe | {_num(mi['sharpe'])} | {_num(mo['sharpe'])} |",
        f"| Sortino | {_num(mi['sortino'])} | {_num(mo['sortino'])} |",
        f"| Max drawdown | {_pct(mi['maximum_drawdown'])} | {_pct(mo['maximum_drawdown'])} |",
        f"| Win rate (events) | {100 * mi['win_rate']:.0f}% | {100 * mo['win_rate']:.0f}% |",
        f"| Trades | {trades(mi)} | {trades(mo)} |",
        f"| Turnover (x capital) | {turnover(mi)} | {turnover(mo)} |",
        f"| Rolling 30-day Sharpe | {rolling(ri)} | {rolling(ro)} |",
        f"| OOS / IS Sharpe | | {_num(decay['ratio'])} ({decay['note']}) |",
    ]


def render_markdown(report: dict) -> str:
    w, cap, live = report["window"], report["capital"], report["live"]
    head = "| | In-sample | Out-of-sample |\n|---|---:|---:|"
    kind = min(report["vs_always_exit_sensitivity_oos"], key=lambda s: s["oos_mean_bps_per_event"])
    gap = report["vs_always_exit_oos_decomposition"]
    conc = report["vs_always_exit_oos_concentration"]
    top = max(conc["by_symbol"], key=lambda sym: conc["by_symbol"][sym]["events"])
    lines = [
        "# Exnight backtest record",
        "",
        "Generated by `python scripts/run_backtest.py`. Machine-readable copy: `reports/backtest.json`;",
        "daily returns: `reports/backtest_daily.csv`; per event: `reports/backtest_events.csv`.",
        "",
        f"- Total window **{w['start']} to {w['end']} ({w['total_days']} days)**, out-of-sample "
        f"**{w['oos_days']} days** (requirement: {w['requirement']}).",
        "- Walk-forward: the rule is fitted on events before each fold and frozen; out-of-sample is two",
        "  non-overlapping folds (August, 1 to 16 September). Only dividend facts public at decision time",
        "  are used (`docs/competition_methodology.md`).",
        f"- ${cap['notional_per_event_usd']:,.0f} per event on a ${cap['capital_base_usd']:,.0f} base; Bitget taker fee "
        f"on both legs plus {cap['slippage_bps_round_trip']} bps round-trip slippage (modeled execution); "
        f"Sharpe and Sortino from the daily series, annualised with sqrt(365).",
        "",
        "## 1. Exnight against always selling first",
        "",
        "The decision Exnight makes is whether a holder should sell before the ex-date and buy back after.",
        "The obvious strategy is to always do it. Each day's return below is Exnight's return minus that",
        "strategy's return, on the same events, prices, costs and capital.",
        "",
        head, *_rows_for(report["vs_always_exit"], rule_trades=False),
        "",
        f"Out-of-sample sensitivity: the gap stays positive in all {len(report['vs_always_exit_sensitivity_oos'])} "
        f"slippage x withholding cases. In the case kindest to stepping out ({kind['slippage_bps']} bps slippage, "
        f"{100 * kind['withholding']:.0f}% withholding) Exnight is still {kind['oos_mean_bps_per_event']:.1f} bps per event ahead, "
        f"Sharpe {_num(kind['oos_sharpe'])}.",
        "",
        f"Where the gap comes from, out-of-sample: stepping out costs {gap['cost_bps']:.1f} bps per event in fees and",
        f"slippage, while holding through the ex-date returned {gap['hold_bps']:.1f} bps per event on average. The gap is",
        "cost avoidance, not a price forecast. In dollars it is small: about "
        f"{gap['book_bps_per_30_days']:.0f} bps of the ${cap['capital_base_usd']:,.0f} book per 30 days at "
        f"${cap['notional_per_event_usd']:,.0f} per event. The Sharpe is high because the gap has the same sign on most",
        "nights, not because it is large.",
        "",
        "Per event, without annualising:",
        "",
        "| | Events | Mean, bps | Std, bps | t-stat | Exnight ahead | Worst, bps |",
        "|---|---:|---:|---:|---:|---:|---:|",
        *[f"| {name} | {v['events']} | {v['mean_bps']:.1f} | {"n/a" if v['std_bps'] is None else f"{v['std_bps']:.1f}"} | {_num(v['t_stat'])} | "
          f"{v['positive']} of {v['events']} | {v['worst_bps']:.1f} |"
          for name, v in report["vs_always_exit_per_event"].items()],
        "",
        f"**Concentration.** Out-of-sample events come from {conc['symbols']} symbols, and "
        f"{top} supplies {conc['by_symbol'][top]['events']} of {report['vs_always_exit_per_event']['OOS']['events']}. "
        "Only events with a gross dividend declared before the decision qualify, and frequent payers "
        "dominate that set. The result with each symbol removed in turn:",
        "",
        "| Symbol | Its events | Its mean, bps | Without it: events | mean, bps | t-stat | Sharpe |",
        "|---|---:|---:|---:|---:|---:|---:|",
        *[f"| {sym} | {conc['by_symbol'][sym]['events']} | {conc['by_symbol'][sym]['mean_bps']:.1f} | "
          f"{v['events']} | {v['mean_bps']:.1f} | {_num(v['t_stat'])} | {_num(v['sharpe'])} |"
          for sym, v in conc["leave_one_symbol_out"].items()],
        "",
        f"Without {top} the gap is still positive ({conc['leave_one_symbol_out'][top]['mean_bps']:.1f} bps per event), but "
        f"{conc['leave_one_symbol_out'][top]['events']} events are too few to be conclusive "
        f"(t-stat {_num(conc['leave_one_symbol_out'][top]['t_stat'])}). The live test below adds 16 different, high-dividend events.",
        "",
        "## 2. Exnight as traded",
        "",
        "Exnight never found an event where stepping out cleared its costs, so it held every time.",
        "Its return is the holder's return: the overnight price move plus the dividend kept.",
        "",
        head, *_rows_for(report["policy"], rule_trades=True),
        "",
        "## 3. Live test (pre-registered, after the backtest)",
        "",
        f"{live['graded']} of {live['scheduled']} high-dividend events graded so far, each decision committed to Git "
        "before the 20:00 ET cutoff. Per event, holding minus stepping out (modeled execution, 70% of the dividend kept):",
        "",
        "| Events | Holding beat stepping out | Mean, bps per event |",
        "|---|---:|---:|",
        f"| All graded | {live['all']['hold_beat_exit']} of {live['all']['events']} | {_num(live['all']['mean_hold_minus_exit_bps'])} |",
        f"| Price moved overnight (PRICED) | {live['priced_overnight']['hold_beat_exit']} of {live['priced_overnight']['events']} "
        f"| {_num(live['priced_overnight']['mean_hold_minus_exit_bps'])} |",
        "",
        "On nights with no overnight trades the price cannot drop, so holding wins by construction;",
        "the PRICED row is the fair test and it is close to even.",
        "",
    ]
    return "\n".join(lines)


def _write_daily(policy_rows: list[dict], spread: list[dict], start: dt.date, end: dt.date) -> None:
    columns = {
        "rule": c._daily(policy_rows, start, end, "policy_return"),
        "hold": c._daily(policy_rows, start, end, "benchmark_return"),
        "always_exit": c._daily(spread, start, end, "always_exit_return"),
        "rule_minus_always_exit": c._daily(spread, start, end, "policy_return"),
    }
    frame = pd.DataFrame(columns)
    frame.index.name = "date"
    frame.index = frame.index.date
    frame.to_csv(DAILY, float_format="%.8f", index_label="date")


def _write_events(spread: list[dict]) -> None:
    fields = ["fold", "event_id", "ex_date", "rule_verdict", "rule_return", "hold_return", "always_exit_return",
              "rule_minus_always_exit", "fee_drag_return", "slippage_drag_return"]
    with EVENTS.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in sorted(spread, key=lambda r: (r["ex_date"], r["event_id"])):
            writer.writerow({**row, "rule_minus_always_exit": row["policy_return"]})


def main() -> None:
    report = build()
    print(json.dumps({k: report[k] for k in ("window",)}, indent=1))


if __name__ == "__main__":
    main()

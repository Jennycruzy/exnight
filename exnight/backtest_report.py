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
RUN_RECORDS = REPORTS / "run_records.md"
LIVE_ORDER = ROOT / "data" / "raw" / "paper" / "20260923T182547.240457Z"
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


def _full_sample(slippage_bps: int = c.BASE_SLIPPAGE_BPS, withholding: float = c.PRIMARY_WITHHOLDING) -> dict:
    """Every resolved cash event, including those the scorecard excludes for declaration timing.

    For an excluded event Exnight has no gross dividend before the cutoff, so its output is
    NO_SIGNAL and the holder holds; the gap is therefore hold minus always-EXIT, measured at the
    rung the walk-forward chose for that period. Labelled post hoc; the frozen scorecard is untouched.
    """
    knowledge = pd.read_csv(c.KNOWLEDGE, keep_default_na=False)
    eligible = set(knowledge.loc[knowledge.eligible_ex_ante == "YES", "event_id"])
    timing_only = set(knowledge.loc[(knowledge.eligible_ex_ante == "NO")
                                    & (knowledge.exclusion_reason == "NO_PRE_DECISION_GROSS_DECLARATION"), "event_id"])
    score = json.loads(c.SCORECARD.read_text())
    folds = [(*f["test_period"].split(".."), f["selected_rung"]) for f in score["folds"]]

    def rung(ex_date: str) -> str:
        return next((r for start, end, r in folds if start <= ex_date <= end), score["initial_model"]["selected_rung"])

    rows = []
    for r in json.loads(c.EVENT_RESULTS.read_text()):
        if r["event_id"] not in eligible | timing_only:
            continue
        p1 = (r["p_post"] or {}).get(rung(r["ex_date"]))
        if p1 is None or not r["p_pre"]:
            continue
        p0 = float(r["p_pre"])
        hold = (float(p1) - p0 + float(r["gross_dividend"]) * (1 - withholding)) / p0
        cost = 2 * float(r["fee_rate"]) + slippage_bps / 10_000
        rows.append({"event_id": r["event_id"], "symbol": r["symbol"], "ex_date": r["ex_date"],
                     "in_scorecard": r["event_id"] in eligible, "policy_return": hold + cost})

    def summary(items: list[dict]) -> dict:
        per_symbol = pd.Series({sym: sum(i["policy_return"] for i in items if i["symbol"] == sym)
                                / sum(i["symbol"] == sym for i in items) for sym in {i["symbol"] for i in items}})
        return dict(_per_event(items), symbols=len(per_symbol), symbols_ahead=int((per_symbol > 0).sum()))

    cuts = {
        "all": rows,
        "all_without_top_symbol": [r for r in rows if r["symbol"] != "rSATA"],
        "oos_period": [r for r in rows if r["ex_date"] >= c.OOS_START.isoformat()],
        "oos_period_without_top_symbol": [r for r in rows if r["ex_date"] >= c.OOS_START.isoformat() and r["symbol"] != "rSATA"],
        "excluded_from_scorecard": [r for r in rows if not r["in_scorecard"]],
    }
    return {"label": "POST_HOC_ROBUSTNESS_NOT_THE_FROZEN_SCORECARD", "top_symbol": "rSATA",
            "excluded_events_verdict": "NO_SIGNAL (no gross dividend declared before the cutoff), so the holder holds",
            **{name: summary(items) for name, items in cuts.items()}}


YIELD_BUCKETS = ((0, 25), (25, 50), (50, 100), (100, 150), (150, 10_000))
HIGH_YIELD_BPS = 100


def _counterfactual(slippage_bps: int = c.BASE_SLIPPAGE_BPS) -> dict:
    """Would stepping out have paid if the rule had traded? Realised EXIT minus HOLD per event,
    by dividend yield, for a holder who keeps the whole dividend and for one who keeps 70%.

    Same events, prices, rungs and costs as the full-sample check. Post hoc: it changes no rule,
    and it is not a strategy. It shows whether a less cautious rule had anything to find.
    """
    knowledge = pd.read_csv(c.KNOWLEDGE, keep_default_na=False)
    keep = set(knowledge.loc[(knowledge.eligible_ex_ante == "YES")
                             | (knowledge.exclusion_reason == "NO_PRE_DECISION_GROSS_DECLARATION"), "event_id"])
    score = json.loads(c.SCORECARD.read_text())
    folds = [(*f["test_period"].split(".."), f["selected_rung"]) for f in score["folds"]]
    events = []
    for r in json.loads(c.EVENT_RESULTS.read_text()):
        if r["event_id"] not in keep:
            continue
        rung = next((x for start, end, x in folds if start <= r["ex_date"] <= end), score["initial_model"]["selected_rung"])
        p1 = (r["p_post"] or {}).get(rung)
        if p1 is None or not r["p_pre"]:
            continue
        p0, gross = float(r["p_pre"]), float(r["gross_dividend"])
        yield_bps = 1e4 * gross / p0
        drop_bps = 1e4 * (p0 - float(p1)) / p0
        cost_bps = 1e4 * 2 * float(r["fee_rate"]) + slippage_bps
        events.append({"event_id": r["event_id"], "symbol": r["symbol"], "ex_date": r["ex_date"],
                       "yield_bps": yield_bps, "drop_over_dividend": drop_bps / yield_bps if yield_bps else None,
                       "cost_bps": cost_bps,
                       "exit_minus_hold_keep_100": drop_bps - yield_bps - cost_bps,
                       "exit_minus_hold_keep_70": drop_bps - 0.7 * yield_bps - cost_bps})

    def bucket(items: list[dict], key: str) -> dict:
        values = pd.Series([e[key] for e in items], dtype=float)
        std = float(values.std(ddof=1)) if len(items) > 1 else None
        return {"events": len(items), "mean_bps": float(values.mean()) if len(items) else None,
                "median_bps": float(values.median()) if len(items) else None,
                "t_stat": float(values.mean()) / std * len(items) ** 0.5 if std else None,
                "exit_won": int((values > 0).sum())}

    buckets = []
    for low, high in YIELD_BUCKETS:
        items = [e for e in events if low <= e["yield_bps"] < high]
        buckets.append({"yield_bps": [low, high], "keep_100": bucket(items, "exit_minus_hold_keep_100"),
                        "keep_70": bucket(items, "exit_minus_hold_keep_70")})
    high = sorted((e for e in events if e["yield_bps"] >= HIGH_YIELD_BPS), key=lambda e: (e["ex_date"], e["event_id"]))
    return {"label": "POST_HOC_COUNTERFACTUAL_NOT_A_STRATEGY", "events": len(events), "buckets": buckets,
            "high_yield_threshold_bps": HIGH_YIELD_BPS, "high_yield": high,
            "high_yield_keep_70": bucket(high, "exit_minus_hold_keep_70")}


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
                "frozen_decision_file": e.get("frozen_decision_file"), "sell_cutoff": e.get("sell_cutoff"),
                "gross_dividend": e.get("gross_dividend"), "pre_price": pre, "post_price": e.get("post_price"),
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
        "policy_folds": [{k: f[k] for k in ("fold", "pdr_estimate", "pdr_se")} for f in json.loads(c.SCORECARD.read_text())["folds"]],
    }
    oos = [r for r in spread if r["fold"] in periods["OOS"][2]]
    report["vs_always_exit_per_event"] = {name: _per_event([r for r in spread if r["fold"] in period[2]])
                                         for name, period in periods.items()}
    report["vs_always_exit_oos_concentration"] = _concentration(spread, periods["OOS"])
    report["vs_always_exit_full_sample"] = _full_sample()
    report["would_trading_have_helped"] = _counterfactual()
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
    RUN_RECORDS.write_text(render_run_records(report, live_order()))
    return report


def live_order(folder: Path = LIVE_ORDER) -> dict:
    """The real order's fields, read from the saved Bitget responses."""
    read = lambda name: json.loads((folder / name).read_text())
    status = read("04_order_status.json")["data"]
    before = read("03_balance_preflight.json")
    after = read("06_balance_after.json")
    return {
        "folder": folder.relative_to(ROOT).as_posix(),
        "submitted_at": read("03_order.json")["requestTime"],
        "order_id": status["orderId"], "instrument": status["symbol"], "direction": status["side"],
        "order_type": f"{status['orderType']} {status['timeInForce']}", "limit_price": status["price"],
        "fill_price": status["avgPrice"], "quantity": status["cumExecQty"], "value_usdt": status["cumExecValue"],
        "status": status["orderStatus"], "fee_usdt": status["feeDetail"][0]["fee"],
        "usdt_before": before["available"], "usdt_after": after["assets"]["USDT"]["available"],
        "base_after": after["assets"][status["symbol"].removesuffix("USDT").replace("R", "r", 1)]["available"],
        "balance_checked_at": after["checked_at"],
    }


def position_check(order: dict, paper: Path | None = None) -> dict | None:
    """Latest read-only snapshot of the live position: holdings, ledger, quote and dividend due."""
    folders = sorted((paper or ROOT / "data" / "raw" / "paper").glob("*_rTOWN_position"))
    if not folders:
        return None
    folder = folders[-1]
    read = lambda name: json.loads((folder / name).read_text())
    assets = {a["coin"]: a for a in read("01_account_rTOWN.json")["data"]["assets"]["data"]["assets"]}
    ledger = [row for name in ("03_ledger_USDT.json", "04_ledger_rTOWN.json") for row in read(name)["data"]["list"]]
    ticker = read("05_ticker.json")["data"][0]
    event = next(json.loads(line) for line in (ROOT / "data" / "ledger" / "reality_forward_20260923_resolved.jsonl")
                 .read_text().splitlines() if '"rTOWN-2026-09-25-1"' in line)
    qty = float(assets["rTOWN"]["balance"])
    gross = float(event["gross_dividend_per_share"])
    cost = float(order["value_usdt"]) + float(order["fee_usdt"])
    value = float(assets["rTOWN"]["usdValue"])
    credit = json.loads((folder / "07_credit.json").read_text()) if (folder / "07_credit.json").is_file() else None
    credited_usdt = float(credit.get("credited_usdt", credit["usdt_change_since_buy"])) if credit else None
    return {
        "credited_usdt": credited_usdt, "credit_detected_at": credit["detected_at"] if credit else None,
        "credit_ledger_types": sorted({row.get("type", "?") for row in credit["ledger_rows"]}) if credit else [],
        "implied_withholding": (1 - credited_usdt / (qty * gross)) if credit and qty * gross else None,
        "folder": (folder.relative_to(ROOT) if folder.is_relative_to(ROOT) else folder).as_posix(),
        "checked_at": read("01_account_rTOWN.json")["requestTime"],
        "quantity": qty, "last_price": ticker["lastPrice"], "bid": ticker["bid1Price"], "ask": ticker["ask1Price"],
        "value_usdt": value, "cost_usdt": cost, "ex_date": event["exchange_ex_date"],
        "dividend_payment_ts": event["cash_dividend_timestamp"], "gross_per_share": gross,
        "dividend_gross_usdt": qty * gross, "dividend_70pct_usdt": qty * gross * 0.7,
        "ledger_rows": len(ledger), "dividend_credited": credit is not None,
    }


def _position_lines(pos: dict | None) -> list[str]:
    if not pos:
        return []
    mark = pos["value_usdt"] - pos["cost_usdt"]
    return [
        "**Since the order.** Exnight's frozen call for rTOWN's ex-date was NO_SIGNAL: no step-out, so",
        f"the position was held through it. Read-only snapshot {pos['checked_at']} ([`{pos['folder']}/`](../{pos['folder']}/)):",
        "",
        "| | |",
        "|---|---|",
        f"| Holding | {pos['quantity']} rTOWN, held through the {pos['ex_date']} ex-date |",
        f"| Paid, with fee | {pos['cost_usdt']:.4f} USDT |",
        f"| Worth now | {pos['value_usdt']:.4f} USDT (last {pos['last_price']}; quote {pos['bid']} / {pos['ask']}) |",
        f"| Change since the buy, fee included | {mark:+.4f} USDT, before the dividend |",
        f"| Dividend due | {pos['gross_per_share']} per share: {pos['dividend_gross_usdt']:.4f} USDT gross, "
        f"{pos['dividend_70pct_usdt']:.4f} if 30% is withheld |",
        (f"| Dividend credited | **{pos['credited_usdt']:.6f} USDT**, seen {pos['credit_detected_at']} "
         f"(ledger type {', '.join(pos['credit_ledger_types']) or 'balance change only'}) |"
         if pos["dividend_credited"] else
         f"| Dividend credited? | not yet: Bitget lists payment at {pos['dividend_payment_ts']}; "
         f"the ledger has {pos['ledger_rows']} rows, the buy only |"),
        *([f"| Withholding actually applied | **{100 * pos['implied_withholding']:.1f}%** "
           f"(1 − credited / gross due) |"] if pos["dividend_credited"] else []),
        "",
        ("This is the withholding the backtest had to assume (0% to 30%), now observed on a real holding."
         if pos["dividend_credited"] else
         "The credit will show what withholding Bitget actually applies to an rToken holder, which the "
         "backtest has to assume. `scripts/check_dividend_credit.py` checks for it read-only every 15 "
         "minutes after the payment time and records it here when it lands."),
        "",
    ]


def render_run_records(report: dict, order: dict) -> str:
    live, window = report["live"], report["window"]
    oos = report["vs_always_exit"]["OOS"]["metrics"]
    base = order["instrument"].removesuffix("USDT").replace("R", "r", 1)
    rows = []
    for e in sorted(live["events"], key=lambda e: (e["ex_date"], e["event_id"])):
        stamp = (e["frozen_decision_file"] or "").removeprefix("signals_v3_").removesuffix(".csv")
        hold = "n/a" if e["exit_minus_hold_bps"] is None else f"{-e['exit_minus_hold_bps']:+.1f}"
        pdr = "n/a" if e["realised_pdr"] is None else f"{e['realised_pdr']:.2f}"
        rows.append(f"| {e['event_id'].split('-')[0]} | {e['ex_date']} | {stamp} | {e['frozen_verdict_1k']} | "
                    f"{e['pre_price']} → {e['post_price']} | {pdr} | {e['price_discovery']} | {hold} |")
    lines = [
        "# Exnight run records",
        "",
        "In the handbook's order of priority: live, then backtest. Every figure below is read from",
        "files committed in this repository; `python scripts/run_backtest.py` regenerates this page.",
        "",
        "## 1. Live order on Bitget",
        "",
        "A real order placed through Bitget Agent Hub to check that an rToken with an empty public",
        f"order book fills at its quote. Saved request and response files: [`{order['folder']}/`](../{order['folder']}/);",
        "write-up: [`docs/live_fill_20260923.md`](../docs/live_fill_20260923.md).",
        "",
        "| Timestamp (UTC) | Instrument | Direction | Price | Quantity | Fee | Balance change |",
        "|---|---|---|---:|---:|---:|---|",
        f"| {order['submitted_at']} | {order['instrument']} | {order['direction']} | {order['fill_price']} "
        f"(limit {order['limit_price']}, {order['order_type']}) | {order['quantity']} | {order['fee_usdt']} USDT | "
        f"USDT {order['usdt_before']} → {order['usdt_after']}; {base} 0 → {order['base_after']} |",
        "",
        f"Order `{order['order_id']}`, status `{order['status']}`, value {order['value_usdt']} USDT; balances read "
        f"{order['balance_checked_at']} with a read-only key.",
        "",
        *_position_lines(position_check(order)),
        "## 2. Live forward test",
        "",
        f"{live['scheduled']} high-dividend ex-dates from 25 September to 8 October, chosen and scheduled before the first",
        "one. Each decision is committed to Git (and, from 5 October, anchored on Arbitrum One) before",
        "the 20:00 ET sell cutoff, the price is recorded every minute, and a scorer grades it after the",
        f"ex-date. {live['graded']} graded so far. Prices are the last trade at the cutoff and at 04:00 ET;",
        "\"Hold minus step out\" is per event, modeled costs, 70% of the dividend kept.",
        "",
        "| Token | Ex-date | Decision committed | Decision ($1k) | Price, cutoff → 04:00 ET | Drop / dividend | Overnight trading | Hold minus step out, bps |",
        "|---|---|---|---|---|---:|---|---:|",
        *rows,
        "",
        f"Holding beat stepping out on {live['all']['hold_beat_exit']} of {live['all']['events']} graded events; on the "
        f"{live['priced_overnight']['events']} nights where the price actually moved, {live['priced_overnight']['hold_beat_exit']} of "
        f"{live['priced_overnight']['events']}. Score files: `data/results/forward_score_v3_*.json`; recordings:",
        "`data/raw/recorder/v3_*/`.",
        "",
        "## 3. Backtest",
        "",
        f"{window['start']} to {window['end']}: {window['total_days']} days in total, {window['oos_days']} days out-of-sample, walk-forward.",
        f"Exnight minus always selling first, out-of-sample: Sharpe {_num(oos['sharpe'])}, Sortino {_num(oos['sortino'])}, "
        f"max drawdown {_pct(oos['maximum_drawdown'])}. Full record and limits: [`backtest.md`](backtest.md); code:",
        "[`exnight/backtest_report.py`](../exnight/backtest_report.py), [`exnight/competition.py`](../exnight/competition.py),",
        "[`scripts/run_backtest.py`](../scripts/run_backtest.py).",
        "",
    ]
    return "\n".join(lines)


def _bp(value) -> str:
    return "n/a" if value is None else f"{value:.1f}"


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
    full = report["vs_always_exit_full_sample"]
    cf = report["would_trading_have_helped"]
    hy = cf["high_yield_keep_70"]
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
        f"(t-stat {_num(conc['leave_one_symbol_out'][top]['t_stat'])}). The check below widens the sample to every resolved event: "
        f"without {top}, Exnight is ahead on {full['all_without_top_symbol']['symbols_ahead']} of "
        f"{full['all_without_top_symbol']['symbols']} tokens.",
        "",
        "**Every resolved event (robustness check, added after the results).** The scorecard counts",
        "only events whose gross dividend was declared before the decision. The other",
        f"{full['excluded_from_scorecard']['events']} resolved cash events were excluded for that reason alone. On them Exnight",
        "has nothing to act on, outputs NO_SIGNAL, and the holder holds, so the same gap can be measured",
        "with the same prices, costs and timing. Nothing in the frozen scorecard changes.",
        "",
        "| Sample | Events | Tokens | Mean, bps | t-stat | Tokens where Exnight is ahead |",
        "|---|---:|---:|---:|---:|---:|",
        *[f"| {label} | {full[key]['events']} | {full[key]['symbols']} | {full[key]['mean_bps']:.1f} | "
          f"{_num(full[key]['t_stat'])} | {full[key]['symbols_ahead']} of {full[key]['symbols']} |"
          for key, label in (("all", "Every resolved event"),
                             ("all_without_top_symbol", f"Every resolved event, without {full['top_symbol']}"),
                             ("oos_period", "Out-of-sample period"),
                             ("oos_period_without_top_symbol", f"Out-of-sample period, without {full['top_symbol']}"),
                             ("excluded_from_scorecard", "Only the events the scorecard excludes"))],
        "",
        "## 2. Exnight as traded",
        "",
        "Exnight never found an event where stepping out cleared its costs, so it held every time.",
        "Its return is the holder's return: the overnight price move plus the dividend kept.",
        "",
        head, *_rows_for(report["policy"], rule_trades=True),
        "",
        "### Why Exnight made no trades, and whether trading would have helped",
        "",
        "Bitget doesn't publish what an rToken holder keeps of a dividend, so the frozen rule steps out",
        "only if the drop beats the *whole* dividend plus costs, with the drop's uncertainty taken",
        "at two standard errors. The walk-forward estimated the drop at "
        + "; ".join(f"{f['pdr_estimate']:.2f} ± {f['pdr_se']:.2f} of the dividend ({f['fold']})" for f in report["policy_folds"])
        + ". Neither lower bound is above 1, so no event could pass, whatever its size.",
        "",
        "So the question is whether a less cautious rule would have found anything. The table uses the",
        f"realised drop on every resolved dividend ({cf['events']} events, added after the results; not a strategy):",
        "stepping out minus holding, per event, after fees and slippage.",
        "",
        "| Dividend yield | Events | Holder keeps 100%: mean / median, bps | Holder keeps 70%: mean / median, bps | t-stat (keeps 70%) | Stepping out won (keeps 70%) |",
        "|---|---:|---:|---:|---:|---:|",
        *[f"| {b['yield_bps'][0]}–{b['yield_bps'][1] if b['yield_bps'][1] < 10_000 else ''} bps | {b['keep_70']['events']} | "
          f"{_bp(b['keep_100']['mean_bps'])} / {_bp(b['keep_100']['median_bps'])} | "
          f"{_bp(b['keep_70']['mean_bps'])} / {_bp(b['keep_70']['median_bps'])} | {_num(b['keep_70']['t_stat'])} | "
          f"{b['keep_70']['exit_won']} of {b['keep_70']['events']} |" for b in cf["buckets"]],
        "",
        f"Even if the holder keeps only 70% and the rule stepped out only on dividends of {cf['high_yield_threshold_bps']} bps or more, "
        f"it would have won {hy['exit_won']} of {hy['events']} and averaged {_bp(hy['mean_bps'])} bps per event (t-stat {_num(hy['t_stat'])}):",
        "",
        "| Token | Ex-date | Yield, bps | Drop / dividend | Cost, bps | Stepping out minus holding, bps |",
        "|---|---|---:|---:|---:|---:|",
        *[f"| {e['symbol']} | {e['ex_date']} | {e['yield_bps']:.0f} | {_num(e['drop_over_dividend'])} | {e['cost_bps']:.0f} | "
          f"{e['exit_minus_hold_keep_70']:+.1f} |" for e in cf["high_yield"]],
        "",
        "Stepping out lost wherever the price had fallen well short of the dividend by the measurement",
        "time; on two nights it hadn't moved at all. No yield band shows stepping out ahead with a t-stat",
        "near 2; on the smallest dividends it is reliably behind. The one band with a positive average",
        "has a negative median. On this data, a rule that stepped out by dividend size, at either",
        "withholding, had no reliable edge to trade, so holding was the right output, not a missing one. The one input that could change this is the withholding Bitget",
        "actually applies, which the live rTOWN position will show when its dividend is credited.",
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

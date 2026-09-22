"""Regenerate the competition decisions, scorecard, capacity summary and Markdown report."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from exnight import competition  # noqa: E402


def pct(value):
    return "—" if value is None else f"{100 * value:.3f}%"


def number(value):
    return "—" if value is None else f"{value:.2f}"


def capacity(forward: dict) -> dict:
    rows = []
    for event in forward["results"]:
        by_size = []
        for item in event["notionals"]:
            public = item["sell_book_source"] == "public_book" and item["buy_book_source"] == "public_book"
            by_size.append({
                "notional_usdt": item["notional_usd"],
                "public_book_supported": public,
                "walk_cost": item["cost_per_share"] if public else None,
                "reason": "" if public else "no contemporaneous two-sided public book",
            })
        rows.append({"symbol": event["symbol"], "nonempty_public_book_samples": 0,
                     "sizes": by_size})
    return {
        "as_of": forward["checked_at"],
        "label": "OBSERVED_FORWARD_EXECUTION_CAPACITY",
        "events": rows,
        "conclusion": "No recorded pair had a nonempty public book; $1k/$5k/$25k capacity is unproven.",
    }


def render(report: dict, forward: dict, cap: dict) -> str:
    sample = report["sample"]
    is_score = report["is_initial_development_window"]
    oos = report["oos_concatenated_non_overlapping_folds"]
    lines = [
        "# Alpha Factory scorecard",
        "",
        "This is the **walk-forward OOS performance of the Exnight selection procedure**. It is not V1 OOS. Strategy V1 was fitted on all 127 discovery events and has no historical OOS window.",
        "",
        "Every historical execution figure below is **MODELED_EXECUTION**. The HOLD benchmark accrues dividend entitlement at T1; it does not assume cash was paid by T1.",
        "",
        "## Sample",
        "",
        f"- Discovery: 185 corporate actions → 58 usable unresolved → 127 usable resolved.",
        f"- Ex-ante filter: **{sample['eligible_ex_ante']} of {sample['resolved_usable']}** resolved/usable events retain pre-decision declaration evidence; {sample['excluded']} are excluded from the scorecard.",
        f"- OOS: **{oos['policy']['event_count']} events across 47 calendar days; {oos['policy']['trade_count']} EXIT trades.**",
        "- The excluded 71 comprise 58 events whose current gross-basis proof is the later Bitget payment notice and 13 supported only by realised records.",
        "",
        "## Fold diagnostics",
        "",
        "| Fold | Training end | Test period | Rung | PDR ± SE | Training events | Test events | EXIT trades | Test Sharpe |",
        "|---|---:|---|---|---:|---:|---:|---:|---:|",
    ]
    for fold in report["folds"]:
        lines.append(
            f"| {fold['fold']} | {fold['training_end']} | {fold['test_period']} | `{fold['selected_rung']}` | "
            f"{fold['pdr_estimate']:.3f} ± {fold['pdr_se']:.3f} | {fold['training_events']} | "
            f"{fold['test_events']} | {fold['test_trades']} | {number(fold['test_sharpe'])} |"
        )
    lines += ["", "## Main scorecard", "",
              "Primary reporting uses 0% withholding, the most holder-favourable and therefore hardest case for EXIT, plus 25 bps round-trip modeled slippage.", "",
              "| Window / series | Total | Annualised | Sharpe / IR | Sortino | Max drawdown |",
              "|---|---:|---:|---:|---:|---:|"]
    for window, scores in (("IS initial", is_score), ("OOS", oos)):
        for series in ("policy", "benchmark", "active"):
            item = scores[series]
            ratio = item.get("information_ratio", item.get("sharpe"))
            lines.append(f"| {window} — {series} | {pct(item['total_return'])} | {pct(item['annualized_return'])} | {number(ratio)} | {number(item['sortino'])} | {pct(item['maximum_drawdown'])} |")
    ratio = report["oos_sharpe_over_is_sharpe"]
    lines += [
        "",
        f"The arithmetic OOS/IS Sharpe quotient is {ratio:.2f}, but it is **not economically meaningful** because IS Sharpe is negative ({is_score['policy']['sharpe']:.2f}) and rests on {report['is_trade_count_for_ratio']} EXIT trades. It is not treated as evidence against the 0.5 decay flag.",
        "",
        "The robust rule issued no EXIT trades. Policy therefore equals HOLD, active return is zero, turnover and modeled fee/slippage drag are zero, and every rolling 30-day Sharpe window is `INSUFFICIENT_EVENTS`.",
        "",
        "## Cost and entitlement sensitivity",
        "",
        "| Round trip slippage | Withholding | EXIT trades | Policy return | Policy Sharpe | Active return |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    for item in report["sensitivity"]:
        score = item["score"]
        lines.append(f"| {item['slippage_bps_MODELED_EXECUTION']} bps | {100*item['withholding']:.0f}% | {score['policy']['trade_count']} | {pct(score['policy']['total_return'])} | {number(score['policy']['sharpe'])} | {pct(score['active']['total_return'])} |")
    lines += [
        "",
        "No point in the full grid produces an EXIT trade. The result therefore does not establish active alpha at the frozen confidence threshold.",
        "",
        "## Forward evidence",
        "",
        "- 21 September remains `INCOMPLETE` because of the disclosed 57-minute recording gap.",
        f"- 22 September recorder integrity passed: 1,348 rows per symbol, maximum gap 63 seconds, and timely T0/T1 samples. The combined strategy score is `{forward['status']}` because rAPH and rSTM lacked resolved gross/net basis. rSATA produced frozen `HOLD` and realised PDR 0.0.",
        f"- Capacity: {cap['conclusion']}",
        "",
        "The forward recorder result is evidence about frozen V1. It is separate from the walk-forward scorecard above.",
        "",
        "## Reproduce",
        "",
        "```bash",
        ".venv/bin/python scripts/build_competition_submission.py",
        "```",
        "",
        f"Frozen manifest SHA-256: `{report['manifest_sha256']}`.",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    report = competition.score()
    forward_path = competition.RESULTS / "forward_score_20260922.json"
    forward = json.loads(forward_path.read_text())
    cap = capacity(forward)
    (competition.RESULTS / "forward_capacity_20260922.json").write_text(json.dumps(cap, indent=2) + "\n")
    (ROOT / "docs" / "competition_scorecard.md").write_text(render(report, forward, cap))


if __name__ == "__main__":
    main()

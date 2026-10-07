import json

import pandas as pd

from exnight import backtest_report, competition


def test_report_meets_the_window_rule_and_matches_its_inputs():
    report = backtest_report.build()
    window = report["window"]
    assert window["total_days"] >= 60 and window["oos_days"] >= 30

    policy = report["policy"]["OOS"]["metrics"]
    scorecard = json.loads(competition.SCORECARD.read_text())["oos_concatenated_non_overlapping_folds"]["policy"]
    assert abs(policy["sharpe"] - scorecard["sharpe"]) < 1e-9
    assert policy["trade_count"] == scorecard["trade_count"]

    spread = report["vs_always_exit"]["OOS"]["metrics"]
    always_exit = json.loads((competition.RESULTS / "always_exit_baseline.json").read_text())["primary"]["oos"]
    gap = report["vs_always_exit_oos_decomposition"]
    assert abs(gap["gap_bps"] + always_exit["mean_active_bps"]) < 1e-6
    assert abs(gap["gap_bps"] - (gap["cost_bps"] + gap["hold_bps"])) < 1e-6
    assert "trade_count" not in spread and spread["comparator_trade_count"] == always_exit["events"]


def test_sensitivity_reuses_frozen_verdicts():
    frame, decisions = backtest_report._frozen_rows()
    frozen = decisions[(decisions.slippage_bps == competition.BASE_SLIPPAGE_BPS)
                       & (decisions.withholding == competition.PRIMARY_WITHHOLDING)]
    rows = backtest_report._spread_rows(decisions, frame, slippage_bps=100, withholding=0.3)
    assert {r["event_id"]: r["rule_verdict"] for r in rows} == dict(zip(frozen.event_id, frozen.verdict))


def test_markdown_quotes_the_json():
    report = json.loads(backtest_report.OUTPUT.read_text())
    text = backtest_report.MARKDOWN.read_text()
    assert f"| Sharpe | {report['vs_always_exit']['IS']['metrics']['sharpe']:.2f} | " \
           f"{report['vs_always_exit']['OOS']['metrics']['sharpe']:.2f} |" in text
    daily = pd.read_csv(backtest_report.DAILY)
    assert (daily.rule - daily.always_exit - daily.rule_minus_always_exit).abs().max() < 1e-7


def test_readme_quotes_the_report():
    report = json.loads(backtest_report.OUTPUT.read_text())
    readme = (competition.ROOT / "README.md").read_text()
    view = report["vs_always_exit"]
    assert f"| Sharpe | {view['IS']['metrics']['sharpe']:.2f} | **{view['OOS']['metrics']['sharpe']:.2f}** |" in readme
    assert f"| Sortino | {view['IS']['metrics']['sortino']:.2f} | {view['OOS']['metrics']['sortino']:.2f} |" in readme
    assert f"{view['oos_over_is_sharpe']['ratio']:.2f} (no decay)" in readme
    gap = report["vs_always_exit_oos_decomposition"]
    assert f"paid {gap['cost_bps']:.1f} bps per event" in readme and f"returned {gap['hold_bps']:.1f} bps" in readme
    oos = report["vs_always_exit_per_event"]["OOS"]
    assert f"averages {oos['mean_bps']:.1f} bps with a t-stat of {oos['t_stat']:.2f}" in readme
    rest = report["vs_always_exit_oos_concentration"]["leave_one_symbol_out"]["rSATA"]
    assert f"({rest['mean_bps']:.1f} bps over {rest['events']} events)" in readme

import json
from pathlib import Path

import pandas as pd

from exnight import baseline, competition

ROOT = Path(__file__).resolve().parent.parent


def test_always_exit_uses_every_frozen_oos_event_and_the_scorecard_costs():
    report = baseline.build()
    decisions = pd.read_csv(competition.DECISIONS)
    primary = decisions[(decisions.slippage_bps == competition.BASE_SLIPPAGE_BPS)
                        & (decisions.withholding == competition.PRIMARY_WITHHOLDING)]
    oos = primary[primary.fold.str.startswith("OOS_")]
    assert report["primary"]["oos"]["events"] == len(oos)
    assert report["primary"]["oos"]["score"]["policy"]["trade_count"] == len(oos)
    # With withholding 0 the benchmark equals the frozen decisions' HOLD benchmark.
    frozen_hold = oos.benchmark_return.mean()
    active = report["primary"]["oos"]["mean_active_bps"] / 1e4
    fee = pd.read_csv(competition.KNOWLEDGE, keep_default_na=False).set_index("event_id").loc[oos.event_id, "fee_rate"]
    exit_mean = -(2 * pd.to_numeric(fee) + competition.BASE_SLIPPAGE_BPS / 1e4).mean()
    assert abs(active - (exit_mean - frozen_hold)) < 1e-12
    assert report["label"].startswith("ADDED_AFTER_OOS_RESULTS")


def test_scorecard_shows_the_always_exit_figures():
    report = json.loads(baseline.OUTPUT.read_text())
    text = (ROOT / "docs" / "competition_scorecard.md").read_text()
    oos = report["primary"]["oos"]
    assert f"| OOS | {oos['events']} | {oos['mean_active_bps']:.1f} bps | {100 * oos['share_exit_beat_hold']:.0f}% |" in text


def test_readme_headline_figures_come_from_saved_results():
    readme = (ROOT / "README.md").read_text()
    exit_ = json.loads(baseline.OUTPUT.read_text())["primary"]["oos"]
    score = json.loads((ROOT / "data" / "results" / "competition_scorecard.json").read_text())
    oos = score["oos_concatenated_non_overlapping_folds"]
    days = json.loads((ROOT / "data" / "results" / "competition_backtest_manifest.json").read_text())["oos_calendar_days"]
    minus = lambda text: text.replace("-", "−")
    assert f"Out-of-sample, {oos['policy']['event_count']} events over {days} days" in readme
    assert minus(f"| Trades | {oos['policy']['trade_count']} | {exit_['score']['policy']['trade_count']} | 0 |") in readme
    assert minus(f"**{exit_['mean_active_bps']:.1f} bps**") in readme
    assert f"| {100 * exit_['share_exit_beat_hold']:.0f}% |" in readme
    assert minus(f"| {100 * oos['policy']['total_return']:.3f}% | {100 * exit_['score']['policy']['total_return']:.3f}% | "
                 f"{100 * oos['benchmark']['total_return']:.3f}% |") in readme
    assert minus(f"| {oos['policy']['sharpe']:.2f} | {exit_['score']['policy']['sharpe']:.2f} | "
                 f"{oos['benchmark']['sharpe']:.2f} |") in readme


def test_submission_copy_matches_saved_results():
    text = (ROOT / "SUBMISSION.md").read_text()
    exit_ = json.loads(baseline.OUTPUT.read_text())["primary"]["oos"]
    score = json.loads((ROOT / "data" / "results" / "competition_scorecard.json").read_text())
    oos = score["oos_concatenated_non_overlapping_folds"]
    minus = lambda t: t.replace("-", "−")
    assert f"{score['sample']['eligible_ex_ante']} of {score['sample']['resolved_usable']} events" in text
    assert f"{oos['policy']['event_count']} events over 47 days" in text
    assert minus(f"{100 * oos['policy']['total_return']:.3f}%, Sharpe {oos['policy']['sharpe']:.2f}") in text
    assert minus(f"**{exit_['mean_active_bps']:.1f} bps per event**") in text
    assert f"only {100 * exit_['share_exit_beat_hold']:.0f}% of events" in text

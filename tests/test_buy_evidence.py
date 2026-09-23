import json
from pathlib import Path

from exnight import buy_evidence

ROOT = Path(__file__).resolve().parent.parent


def _mean(report: dict, scenario: str, slippage: int) -> float:
    return next(s["mean_bps"] for s in report["scenarios"]
                if s["scenario"] == scenario and s["slippage_bps"] == slippage)


def test_buy_capture_loses_in_every_scenario():
    report = buy_evidence.build()
    assert report["events"] == 127
    assert all(s["mean_bps"] < 0 for s in report["scenarios"])
    # Not being counted is always worse than being counted with no withholding.
    for slip in buy_evidence.SLIPPAGE_BPS:
        assert _mean(report, "not counted", slip) < _mean(report, "counted, no withholding", slip)


def test_quoted_buy_figures_match_saved_result():
    report = json.loads(buy_evidence.OUTPUT.read_text())
    best = f"{_mean(report, 'counted, no withholding', 10):.1f}".replace("-", "−")
    uncounted = f"{_mean(report, 'not counted', 10):.1f}".replace("-", "−")
    readme = (ROOT / "README.md").read_text()
    assert f"{best} bps per event" in readme and f"{uncounted} bps or worse" in readme
    assert f"({best} bps per event)" in (ROOT / "SUBMISSION.md").read_text()
    from dashboard.server import LIMITS
    assert any(best.replace("−", "-") in item for item in LIMITS)

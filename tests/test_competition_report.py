import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_competition_report_regenerates_exactly():
    tracked = [
        ROOT / "data/results/competition_scorecard.json",
        ROOT / "data/results/competition_decisions.csv",
        ROOT / "data/results/forward_capacity_20260922.json",
        ROOT / "docs/competition_scorecard.md",
    ]
    before = {path: path.read_bytes() for path in tracked}
    subprocess.run([sys.executable, str(ROOT / "scripts/build_competition_submission.py")],
                   check=True, capture_output=True)
    assert {path: path.read_bytes() for path in tracked} == before


def test_report_numbers_come_from_scorecard():
    score = json.loads((ROOT / "data/results/competition_scorecard.json").read_text())
    text = (ROOT / "docs/competition_scorecard.md").read_text()
    assert f"**{score['sample']['eligible_ex_ante']} of {score['sample']['resolved_usable']}**" in text
    assert f"{score['oos_concatenated_non_overlapping_folds']['policy']['event_count']} events" in text
    assert score["manifest_sha256"] in text

    readme = (ROOT / "README.md").read_text()
    oos = score["oos_concatenated_non_overlapping_folds"]
    assert f"Only {score['sample']['eligible_ex_ante']} of the {score['sample']['resolved_usable']}" in readme
    assert f"{oos['policy']['event_count']}\n   events" in readme
    assert f"Sharpe **{oos['policy']['sharpe']:.2f}**".replace("-", "−") in readme

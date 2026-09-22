import json
import subprocess
import sys
import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def test_competition_report_regenerates_exactly():
    report = ROOT / "docs/competition_scorecard.md"
    capacity = ROOT / "data/results/forward_capacity_20260922.json"
    decisions = ROOT / "data/results/competition_decisions.csv"
    before_report = report.read_bytes()
    before_capacity = json.loads(capacity.read_text())
    with decisions.open(newline="") as stream:
        before_decisions = [(r["fold"], r["event_id"], r["selected_rung"], r["verdict"])
                            for r in csv.DictReader(stream)]
    subprocess.run([sys.executable, str(ROOT / "scripts/build_competition_submission.py")],
                   check=True, capture_output=True)
    assert report.read_bytes() == before_report
    assert json.loads(capacity.read_text()) == before_capacity
    with decisions.open(newline="") as stream:
        after_decisions = [(r["fold"], r["event_id"], r["selected_rung"], r["verdict"])
                           for r in csv.DictReader(stream)]
    assert after_decisions == before_decisions


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

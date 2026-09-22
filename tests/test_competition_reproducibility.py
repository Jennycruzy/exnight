"""Competition-facing discovery provenance must match the frozen V1 rule."""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def _jsonl_count(path: Path) -> int:
    return sum(1 for line in path.read_text().splitlines() if line.strip())


def test_readme_reproduces_the_resolved_v1_study():
    readme = (ROOT / "README.md").read_text()
    rule = json.loads((ROOT / "strategy" / "strategy_v1.json").read_text())
    summary = json.loads((ROOT / "data" / "results" / "summary_resolved.json").read_text())
    unresolved = json.loads((ROOT / "data" / "results" / "summary_reality.json").read_text())

    assert "--ledger data/ledger/reality_notice59_resolved.jsonl" in readme
    assert "--output data/results/event_results_resolved.json" in readme
    assert _jsonl_count(ROOT / "data" / "ledger" / "reality_notice59.jsonl") == 185
    assert _jsonl_count(ROOT / "data" / "ledger" / "reality_notice59_resolved.jsonl") == 185
    assert unresolved["floor_None"]["events_usable"] == 58
    assert summary["floor_None"]["events_usable"] == 127

    slope = summary[rule["estimate"]["sample"]]["rungs"][rule["rung"]]["slope"]
    assert slope["n"] == rule["estimate"]["n"] == 127
    assert slope["pdr"] == rule["estimate"]["pdr_hat"]

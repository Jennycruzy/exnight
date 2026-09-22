import csv
import datetime as dt
import json
from pathlib import Path

import pandas as pd

from exnight import competition


ROOT = Path(__file__).resolve().parent.parent


def test_knowledge_time_never_uses_post_decision_gross(tmp_path, monkeypatch):
    output = tmp_path / "knowledge.csv"
    monkeypatch.setattr(competition, "KNOWLEDGE", output)
    rows = competition.build_knowledge_table()
    assert len(rows) == 185
    eligible = [r for r in rows if r["eligible_ex_ante"] == "YES"]
    assert eligible
    for row in eligible:
        assert row["gross_known_before_decision"] == "YES"
        assert dt.datetime.fromisoformat(row["gross_dividend_published_ts"]) <= dt.datetime.fromisoformat(row["decision_ts"])
        assert row["withholding_known_before_decision"] in {"YES", "RANGE_USED"}


def test_fold_training_outcomes_precede_test_decisions():
    competition.build_knowledge_table()
    frame = competition._eligible_frame()
    for start in (dt.date(2026, 8, 1), dt.date(2026, 9, 1)):
        first = pd.Timestamp(dt.datetime.combine(start, dt.time(20), competition.ET) - dt.timedelta(days=1))
        training = frame[frame.outcome_observable_ts < first]
        test = frame[frame.ex_date >= start]
        assert len(training) >= competition.MIN_TRAINING_EVENTS
        assert training.outcome_observable_ts.max() < test.decision_ts.min()


def test_manifest_records_case_b_and_t0_definition():
    if not competition.MANIFEST.exists():
        return
    manifest = json.loads(competition.MANIFEST.read_text())
    assert manifest["v1_provenance"].startswith("Case B")
    assert "decision_ts=T0" in manifest["portfolio_definition"]
    assert manifest["rung_rule_written_after_v1_freeze"] is True

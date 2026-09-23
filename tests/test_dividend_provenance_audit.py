"""The source audit must reproduce without network or touching the frozen scorecard."""
import csv
import datetime as dt
import hashlib
import json
from pathlib import Path

from scripts.audit_dividend_provenance import _date, audit

ROOT = Path(__file__).resolve().parent.parent


def test_bitget_epoch_dates_use_the_documented_audit_calendar():
    stamp = int(dt.datetime(2026, 6, 10, 16, tzinfo=dt.timezone.utc).timestamp() * 1000)
    assert _date(str(stamp)) == "2026-06-11"


def test_source_audit_rebuilds_without_changing_frozen_results(tmp_path):
    frozen = ROOT / "data/results/competition_scorecard.json"
    before = hashlib.sha256(frozen.read_bytes()).hexdigest()
    output = tmp_path / "audit.csv"
    counts = audit(ROOT / "data/sources/bitget_dividends_audit_20260923.json", output)
    assert counts == {"MATCHED_PRE_DECISION_PRIMARY": 16,
                      "PRIMARY_AMOUNT_MISMATCH": 1, "NOT_REVIEWED": 54}
    with output.open(newline="", encoding="utf-8") as stream:
        rows = {row["event_id"]: row for row in csv.DictReader(stream)}
    assert len(rows) == 71
    assert rows["rBABA-2026-06-11-1"]["predecision_publication_verified"] == "NO"
    assert rows["rCRM-2026-06-11-1"]["predecision_publication_verified"] == "YES"
    assert all(row["primary_source_published_date"] < row["decision_ts"][:10]
               for row in rows.values() if row["predecision_publication_verified"] == "YES")
    assert hashlib.sha256(frozen.read_bytes()).hexdigest() == before


def test_audit_document_numbers_match_saved_inputs():
    document = (ROOT / "docs/dividend_provenance_audit.md").read_text(encoding="utf-8")
    with (ROOT / "data/results/dividend_provenance_candidates_20260923.csv").open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    verified = sum(row["predecision_publication_verified"] == "YES" for row in rows)
    earlier = sum(row["audit_status"] == "PRE_DECISION_DATE_CANDIDATE" for row in rows)
    same_day = sum(row["audit_status"] == "SAME_DAY_TIME_UNKNOWN" for row in rows)
    impact = json.loads((ROOT / "data/results/dividend_provenance_training_impact_20260923.json").read_text())
    initial = impact["windows"]["initial_development"]
    assert f"{verified} events match" in document
    assert f"{earlier} have an" in document
    assert f"{same_day} have a" in document
    assert f"{initial['frozen_inputs']['training_events']} | {initial['primary_verified_additions']['training_events']}" in document
    normalized = document.replace("−", "-")
    for name in ("initial_development", "before_september_fold"):
        window = impact["windows"][name]
        bounds = (f"{window['frozen_inputs']['two_se_lower_bound']:.3f} → "
                  f"{window['primary_verified_additions']['two_se_lower_bound']:.3f}")
        assert bounds in normalized
    jackknife = impact["leave_one_added_out_before_september"]
    assert f"{min(row['two_se_lower_bound'] for row in jackknife):.3f} and " in document
    assert f"{max(row['two_se_lower_bound'] for row in jackknife):.3f}" in document

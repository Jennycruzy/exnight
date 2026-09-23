import csv
import datetime as dt
import json
from pathlib import Path

from dashboard import v3_view

ROOT = Path(__file__).resolve().parent.parent


def test_comparison_matches_saved_results():
    view = v3_view.comparison(ROOT)
    exit_ = json.loads((ROOT / "data/results/always_exit_baseline.json").read_text())["primary"]["oos"]
    row = next(r for r in view["rows"] if r["name"] == "Always step out")
    assert view["events"] == exit_["events"]
    assert row["active_bps_per_event"] == exit_["mean_active_bps"]
    assert [r["name"] for r in view["rows"]] == ["Exnight", "Always step out", "Hold"]


def _write(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def test_shows_latest_decision_made_before_the_cutoff(tmp_path):
    results = tmp_path / "data" / "results"
    results.mkdir(parents=True)
    (tmp_path / "data" / "forward").mkdir()
    plan = {"rule_id": "exnight-strategy-v3", "min_gross_yield_bp": 66.7,
            "targets": [{"event_id": "rX-2026-09-28-1", "symbol": "rX", "ex_date": "2026-09-28",
                         "gross_dividend": 0.5, "gross_yield_bp": 80.0}],
            "groups": [{"label": "v3_20260928_RX", "event_ids": ["rX-2026-09-28-1"],
                        "sell_cutoff": "2026-09-25T20:00:00-04:00"}]}
    (tmp_path / "data" / "forward" / "v3_schedule.json").write_text(json.dumps(plan))
    base = {"event_id": "rX-2026-09-28-1", "notional_usd": "1000", "reason": "", "entitlement_tier": "E0_RANGE",
            "breakeven_yield_bp": "", "lower_ratio": "0.599", "pdr_hat": "0.966", "pdr_se": "0.183"}
    _write(results / "signals_v3_a.csv", [base | {"decided_at": "2026-09-24T23:30:00+00:00", "verdict": "NO_SIGNAL"}])
    _write(results / "signals_v3_b.csv", [base | {"decided_at": "2026-09-25T23:30:00+00:00", "verdict": "HOLD"}])
    _write(results / "signals_v3_c.csv", [base | {"decided_at": "2026-09-26T01:00:00+00:00", "verdict": "EXIT"}])
    event = v3_view.v3(tmp_path)["events"][0]
    assert event["verdict"] == "HOLD" and event["decision_file"] == "signals_v3_b.csv"
    assert event["score_status"] == "NOT_SCORED"


def test_public_build_includes_comparison_and_v3(tmp_path):
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    import build_pages
    build_pages.build(ROOT, tmp_path / "site", snapshot_path=ROOT / "data/results/public_dashboard_snapshot.json")
    summary = json.loads((tmp_path / "site" / "api" / "summary.json").read_text())
    assert summary["comparison"]["status"] == "AVAILABLE"
    assert len(summary["v3"]["events"]) == 16

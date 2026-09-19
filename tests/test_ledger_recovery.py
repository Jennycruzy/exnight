import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from build_reality_ledger import reconcile_failures
from verify_evidence import verify_ledger


def test_recovery_handles_changed_batch_boundaries_and_preserves_history():
    recovered = {"base_coins": ["rA", "rB"], "error": "old failure"}
    partial = {"base_coins": ["rB", "rC"], "error": "still pending"}
    unknown = {"error": "unknown batch"}
    state = {"completed": ["rA", "rB"], "failed": [recovered, partial, unknown]}
    reconcile_failures(state)
    reconcile_failures(state)
    assert state["failed"] == [partial, unknown]
    assert state["recovered_failures"] == [recovered]


def test_ledger_verification_rejects_duplicate_and_invalid_rows(tmp_path):
    source = Path(__file__).resolve().parent.parent / "data" / "ledger"
    row = next(source.glob("*.jsonl")).read_text().splitlines()[0]
    path = tmp_path / "ledger.jsonl"
    path.write_text(row + "\n")
    assert verify_ledger(path) == []
    path.write_text(row + "\n" + row + "\n{}\n")
    errors = verify_ledger(path)
    assert any("duplicate event ID" in error for error in errors)
    assert any("invalid ledger row" in error for error in errors)


def test_ledger_verification_rejects_missing_or_empty_output(tmp_path):
    path = tmp_path / "ledger.jsonl"
    assert verify_ledger(path)
    path.touch()
    assert verify_ledger(path)

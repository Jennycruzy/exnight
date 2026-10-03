import datetime as dt
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("freeze_v3", ROOT / "scripts" / "freeze_v3_decisions.py")
freeze = importlib.util.module_from_spec(spec)
spec.loader.exec_module(freeze)

NOW = dt.datetime(2026, 10, 6, 23, 30, tzinfo=dt.UTC)
COMMIT = "a" * 40
PATHS = ["data/results/signals_v3_x.csv"]


def _setup(monkeypatch, tmp_path, key):
    monkeypatch.setattr(freeze, "ROOT", tmp_path)
    monkeypatch.setattr(freeze, "load_dotenv", lambda *a, **k: None)
    if key is None:
        monkeypatch.delenv("EXNIGHT_ANCHOR_KEY", raising=False)
    else:
        monkeypatch.setenv("EXNIGHT_ANCHOR_KEY", key)
    calls = []
    monkeypatch.setattr(freeze, "_git", lambda *a: calls.append(a) or "")
    monkeypatch.setattr(freeze.anchor, "build_payload", lambda c, p, r: "payload")
    return calls


def test_no_key_skips_without_touching_git(monkeypatch, tmp_path, capsys):
    calls = _setup(monkeypatch, tmp_path, None)
    assert freeze.anchor_freeze(COMMIT, PATHS, NOW, "_x") == 0
    assert calls == [] and "anchor skipped" in capsys.readouterr().out


def test_failure_exits_3_and_commits_nothing(monkeypatch, tmp_path, capsys):
    calls = _setup(monkeypatch, tmp_path, "0xkey")
    def boom(*a, **k):
        raise freeze.anchor.AnchorError("wallet empty")
    monkeypatch.setattr(freeze.anchor, "anchor", boom)
    assert freeze.anchor_freeze(COMMIT, PATHS, NOW, "_x") == 3
    assert calls == [] and "anchor FAILED" in capsys.readouterr().err


def _ok(block_time):
    return lambda *a, **k: {"tx_hash": "0xabc", "block_number": 7, "block_time_utc": block_time,
                            "explorer": "https://arbiscan.io/tx/0xabc", "sent": True}


def test_success_writes_record_and_commits_it(monkeypatch, tmp_path):
    calls = _setup(monkeypatch, tmp_path, "0xkey")
    monkeypatch.setattr(freeze.anchor, "anchor", _ok("2026-10-06T23:31:00+00:00"))
    assert freeze.anchor_freeze(COMMIT, PATHS, NOW, "_20261006T2330Z") == 0
    rec = json.loads((tmp_path / "data/anchors/anchor_v3_20261006T2330Z.json").read_text())
    assert rec["before_cutoff"] is True and rec["cutoff_utc"] == "2026-10-07T00:00:00+00:00"
    assert rec["commit"] == COMMIT and rec["files"] == PATHS
    assert calls[0] == ("add", "--", "data/anchors/anchor_v3_20261006T2330Z.json")
    assert calls[1][:2] == ("commit", "--only") and "0xabc" in calls[1][4]


def test_late_block_is_flagged(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, "0xkey")
    monkeypatch.setattr(freeze.anchor, "anchor", _ok("2026-10-07T00:00:05+00:00"))
    assert freeze.anchor_freeze(COMMIT, PATHS, NOW, "_late") == 4
    rec = json.loads((tmp_path / "data/anchors/anchor_v3_late.json").read_text())
    assert rec["before_cutoff"] is False

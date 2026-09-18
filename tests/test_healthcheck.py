import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from healthcheck import depth_health  # noqa: E402


def test_depth_health_reports_fresh_csv(tmp_path):
    path = tmp_path / "depth.csv"
    path.write_text("ts,symbol\n2026-09-18T00:00:00Z,RXUSDT\n")
    result = depth_health(path, dt.datetime(2026, 9, 18, 0, 30, tzinfo=dt.UTC), 3600)
    assert result["status"] == "PASS" and result["rows"] == 1 and result["symbols"] == 1

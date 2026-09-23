"""docs/m0.md is rendered from data/results; assert it is current and internally consistent."""
import json
import math
import subprocess
import sys
from pathlib import Path

from exnight.analysis import frame, load, summarize

ROOT = Path(__file__).resolve().parent.parent


def test_m0_is_rendered_from_current_results(tmp_path):
    current = (ROOT / "docs" / "m0.md").read_text()
    subprocess.run([sys.executable, str(ROOT / "scripts" / "render_m0.py")], check=True, capture_output=True)
    rendered = (ROOT / "docs" / "m0.md").read_text()
    assert rendered == current, "docs/m0.md is stale: run scripts/render_m0.py"


def test_denominator():
    df = frame(load())
    s = summarize(df)
    assert s["events_total"] == 63
    assert s["events_usable"] + len(s["exclusions"]) == 63
    m0 = (ROOT / "docs" / "m0.md").read_text()
    for e in s["exclusions"]:
        assert e["event_id"] in m0


def test_summary_json_matches_recomputation():
    df = frame(load())
    stored = json.loads((ROOT / "data" / "results" / "summary.json").read_text())
    for key, kw in [("floor_None", {}), ("floor_0.5", {"yield_floor_pct": 0.5}),
                    ("clean_2000_floor_0.2", {"yield_floor_pct": 0.2, "clean_2000": True})]:
        fresh = summarize(df, **kw)
        assert math.isclose(
            fresh["rungs"]["overnight_2000"]["slope"]["pdr"],
            stored[key]["rungs"]["overnight_2000"]["slope"]["pdr"],
            rel_tol=1e-12, abs_tol=1e-12,
        )
        assert math.isclose(
            fresh["robustness_2000"]["ratio_of_sums"],
            stored[key]["robustness_2000"]["ratio_of_sums"],
            rel_tol=1e-12, abs_tol=1e-12,
        )

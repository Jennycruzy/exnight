"""Every headline figure in docs/m0.md recomputes from data/results (offline)."""
import json
import re
from pathlib import Path

from exnight.analysis import frame, load, summarize

ROOT = Path(__file__).resolve().parent.parent


def test_headline_figures_match_summary():
    df = frame(load())
    s = summarize(df)
    m0 = (ROOT / "docs" / "m0.md").read_text()
    assert s["events_total"] == 63 and s["events_usable"] == 59
    assert "63 distributions on 59 rTokens" in m0 and "**59 usable.**" in m0
    r = s["rungs"]["overnight_2000"]["slope"]
    assert f"**{r['pdr']:.2f} ± {r['se']:.2f}** (n = {r['n']}" in m0
    assert 0.9 < r["pdr"] < 1.3 and r["se"] < 0.2
    for e in s["exclusions"]:
        assert e["event_id"] in m0


def test_exclusion_count_equals_total_minus_usable():
    df = frame(load())
    assert len(df) - int(df.usable.sum()) == 4


def test_summary_json_regenerates():
    df = frame(load())
    fresh = {f"floor_{f}": summarize(df, f) for f in (None, 0.2, 0.5)}
    stored = json.loads((ROOT / "data" / "results" / "summary.json").read_text())
    for k in fresh:
        assert fresh[k]["rungs"]["overnight_2000"]["slope"]["pdr"] == stored[k]["rungs"]["overnight_2000"]["slope"]["pdr"]

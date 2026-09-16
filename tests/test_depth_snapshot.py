import datetime as dt
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from depth_snapshot import ET, session_label, vwap_for  # noqa: E402

# Shapes OBSERVED from /api/v3/reality/market/states and /calendar on 2026-09-16.
STATES = {"market": "US", "stateList": [
    {"state": "pre_market", "startTime": "04:00", "endTime": "09:30"},
    {"state": "regular", "startTime": "09:30", "endTime": "16:00"},
    {"state": "after_hours", "startTime": "16:00", "endTime": "20:00"},
    {"state": "overnight", "startTime": "20:00", "endTime": "04:00"}]}
CAL = {"timeZone": "EST", "regularConfig": ["SATURDAY", "SUNDAY"],
       "specificConfig": [{"startTime": "2026-09-06 20:00", "endTime": "2026-09-07 20:00"}]}


@pytest.mark.parametrize("when, label", [
    (dt.datetime(2026, 9, 16, 15, 17, tzinfo=ET), "regular"),
    (dt.datetime(2026, 9, 16, 16, 0, tzinfo=ET), "after_hours"),
    (dt.datetime(2026, 9, 16, 21, 0, tzinfo=ET), "overnight"),
    (dt.datetime(2026, 9, 17, 3, 59, tzinfo=ET), "overnight"),
    (dt.datetime(2026, 9, 17, 4, 0, tzinfo=ET), "pre_market"),
    (dt.datetime(2026, 9, 19, 12, 0, tzinfo=ET), "weekend"),
    (dt.datetime(2026, 9, 7, 12, 0, tzinfo=ET), "holiday"),      # Labor Day window
    (dt.datetime(2026, 9, 7, 20, 0, tzinfo=ET), "overnight"),    # window end is exclusive
])
def test_session_label_from_live_config(when, label):
    assert session_label(when, STATES, CAL) == label


def test_vwap_walks_levels_and_returns_none_when_unfillable():
    levels = [[100.0, 10.0], [101.0, 10.0]]
    assert vwap_for(levels, 1000) == pytest.approx(100.0)
    assert vwap_for(levels, 1500) == pytest.approx(1500 / (10 + 500 / 101))
    assert vwap_for(levels, 5000) is None

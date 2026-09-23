import datetime as dt
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import plan_v3_forward as plan  # noqa: E402
import record_schedule  # noqa: E402
import score_forward_v3 as score  # noqa: E402

UTC = dt.timezone.utc


def _event(event_id="rX-2026-09-28-1", ex="2026-09-28", gross="0.50", basis="GROSS", tier=2):
    return dict(event_id=event_id, symbol=event_id.split("-")[0], spot_symbol=event_id.split("-")[0].upper() + "USDT",
                exchange_ex_date=ex, event_type="CASH_DIV", cash_dividend_basis=basis, basis_tier=tier,
                gross_dividend_per_share=gross, instrument_snapshot={"taker_fee": "0.001"})


def test_monday_ex_date_sells_before_friday_close():
    w = plan.window(dt.date(2026, 9, 28))
    assert w["sell_cutoff"] == "2026-09-25T20:00:00-04:00"
    assert w["start"] == "2026-09-25T20:00:00+00:00"
    assert w["end"] == "2026-09-28T14:30:00+00:00"
    assert plan.window(dt.date(2026, 9, 30))["sell_cutoff"] == "2026-09-29T20:00:00-04:00"


def test_selection_is_mechanical_on_yield_basis_and_horizon():
    ledger = [_event("rA-2026-09-28-1", gross="0.70"),                    # 70 bp at 100 -> in
              _event("rB-2026-09-28-1", gross="0.60"),                    # 60 bp -> below threshold
              _event("rC-2026-09-28-1", gross="2.00", basis="UNRESOLVED", tier=None),
              _event("rD-2026-12-01-1", ex="2026-12-01", gross="2.00"),   # beyond horizon
              _event("rE-2026-09-23-1", ex="2026-09-23", gross="2.00")]   # not after plan date
    prices = {e["event_id"]: 100.0 for e in ledger}
    chosen = plan.select(ledger, prices, dt.date(2026, 9, 23))
    assert [t["event_id"] for t in chosen] == ["rA-2026-09-28-1"]
    g = plan.groups(chosen)
    assert g[0]["label"] == "v3_20260928_RA" and g[0]["symbols"] == ["RAUSDT"]


def test_only_open_windows_are_recorded():
    p = {"groups": [dict(label="a", start="2026-09-24T20:00:00+00:00", end="2026-09-25T14:30:00+00:00"),
                    dict(label="b", start="2026-09-25T20:00:00+00:00", end="2026-09-28T14:30:00+00:00")]}
    now = dt.datetime(2026, 9, 25, 14, 29, tzinfo=UTC)
    assert [g["label"] for g in record_schedule.active_groups(p, now)] == ["a"]
    assert record_schedule.active_groups(p, dt.datetime(2026, 9, 25, 14, 30, tzinfo=UTC)) == []


def test_frozen_decision_is_latest_before_cutoff(tmp_path):
    for stamp, decided, verdict in (("a", "2026-09-24T23:30:00+00:00", "HOLD"),
                                    ("b", "2026-09-25T23:30:00+00:00", "NO_SIGNAL"),
                                    ("c", "2026-09-26T01:00:00+00:00", "EXIT")):
        pd.DataFrame([dict(event_id="rX-2026-09-28-1", decided_at=decided, notional_usd=1000,
                           verdict=verdict)]).to_csv(tmp_path / f"signals_v3_{stamp}.csv", index=False)
    cutoff = dt.datetime(2026, 9, 26, 0, 0, tzinfo=UTC)   # Friday 20:00 ET
    rows, name = score.frozen_decision("rX-2026-09-28-1", cutoff, sorted(tmp_path.glob("*.csv")))
    assert name == "signals_v3_b.csv" and rows.verdict.iloc[0] == "NO_SIGNAL"


@pytest.mark.parametrize("low, high, expected", [(0.01, 0.2, "EXIT"), (-0.2, -0.01, "HOLD"),
                                                 (-0.1, 0.1, "ENTITLEMENT_AMBIGUOUS"), (None, 0.1, "NO_SIGNAL")])
def test_realised_verdict(low, high, expected):
    assert score.realised_verdict(low, high) == expected


def _sample(ts, last, bid, ask):
    row = {"ts": ts.isoformat(), "ticker": {"lastPrice": str(last), "bid1Price": str(bid), "ask1Price": str(ask),
                                            "bid1Size": "1000", "ask1Size": "1000"},
           "orderbook": {"bids": [[str(bid), "1000"]], "asks": [[str(ask), "1000"]]}}
    return ts, row


def test_score_event_uses_frozen_entitlement(tmp_path):
    group = dict(sell_cutoff="2026-09-25T20:00:00-04:00", rung_0400="2026-09-28T04:00:00-04:00")
    target = dict(event_id="rX-2026-09-28-1", spot_symbol="RXUSDT", ex_date="2026-09-28")
    pre_ts = dt.datetime(2026, 9, 25, 23, 59, tzinfo=UTC)
    post_ts = dt.datetime(2026, 9, 28, 8, 0, tzinfo=UTC)
    rows = [_sample(pre_ts, 100.0, 99.99, 100.01), _sample(post_ts, 98.0, 97.99, 98.01)]
    pd.DataFrame([dict(event_id=target["event_id"], decided_at="2026-09-25T23:30:00+00:00", notional_usd=n,
                       verdict="HOLD", reason="", entitlement_tier="E1_DOCUMENTED_PRECEDENT",
                       w_low=0.30, w_high=0.30) for n in (1000, 5000, 25000)]).to_csv(tmp_path / "signals_v3_x.csv", index=False)
    result = score.score_event(target, group, _event(gross="2.00"), rows, sorted(tmp_path.glob("*.csv")),
                               max_lateness_seconds=180)
    assert result["complete"] and result["realised_pdr"] == pytest.approx(1.0)
    first = result["notionals"][0]
    # A 2% dividend fully priced in: keeping 70% makes EXIT win by 0.6 minus about 0.2 of cost.
    assert first["frozen_verdict"] == "HOLD" and first["realised_verdict"] == "EXIT"
    assert first["realised_edge_keep_gross"] < 0 < first["realised_edge_keep_70pct"]
    # The modeled-cost view is always present and uses the scorecard's 25 bps assumption.
    modeled = result["modeled"]
    assert modeled["label"] == "MODELED_EXECUTION"
    assert modeled["cost_per_share"] == pytest.approx(100.0 * (2 * 0.001 + 0.0025))
    assert modeled["realised_verdict"] == "EXIT"   # 2.0 drop - 1.4 kept - 0.45 cost > 0


def test_depth_sampler_adds_scheduled_symbols(tmp_path, monkeypatch):
    import depth_snapshot
    schedule = tmp_path / "s.json"
    schedule.write_text(json.dumps({"groups": [{"symbols": ["RZZZUSDT"]}]}))
    symbols = depth_snapshot.sampled_symbols(schedule)
    assert "RZZZUSDT" in symbols and len(symbols) > 1
    assert "RZZZUSDT" not in depth_snapshot.sampled_symbols(tmp_path / "missing.json")

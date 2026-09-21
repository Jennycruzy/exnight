import pandas as pd
import pytest

from exnight.costs import latest_samples
from exnight.strategy import estimate, summarize_forward_decisions, verdict_row


def _samples(**over):
    cols = dict(levels_ask=5, levels_bid=5, ticker_spread_bp=None, ticker_ask1_notional=None, ticker_bid1_notional=None,
                **{f"{s}_walk_bp_{n}": None for s in ("buy", "sell") for n in (1000, 5000, 25000)})
    rows = [dict(cols, ts="2026-09-16T20:30:00+00:00", session="after_hours", symbol="RXUSDT", book_source="public_book",
                 sell_walk_bp_1000=10.0, sell_walk_bp_5000=10.0),
            dict(cols, ts="2026-09-17T00:11:00+00:00", session="overnight", symbol="RXUSDT", book_source="public_book",
                 buy_walk_bp_1000=10.0, buy_walk_bp_5000=10.0)]
    return latest_samples(pd.DataFrame(rows))


BASE = dict(event_id="rX-2026-09-21-1", symbol="rX", spot="RXUSDT", ex_date="2026-09-21", gross=1.0, net=0.7,
            basis="GROSS", eligible=False, price=100.0, price_label="test", fee=0.001, fee_label="test",
            drop_se=0.1, drop_label="test", notional=1000)


def test_hold_when_lower_bound_does_not_beat_net_plus_cost():
    r = verdict_row(**BASE, drop_ratio=0.66, samples=_samples())
    projected_buy = 100 - 0.66
    cost = 0.001 * (100 + projected_buy) + 0.001 * 100 + 0.001 * projected_buy
    assert r["cost_per_share"] == pytest.approx(cost)
    assert r["exit_edge_lower"] == pytest.approx((0.66 - 0.2) * 1.0 - 0.7 - cost)
    assert r["verdict"] == "HOLD" and r["buy"].startswith("SUPPRESSED")


def test_exit_only_on_lower_bound():
    r = verdict_row(**BASE, drop_ratio=1.5, samples=_samples())
    projected_buy = 100 - 1.5
    cost = 0.001 * (100 + projected_buy) + 0.001 * 100 + 0.001 * projected_buy
    assert r["exit_edge_lower"] == pytest.approx(1.3 - 0.7 - cost) and r["verdict"] == "EXIT"
    r = verdict_row(**dict(BASE, drop_se=0.5), drop_ratio=1.5, samples=_samples())   # 1.5 - 1.0 = 0.5 < 1.1
    assert r["verdict"] == "HOLD"


def test_ex_post_cost_uses_distinct_buy_price():
    r = verdict_row(**BASE, drop_ratio=0.2, samples=_samples(), buy_price=80.0)
    assert r["cost_per_share"] == pytest.approx(0.36)
    assert r["buy_price"] == 80.0


def test_no_signal_paths():
    r = verdict_row(**dict(BASE, basis="UNRESOLVED", gross=None, net=None), drop_ratio=0.66, samples=_samples())
    assert r["verdict"] == "NO_SIGNAL" and "UNRESOLVED" in r["reason"]
    r = verdict_row(**dict(BASE, notional=25000), drop_ratio=0.66, samples=_samples())
    assert r["verdict"] == "NO_SIGNAL" and "sell:" in r["reason"] and "buy:" in r["reason"]
    r = verdict_row(**dict(BASE, price=None), drop_ratio=0.66, samples=_samples())
    assert r["reason"] == "no reference price"


def test_buy_needs_eligibility_and_positive_edge():
    r = verdict_row(**dict(BASE, eligible=True), drop_ratio=0.1, samples=_samples())
    projected_buy = 100 - 0.1
    cost = 0.001 * (100 + projected_buy) + 0.001 * 100 + 0.001 * projected_buy
    assert r["buy"] == "BUY" and r["buy_edge_point"] == pytest.approx(0.7 - 0.1 - cost)
    r = verdict_row(**dict(BASE, eligible=True), drop_ratio=0.66, samples=_samples())
    assert r["buy"] is None


def test_estimate_requires_slope():
    s = {"floor_None": {"rungs": {"overnight_2000": {"slope": {"pdr": 0.66, "se": 0.09, "n": 125}}}}}
    assert estimate(s, "floor_None")["pdr_hat"] == 0.66
    with pytest.raises(ValueError):
        estimate({"x": {"rungs": {"overnight_2000": {"slope": {"pdr": None, "se": None, "n": 2}}}}}, "x")


def test_manifest_summary_includes_every_forward_event():
    signals = pd.DataFrame([
        {"event_id": "rVST-2026-09-21-1", "notional_usd": 5000, "verdict": "NO_SIGNAL"},
        {"event_id": "rSATA-2026-09-21-1", "notional_usd": 1000, "verdict": "HOLD"},
        {"event_id": "rVST-2026-09-21-1", "notional_usd": 1000, "verdict": "HOLD"},
        {"event_id": "rSATA-2026-09-21-1", "notional_usd": 5000, "verdict": "NO_SIGNAL"},
    ])
    assert summarize_forward_decisions(signals) == {
        "rSATA-2026-09-21-1": {"1000": "HOLD", "5000": "NO_SIGNAL"},
        "rVST-2026-09-21-1": {"1000": "HOLD", "5000": "NO_SIGNAL"},
    }


def test_frozen_rule_loads_and_rejects_drift(tmp_path):
    import json
    from pathlib import Path
    from exnight.strategy import load_rule
    rule = json.loads(Path("strategy/strategy_v1.json").read_text())
    assert load_rule(Path("strategy/strategy_v1.json"))["rung"] == "premarket_0400"
    for key, bad in (("z", 1.5), ("withholding_high", "0.35"), ("rung", "open_1200"), ("notionals_usd", [1000])):
        p = tmp_path / "r.json"
        p.write_text(json.dumps(dict(rule, **{key: bad})))
        with pytest.raises(ValueError):
            load_rule(p)

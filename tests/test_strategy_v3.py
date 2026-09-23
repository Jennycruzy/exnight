import datetime as dt
import math
from decimal import Decimal

import pandas as pd
import pytest

from exnight import strategy_v3 as v3

UTC = dt.timezone.utc


def _prior(symbol="rJEPQ", ex=dt.date(2026, 8, 3), primary=dt.datetime(2026, 9, 23, tzinfo=UTC),
           content=dt.datetime(2026, 8, 25, 4, tzinfo=UTC)):
    return [dict(symbol=symbol, ex_date=ex, amount=Decimal("0.70497"), source_key="dividends_89_2026_09_23",
                 available={"primary": primary, "content_bound": content})]


def test_rule_file_matches_code():
    rule = v3.load_rule()
    assert rule["amendment_policy"].endswith("strategy_v4.json")


def test_exit_requires_documented_entitlement():
    # Perfect repricing, 2% yield, 20 bp cost: wins only when the holder keeps 70%.
    common = dict(pdr=1.0, se=0.0, gross=2.0, price=100.0, cost_per_share=0.20)
    assert v3.decide(**common, w_low=0.30, w_high=0.30)["verdict"] == "EXIT"
    uncertain = v3.decide(**common, w_low=0.0, w_high=0.30)
    assert uncertain["verdict"] == "NO_SIGNAL" and uncertain["reason"] == "ENTITLEMENT_UNCERTAIN"


def test_overshoot_earns_no_credit():
    # pdr - 2se = 1.6 would clear full withholding-free entitlement; the cap removes that.
    d = v3.decide(pdr=1.8, se=0.1, gross=1.0, price=100.0, cost_per_share=0.10, w_low=0.0, w_high=0.30)
    assert d["lower_ratio"] == 1.0
    assert d["verdict"] == "NO_SIGNAL"


def test_small_dividend_holds_even_when_documented():
    d = v3.decide(pdr=1.0, se=0.0, gross=0.05, price=100.0, cost_per_share=0.20, w_low=0.30, w_high=0.30)
    assert d["verdict"] == "HOLD"
    assert d["breakeven_yield"] == pytest.approx(0.002 / 0.30)


def test_breakeven_is_infinite_when_lower_bound_below_retained_share():
    d = v3.decide(pdr=0.9, se=0.1, gross=1.0, price=50.0, cost_per_share=0.05, w_low=0.30, w_high=0.30)
    assert math.isinf(d["breakeven_yield"]) and d["verdict"] == "HOLD"


def test_invalid_inputs_fail_loudly():
    with pytest.raises(ValueError):
        v3.decide(pdr=float("nan"), se=0.1, gross=1.0, price=50.0, cost_per_share=0.05, w_low=0.3, w_high=0.3)
    with pytest.raises(ValueError):
        v3.decide(pdr=1.0, se=0.1, gross=1.0, price=50.0, cost_per_share=0.05, w_low=0.3, w_high=0.0)


def test_entitlement_uses_only_notices_available_before_decision():
    prior = _prior()
    before = dt.datetime(2026, 9, 1, tzinfo=UTC)
    after = dt.datetime(2026, 9, 24, tzinfo=UTC)
    assert v3.entitlement("rJEPQ", dt.date(2026, 9, 1), before, prior)["tier"] == "E0_RANGE"
    assert v3.entitlement("rJEPQ", dt.date(2026, 9, 1), before, prior, "content_bound")["tier"] == "E1_DOCUMENTED_PRECEDENT"
    documented = v3.entitlement("rJEPQ", dt.date(2026, 10, 1), after, prior)
    assert (documented["w_low"], documented["w_high"]) == (0.30, 0.30)
    # A notice about this same event, or another symbol, is never a precedent.
    assert v3.entitlement("rJEPQ", dt.date(2026, 8, 3), after, prior)["tier"] == "E0_RANGE"
    assert v3.entitlement("rQQQI", dt.date(2026, 10, 1), after, prior)["tier"] == "E0_RANGE"


def test_precedent_requires_notice_amount_equal_to_resolved_gross():
    ledger = [dict(symbol="rNXPI", exchange_ex_date="2026-06-24", event_type="CASH_DIV", cash_dividend_basis="GROSS",
                   basis_tier=2, gross_dividend_per_share="1.014"),
              dict(symbol="rKO", exchange_ex_date="2026-06-15", event_type="CASH_DIV", cash_dividend_basis="GROSS",
                   basis_tier=1, gross_dividend_per_share="0.53")]
    rows = [dict(symbol="rNXPI", ex_date=dt.date(2026, 6, 24), amount=Decimal("0.8619")),
            dict(symbol="rKO", ex_date=dt.date(2026, 6, 15), amount=Decimal("0.53")),
            dict(symbol="rXYZ", ex_date=dt.date(2026, 6, 15), amount=Decimal("0.10"))]
    assert [r["symbol"] for r in v3.precedents(ledger, rows)] == ["rKO"]


def test_saved_notices_parse_with_provable_availability():
    rows = v3.notice_rows()
    assert sum(r["source_key"] == "dividends_2026_07_24" for r in rows) == 63
    n89 = [r for r in rows if r["source_key"] == "dividends_89_2026_09_23"]
    assert len(n89) == 89
    # The displayed 24 July date cannot be the publication time of a list with August payments.
    assert n89[0]["available"]["content_bound"].date() >= dt.date(2026, 8, 25)
    assert n89[0]["available"]["primary"] == dt.datetime(2026, 9, 23, 12, 34, 33, tzinfo=UTC)


def test_estimate_uses_only_outcomes_observed_before_decision():
    rows = []
    for i in range(20):
        ts = pd.Timestamp("2026-07-01T08:00:00Z") + pd.Timedelta(days=i)
        y = 0.002 + 0.0005 * (i % 5)
        rows.append(dict(event_id=f"e{i}", symbol=f"r{i}", ex_date=ts.date(), decision_ts=ts - pd.Timedelta(hours=12),
                         p_pre=100.0, p_post=100.0 * (1 - y), outcome_ts=ts, gross=100.0 * y, fee_rate=0.001))
    frame = pd.DataFrame(rows)
    with pytest.raises(RuntimeError):
        v3.estimate(frame, dt.datetime(2026, 7, 10, tzinfo=UTC))
    est = v3.estimate(frame, dt.datetime(2026, 7, 18, tzinfo=UTC))
    assert est["n"] == 17 and est["pdr"] == pytest.approx(1.0)

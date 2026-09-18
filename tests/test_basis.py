import datetime as dt
from decimal import Decimal

import pytest

from exnight.basis import (IssuerSources, _match, parse_perp_dividend_notice_2026_09_16, resolve_event)
from exnight.events import CorporateAction, EventType
from exnight.strategy import verdict_row
from tests.test_strategy import BASE, _samples

EX = dt.date(2026, 9, 21)
PERP = [dict(underlying="AVGO", amount=Decimal("0.65"), ex_date=EX, source_key="perp_test")]


class FakeSources(IssuerSources):
    def __init__(self, *, declared=None, realised=None, calendar=None):
        super().__init__(offline=True)
        self.declared, self.realised, self.calendar = declared, realised, calendar

    def nasdaq_declared(self, ticker):
        return self.declared

    def yahoo_realised(self, ticker, ex_date):
        return self.realised

    def yahoo_calendar(self, ticker):
        return self.calendar


def _event(amount="0.65", underlying="AVGO", ex=EX):
    return CorporateAction(
        event_id=f"r{underlying}-{ex.isoformat()}-1", symbol=f"r{underlying}", underlying=underlying,
        spot_symbol=f"R{underlying}USDT", event_type=EventType.CASH_DIV, announcement_date=None,
        exchange_ex_date=ex, exchange_record_date=None, bitget_snapshot_time=None, payment_date=None,
        gross_dividend_per_share=None, withholding_rate=None, net_dividend_per_share=None,
        eligibility_verified=False, weekend_list_2026_07_17=None, source_key="test",
        source_url="https://example.invalid", label="OBSERVED",
        cash_dividend_per_share=Decimal(amount), cash_dividend_basis="UNRESOLVED",
    )


def test_perp_notice_parses_both_pairs():
    rows = parse_perp_dividend_notice_2026_09_16()
    assert {(r["underlying"], str(r["amount"]), r["ex_date"]) for r in rows} == {
        ("VST", "0.23", EX), ("AVGO", "0.65", EX)}


def test_match_allows_source_rounding_only():
    assert _match(Decimal("0.0493"), Decimal("0.049"))          # Yahoo prints 3 dp
    assert _match(Decimal("0.013749"), Decimal("0.014"))
    assert not _match(Decimal("0.8619"), Decimal("1.014"))      # NXPI: home-country net
    assert not _match(Decimal("0.874889"), Decimal("1.107"))    # TSM
    assert not _match(Decimal("0.65"), Decimal("0.66"))


def test_issuer_declared_match_is_tier_2():
    src = FakeSources(declared=[dict(ex_date=EX, amount=Decimal("0.65"), declaration_date="09/01/2026", type="Cash")])
    e, rec = resolve_event(_event(), src, PERP)
    assert e.cash_dividend_basis == "GROSS" and e.basis_tier == 2 and rec["tier"] == 2
    assert e.gross_dividend_per_share == Decimal("0.65")
    assert e.net_dividend_verified is False
    assert (e.withholding_rate_low, e.withholding_rate, e.withholding_rate_high) == (Decimal("0"), Decimal("0.30"), Decimal("0.30"))
    assert any("nasdaq_declared" in x for x in e.basis_evidence) and any("perp_test" in x for x in e.basis_evidence)


def test_issuer_amount_mismatch_stays_unresolved_despite_bitget_corroboration():
    # Bitget's Reality feed and its perp notice both say 0.8619; the issuer declared 1.014.
    perp = [dict(underlying="NXPI", amount=Decimal("0.8619"), ex_date=EX, source_key="perp_test")]
    src = FakeSources(declared=[dict(ex_date=EX, amount=Decimal("1.014"), declaration_date="x", type="Cash")],
                      calendar=EX, realised=[dict(ex_date=EX - dt.timedelta(days=90), amount=Decimal("0.8619"))])
    e, rec = resolve_event(_event("0.8619", "NXPI"), src, perp)
    assert e.cash_dividend_basis == "UNRESOLVED" and rec["reason"].startswith("amount conflict")
    assert "ratio 0.850" in rec["reason"]


def test_issuer_row_on_other_date_does_not_resolve():
    src = FakeSources(declared=[dict(ex_date=EX + dt.timedelta(days=7), amount=Decimal("0.65"), declaration_date="x", type="Cash")])
    e, rec = resolve_event(_event(), src, [])
    assert e.cash_dividend_basis == "UNRESOLVED" and "no issuer row at ex-date" in rec["reason"]


def test_tier_3_needs_all_three_corroborations():
    prior = [dict(ex_date=EX - dt.timedelta(days=91), amount=Decimal("0.229"))]
    perp = [dict(underlying="VST", amount=Decimal("0.23"), ex_date=EX, source_key="perp_test")]
    e, rec = resolve_event(_event("0.23", "VST"), FakeSources(realised=prior, calendar=EX), perp)
    assert e.cash_dividend_basis == "GROSS" and e.basis_tier == 3
    # missing first-party corroboration (rCRM on 2026-09-17)
    e, rec = resolve_event(_event("0.23", "VST"), FakeSources(realised=prior, calendar=EX), [])
    assert e.cash_dividend_basis == "UNRESOLVED" and "first-party amount corroboration" in rec["reason"]
    # issuer has not announced the date
    e, rec = resolve_event(_event("0.23", "VST"), FakeSources(realised=prior, calendar=None), perp)
    assert e.cash_dividend_basis == "UNRESOLVED" and "issuer announced ex-date" in rec["reason"]
    # amount changed from the prior period
    e, rec = resolve_event(_event("0.25", "VST"), FakeSources(realised=prior, calendar=EX),
                           [dict(underlying="VST", amount=Decimal("0.25"), ex_date=EX, source_key="perp_test")])
    assert e.cash_dividend_basis == "UNRESOLVED" and "prior-period amount" in rec["reason"]


def test_tier_1_rows_are_left_alone():
    e = _event().model_copy(update=dict(
        cash_dividend_basis="GROSS", gross_dividend_per_share=Decimal("0.65"), withholding_rate=Decimal("0.30"),
        net_dividend_per_share=Decimal("0.455"), basis_tier=1, net_dividend_verified=True, basis_evidence=["notice"]))
    out, rec = resolve_event(e, FakeSources(declared=[dict(ex_date=EX, amount=Decimal("0.60"), type="Cash")]), PERP)
    assert out.basis_tier == 1 and out.net_dividend_verified and rec["reason"].startswith("tier 1")


# --- net-range verdicts -------------------------------------------------------------

def _row(drop_ratio, **over):
    kw = dict(BASE, net=0.7, net_low=0.7, net_high=1.0, net_verified=False)
    kw.update(over)
    return verdict_row(**kw, drop_ratio=drop_ratio, samples=_samples())


def test_exit_only_when_positive_at_highest_net():
    # The buy leg uses the projected post-event price, so cost varies slightly with drop.
    r = _row(1.7)                       # 1.5 - 1.0 - 0.4 = +0.1 at net_high -> EXIT
    assert r["verdict"] == "EXIT" and r["exit_edge_lower_net_high"] == pytest.approx(0.1034)
    r = _row(1.5)                       # +0.2 at net_low, -0.1 at net_high -> no verdict
    assert r["verdict"] == "NO_SIGNAL" and r["reason"].startswith("net entitlement unresolved")
    assert r["exit_edge_lower_net_low"] == pytest.approx(0.203) and r["exit_edge_lower_net_high"] == pytest.approx(-0.097)


def test_hold_only_when_not_positive_at_lowest_net():
    r = _row(1.2)                       # 1.0 - 0.7 - 0.4 = -0.1 at net_low -> HOLD
    assert r["verdict"] == "HOLD" and r["exit_edge_lower_net_low"] == pytest.approx(-0.0976)
    assert r["exit_edge_lower_zero_net"] == pytest.approx(0.6024)   # would EXIT if fully withheld; HOLD depends on entitlement
    r = _row(0.5)
    assert r["verdict"] == "HOLD" and r["exit_edge_lower_zero_net"] < 0   # HOLD regardless of withholding


def test_verified_net_collapses_to_the_old_rule():
    r = verdict_row(**BASE, drop_ratio=1.5, samples=_samples())
    assert r["net_low"] == r["net_high"] == 0.7 and r["verdict"] == "EXIT"


def test_range_must_bracket_base():
    r = _row(1.5, net=0.7, net_low=0.8, net_high=1.0)
    assert r["verdict"] == "NO_SIGNAL" and "bracket" in r["reason"]

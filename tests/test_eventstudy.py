import datetime as dt
from decimal import Decimal

from exnight.eventstudy import run
from exnight.events import CorporateAction, EventType


class EmptyUniverse:
    def rtokens(self):
        return {}


def _event(*, basis="UNRESOLVED", event_type=EventType.CASH_DIV):
    return CorporateAction(
        event_id="rTEST-2026-07-06-1",
        symbol="rTEST",
        underlying="TEST",
        spot_symbol="RTESTUSDT",
        event_type=event_type,
        announcement_date=None,
        exchange_ex_date=dt.date(2026, 7, 6),
        exchange_record_date=None,
        bitget_snapshot_time=None,
        payment_date=None,
        gross_dividend_per_share=Decimal("0.15") if basis == "GROSS" else None,
        withholding_rate=Decimal("0.30") if basis == "GROSS" else None,
        net_dividend_per_share=Decimal("0.105") if basis == "GROSS" else None,
        eligibility_verified=False,
        weekend_list_2026_07_17=False,
        source_key="test",
        source_url="https://example.invalid",
        label="OBSERVED",
        cash_dividend_per_share=Decimal("0.15") if event_type is EventType.CASH_DIV else None,
        cash_dividend_basis=basis,
        adjustment_ratio=Decimal("2") if event_type is EventType.SPLIT else None,
    )


def test_run_records_unresolved_cash_basis_without_computing():
    result = run([_event()], EmptyUniverse())[0]

    assert result.usable is False
    assert result.gross_dividend is None
    assert result.exclusion_reason == "cash amount basis is UNRESOLVED; gross basis required"


def test_run_records_missing_live_symbol_once():
    result = run([_event(basis="GROSS")], EmptyUniverse())[0]

    assert result.usable is False
    assert result.exclusion_reason == "symbol not in live universe"


def test_run_excludes_non_cash_actions():
    result = run([_event(event_type=EventType.SPLIT)], EmptyUniverse())[0]

    assert result.usable is False
    assert result.exclusion_reason == "event type SPLIT is not a cash dividend"

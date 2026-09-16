import datetime as dt
from decimal import Decimal

from exnight.eventstudy import run
from exnight.events import CorporateAction, EventType


class EmptyUniverse:
    def rtokens(self):
        return {}

    def market_calendar(self):
        return {"timeZone": "EST", "regularConfig": ["SATURDAY", "SUNDAY"], "specificConfig": []}


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


def test_live_calendar_marks_full_day_closures_and_weekends():
    import datetime as dt
    from exnight.eventstudy import MarketCalendar, prev_us_trading_day
    # Shape OBSERVED from /api/v3/reality/market/calendar on 2026-09-16
    cal = MarketCalendar.from_reality({"timeZone": "EST", "regularConfig": ["SATURDAY", "SUNDAY"], "specificConfig": [
        {"remark": "", "startTime": "2026-07-02 20:00", "endTime": "2026-07-03 20:00"},
        {"remark": "", "startTime": "2026-09-06 20:00", "endTime": "2026-09-07 20:00"}]})
    assert cal.closed_dates == {dt.date(2026, 7, 3), dt.date(2026, 9, 7)}
    assert prev_us_trading_day(dt.date(2026, 7, 6), cal) == dt.date(2026, 7, 2)   # Mon after the Fri closure
    assert prev_us_trading_day(dt.date(2026, 9, 8), cal) == dt.date(2026, 9, 4)   # Tue after Labor Day
    assert prev_us_trading_day(dt.date(2026, 6, 23), cal) == dt.date(2026, 6, 22)
    # an early close (window not covering 09:30-16:00) is not a closed day
    cal2 = MarketCalendar.from_reality({"regularConfig": ["SATURDAY", "SUNDAY"],
                                        "specificConfig": [{"startTime": "2026-11-27 13:00", "endTime": "2026-11-27 20:00"}]})
    assert cal2.closed_dates == frozenset()

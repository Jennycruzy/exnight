import pandas as pd

from exnight.confounders import FLAG_LABELS, build


def _result(**kw):
    base = dict(event_id="rX-2026-06-24-1", symbol="rX", underlying="X", ex_date="2026-06-24", usable=True,
                open_time="2026-06-10T14:00:00+00:00", p_pre_staleness_h=0.02, dividend_yield_pct=0.3,
                ex_date_is_monday=False, market_move_pct={"overnight_2000": 0.1},
                underlying_div_check="Yahoo agrees on ex-date and amount (to 3 dp)")
    base.update(kw); return base


def _reality(*rows):
    out = []
    for sym, ex, typ, amt in rows:
        out.append(dict(symbol=sym, exchange_ex_date=ex, event_type=typ, cash_dividend_per_share=amt))
    return out


NOTICE = [dict(event_id="rX-2026-06-24-1", gross_dividend_per_share="0.8619")]


def test_clean_event_has_no_flags(monkeypatch):
    monkeypatch.setattr("exnight.confounders.yahoo_meta", lambda t: {"instrumentType": "EQUITY", "longName": "X Inc."})
    df = build([_result()], NOTICE, _reality(("rX", "2026-06-24", "CASH_DIV", "0.8619")))
    assert df.clean.iloc[0] and df.n_flags.iloc[0] == 0 and df.reality_matched.iloc[0]
    assert df.listing_age_days.iloc[0] == 14


def test_gross_basis_conflict_but_not_rounding(monkeypatch):
    monkeypatch.setattr("exnight.confounders.yahoo_meta", lambda t: {})
    df = build([_result()], NOTICE, _reality(("rX", "2026-06-24", "CASH_DIV", "1.014")))
    assert df.gross_basis_conflict.iloc[0] and abs(df.notice_over_reality.iloc[0] - 0.85) < 1e-9
    df = build([_result()], NOTICE, _reality(("rX", "2026-06-24", "CASH_DIV", "0.862")))
    assert not df.gross_basis_conflict.iloc[0]


def test_adjacent_noncash_relisted_and_name_hint(monkeypatch):
    monkeypatch.setattr("exnight.confounders.yahoo_meta",
                        lambda t: {"instrumentType": "ETF", "longName": "Direxion Daily X Bull 3X Shares"})
    reality = _reality(("rX", "2026-06-24", "CASH_DIV", "1.014"), ("rX", "2026-06-25", "CASH_DIV", "1.014"),
                       ("rX", "2026-07-15", "REVERSE_SPLIT", None))
    df = build([_result(open_time="2026-07-15T14:00:00+00:00", ex_date_is_monday=True,
                        market_move_pct={"overnight_2000": -1.5}, dividend_yield_pct=2.5, p_pre_staleness_h=30,
                        underlying_div_check="AMOUNT MISMATCH")], NOTICE, reality)
    r = df.iloc[0]
    for k in FLAG_LABELS:
        assert r[k], k
    assert r.nearest_cash_days == 1 and r.nearest_noncash_days == 21 and not r.clean


def test_unusable_is_never_clean(monkeypatch):
    monkeypatch.setattr("exnight.confounders.yahoo_meta", lambda t: {})
    df = build([_result(usable=False)], NOTICE, _reality(("rX", "2026-06-24", "CASH_DIV", "0.8619")))
    assert not df.clean.iloc[0] and df.n_flags.iloc[0] == 0

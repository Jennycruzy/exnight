"""C2: the event study.

Measurement points, and why
---------------------------
Bitget rTokens trade continuously on weekdays (24/5) and the sample's ex-dates are all
weekdays, so there is no single "open" at which the dividend is priced out. The engine
therefore takes one pre-event price and a *ladder* of post-event prices, and reports the
price-drop ratio at each rung. The ladder shows *when* the overnight venue reprices, which
is itself a result.

  P_pre        last 1m close strictly before 20:00 ET on the last US trading day before the
               ex-date. That is the US after-hours close: the last moment the token is
               unambiguously cum-dividend under exchange rules, and the moment Bitget's own
               stock perps settle dividends (support article 12560603895292). Staleness is
               recorded; a P_pre older than 72h is rejected.
  P_post[k]    first 1m close at or after each rung, all on the ex-date in ET:
               20:00 ET (D-1)  start of the overnight session
               04:00 ET        US pre-market opens
               09:30 ET        US regular session opens
               10:00 ET        30 minutes into the session (literature's usual "open" proxy)
               16:00 ET        US close
  In addition, `pdr_literature` uses the academic convention on the rToken itself, close
  before 16:00 ET on D-1 to the first bar at/after 09:30 ET on D, so the rToken and the
  underlying can be compared on the same footing.

  PDR[k] = (P_pre - P_post[k]) / gross_dividend

The underlying's PDR uses the literature convention: (close on D-1 - open on D) / dividend,
from daily bars (third-party source, see underlying.py).

Market adjustment: the same-interval move of RSPYUSDT is subtracted with beta = 1 to give
the abnormal move. This is a stated simplification, not an estimate.

Costs: fee is per event (0.05% promotional rate through 2026-08-31, DOCUMENTED); spread is
the current half-spread measured from the live book because no historical book exists —
it is labelled OBSERVED-NOW and is not the spread at the event. Slippage is set to zero at
a size below the visible top-of-book quantity and the size is reported.

Nothing here defaults. A missing rung is None, and a None propagates to the result row with
the reason attached. No PDR is ever filled with a literature value.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, asdict
from decimal import Decimal
from zoneinfo import ZoneInfo

import pandas as pd

from .candles import fetch_cached, window_for_event
from .events import CorporateAction, EventType
from .market import BitgetPublic, SpotSymbol
from .normalizer import normalize
from .underlying import daily as underlying_daily, dividends as underlying_dividends

ET = ZoneInfo("America/New_York")
RUNGS = [("overnight_2000", -1, dt.time(20, 0)), ("premarket_0400", 0, dt.time(4, 0)),
         ("open_0930", 0, dt.time(9, 30)), ("open_1000", 0, dt.time(10, 0)),
         ("close_1600", 0, dt.time(16, 0))]
MAX_PRE_STALENESS = dt.timedelta(hours=72)
MARKET_PROXY = "rSPY"
PROMO_FEE_END = dt.date(2026, 8, 31)
PROMO_FEE = Decimal("0.0005")   # DOCUMENTED, Academy FAQ: 0.05% through 2026-08-31


# Market closures come from Bitget's live Reality calendar (OBSERVED shape 2026-09-16:
# `specificConfig` windows "YYYY-MM-DD HH:MM" in the "EST" zone, e.g. 2026-07-02 20:00 ->
# 2026-07-03 20:00 for Independence Day observed; `regularConfig` lists the weekend days).
# A closure window that covers a whole 09:30-16:00 session marks that date as a non-trading
# day. There is no hardcoded holiday set; a missing calendar is an error, not a default.
@dataclass(frozen=True)
class MarketCalendar:
    closed_dates: frozenset[dt.date]
    weekend_days: frozenset[int]     # Python weekday numbers
    source: str

    @classmethod
    def from_reality(cls, calendar: dict) -> "MarketCalendar":
        closed: set[dt.date] = set()
        for cfg in calendar.get("specificConfig", []):
            start = dt.datetime.strptime(cfg["startTime"], "%Y-%m-%d %H:%M").replace(tzinfo=ET)
            end = dt.datetime.strptime(cfg["endTime"], "%Y-%m-%d %H:%M").replace(tzinfo=ET)
            day = start.date()
            while day <= end.date():
                s_open = dt.datetime.combine(day, dt.time(9, 30), ET)
                s_close = dt.datetime.combine(day, dt.time(16, 0), ET)
                if start <= s_open and end >= s_close:
                    closed.add(day)
                day += dt.timedelta(days=1)
        names = {"MONDAY": 0, "TUESDAY": 1, "WEDNESDAY": 2, "THURSDAY": 3, "FRIDAY": 4, "SATURDAY": 5, "SUNDAY": 6}
        weekend = frozenset(names[d.upper()] for d in calendar.get("regularConfig", []))
        if not weekend:
            raise ValueError("Reality calendar has no regularConfig weekend days")
        return cls(frozenset(closed), weekend, "OBSERVED /api/v3/reality/market/calendar")

    def is_trading_day(self, d: dt.date) -> bool:
        return d.weekday() not in self.weekend_days and d not in self.closed_dates


def prev_us_trading_day(d: dt.date, cal: MarketCalendar) -> dt.date:
    d -= dt.timedelta(days=1)
    while not cal.is_trading_day(d):
        d -= dt.timedelta(days=1)
    return d


def _at(bars: pd.DataFrame, when: dt.datetime, side: str) -> tuple[float | None, pd.Timestamp | None]:
    if bars.empty:
        return None, None
    if side == "before":
        sel = bars[bars["ts"] < when]   # strictly before: the bar stamped at the cutoff is post
        if sel.empty:
            return None, None
        row = sel.iloc[-1]
    else:
        sel = bars[bars["ts"] >= when]
        if sel.empty:
            return None, None
        row = sel.iloc[0]
    return float(row["close"]), row["ts"]


@dataclass
class EventResult:
    event_id: str
    symbol: str
    underlying: str
    ex_date: str
    gross_dividend: float | None
    net_dividend: float | None
    usable: bool
    exclusion_reason: str | None
    bars_in_window: int
    open_time: str
    p_pre: float | None
    p_pre_ts: str | None
    p_pre_staleness_h: float | None
    dividend_yield_pct: float | None
    p_post: dict
    p_post_ts: dict
    pdr: dict
    market_move_pct: dict
    abnormal_move_pct: dict
    underlying_close_pre: float | None
    underlying_open_ex: float | None
    underlying_pdr: float | None
    underlying_div_check: str
    fee_rate: float
    fee_label: str
    weekend_list_2026_07_17: bool | None
    stale_extremes: int
    pre_trading_day: str = ""
    ex_date_is_monday: bool = False          # ex-date follows a weekend or holiday: the 20:00 rung spans it
    gap_pre_to_2000_min: float | None = None  # minutes between the pre bar and the first post-cutoff bar
    jump_ts: str | None = None               # largest single-bar drop between the cutoff and 09:30 ET (timing only)
    jump_over_dividend: float | None = None
    # literature convention on the rToken: last bar before 16:00 ET on D-1 -> first bar at/after 09:30 ET on D
    p_close_pre: float | None = None
    pdr_literature: float | None = None


def _fee_for(ex_date: dt.date, live: SpotSymbol) -> tuple[Decimal, str]:
    if ex_date <= PROMO_FEE_END:
        return PROMO_FEE, "DOCUMENTED promotional 0.05% through 2026-08-31"
    return live.taker_fee, "OBSERVED live symbol takerFeeRate"


def _instrument_for_event(e: CorporateAction, current: SpotSymbol | None) -> SpotSymbol:
    """Use the event's immutable instrument snapshot, falling back only for old rows."""
    snap = e.instrument_snapshot or {}
    if not snap:
        if current is None:
            raise ValueError(f"{e.event_id}: no current or snapshotted instrument metadata")
        return current
    if e.spot_symbol and snap.get("symbol") != e.spot_symbol:
        raise ValueError(f"{e.event_id}: instrument snapshot symbol does not match ledger")
    try:
        return SpotSymbol(
            symbol=str(snap["symbol"]),
            base_coin=str(snap.get("base_coin", e.symbol)),
            quote_coin=str(snap.get("quote_coin", "USDT")),
            maker_fee=Decimal(str(snap["maker_fee"])),
            taker_fee=Decimal(str(snap["taker_fee"])),
            price_precision=int(snap["price_precision"]),
            quantity_precision=int(snap["quantity_precision"]),
            min_trade_usdt=Decimal(str(snap["min_trade_usdt"])),
            status=str(snap["status"]),
            open_time=dt.datetime.fromisoformat(str(snap["open_time"])),
            symbol_type=str(snap.get("symbol_type", "")),
            is_reality=bool(snap.get("is_reality", False)),
            is_rwa=snap.get("is_rwa"),
            reality_code=e.underlying,
        )
    except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
        raise ValueError(f"{e.event_id}: invalid instrument snapshot: {exc}") from exc


def study_event(api: BitgetPublic, e: CorporateAction, live: SpotSymbol, cal: MarketCalendar,
                proxy: SpotSymbol | None, ledger: list[CorporateAction]) -> EventResult:
    d_pre = prev_us_trading_day(e.exchange_ex_date, cal)
    start, end = window_for_event(d_pre, e.exchange_ex_date)
    raw = fetch_cached(api, e.spot_symbol, "1m", start, end)
    norm = normalize(e.spot_symbol, raw, ledger, live.open_time)
    bars = norm.bars
    gross = float(e.gross_dividend_per_share)
    fee, fee_label = _fee_for(e.exchange_ex_date, live)

    base = dict(event_id=e.event_id, symbol=e.symbol, underlying=e.underlying,
                ex_date=e.exchange_ex_date.isoformat(), gross_dividend=gross,
                net_dividend=float(e.net_dividend_per_share), bars_in_window=len(bars),
                open_time=live.open_time.isoformat(), fee_rate=float(fee), fee_label=fee_label,
                weekend_list_2026_07_17=e.weekend_list_2026_07_17, stale_extremes=len(norm.stale_extremes),
                p_post={}, p_post_ts={}, pdr={}, market_move_pct={}, abnormal_move_pct={},
                underlying_close_pre=None, underlying_open_ex=None, underlying_pdr=None,
                underlying_div_check="not checked", p_pre=None, p_pre_ts=None,
                p_pre_staleness_h=None, dividend_yield_pct=None)

    # ---- underlying baseline (independent of rToken data availability) ----
    try:
        u = underlying_daily(e.underlying, e.exchange_ex_date - dt.timedelta(days=10),
                             e.exchange_ex_date + dt.timedelta(days=3))
        pre_rows = u[u["date"] < e.exchange_ex_date]
        ex_rows = u[u["date"] == e.exchange_ex_date]
        if not pre_rows.empty and not ex_rows.empty:
            c0 = float(pre_rows.iloc[-1]["close"]); o1 = float(ex_rows.iloc[0]["open"])
            base.update(underlying_close_pre=c0, underlying_open_ex=o1,
                        underlying_pdr=(c0 - o1) / gross)
        ydiv = [d for d in underlying_dividends(e.underlying, e.exchange_ex_date - dt.timedelta(days=10),
                                                e.exchange_ex_date + dt.timedelta(days=3))
                if d["ex_date"] == e.exchange_ex_date]
        if not ydiv:
            base["underlying_div_check"] = "Yahoo lists no dividend on this ex-date"
        elif abs(ydiv[0]["amount"] - gross) > 0.0006:   # Yahoo rounds to 3 decimals
            base["underlying_div_check"] = f"AMOUNT MISMATCH: Yahoo {ydiv[0]['amount']} vs Bitget {gross}"
        else:
            base["underlying_div_check"] = "Yahoo agrees on ex-date and amount (to 3 dp)"
    except Exception as ex:  # recorded, never swallowed
        base["underlying_div_check"] = f"underlying fetch failed: {type(ex).__name__}: {ex}"

    if bars.empty:
        return EventResult(usable=False, exclusion_reason=(
            f"no 1m bars at/after openTime {live.open_time:%Y-%m-%d} in window"
            f" ({norm.dropped_before_open} pre-listing bars dropped)"), **base)

    t_pre = dt.datetime.combine(d_pre, dt.time(20, 0), ET)
    p_pre, ts_pre = _at(bars, t_pre, "before")
    if p_pre is None:
        return EventResult(usable=False, exclusion_reason="no bar at or before the pre-event cutoff", **base)
    staleness = t_pre - ts_pre.to_pydatetime()
    base.update(p_pre=p_pre, p_pre_ts=ts_pre.isoformat(), p_pre_staleness_h=staleness.total_seconds() / 3600,
                dividend_yield_pct=100 * gross / p_pre)
    if staleness > MAX_PRE_STALENESS:
        return EventResult(usable=False, exclusion_reason=f"pre-event price stale by {staleness}", **base)

    proxy_bars = None
    if proxy is not None:
        praw = fetch_cached(api, proxy.symbol, "1m", start, end)
        proxy_bars = normalize(proxy.symbol, praw, ledger, proxy.open_time).bars
        m_pre, _ = _at(proxy_bars, t_pre, "before")

    for name, day_off, tod in RUNGS:
        day = d_pre if day_off == -1 else e.exchange_ex_date
        t = dt.datetime.combine(day, tod, ET)
        p, ts = _at(bars, t, "after")
        base["p_post"][name] = p
        base["p_post_ts"][name] = ts.isoformat() if ts is not None else None
        base["pdr"][name] = (p_pre - p) / gross if p is not None else None
        if proxy_bars is not None and p is not None and m_pre:
            m, _ = _at(proxy_bars, t, "after")
            if m is not None:
                mm = 100 * (m / m_pre - 1)
                base["market_move_pct"][name] = mm
                base["abnormal_move_pct"][name] = 100 * (p / p_pre - 1) - mm
                continue
        base["market_move_pct"][name] = None
        base["abnormal_move_pct"][name] = None

    base["pre_trading_day"] = d_pre.isoformat()
    base["ex_date_is_monday"] = (e.exchange_ex_date - d_pre).days > 1
    ts_2000 = base["p_post_ts"].get("overnight_2000")
    if ts_2000:
        base["gap_pre_to_2000_min"] = (pd.Timestamp(ts_2000) - ts_pre).total_seconds() / 60
    # Timing of the repricing: the largest one-bar drop between the cutoff and the US open.
    # Selecting the maximum is biased, so this is reported for *when*, never used as an estimate of how much.
    seg = bars[(bars["ts"] >= ts_pre) & (bars["ts"] <= dt.datetime.combine(e.exchange_ex_date, dt.time(9, 30), ET))]
    if len(seg) >= 2:
        drops = seg["close"].diff()
        i = drops.idxmin()
        base["jump_ts"] = seg.loc[i, "ts"].isoformat()
        base["jump_over_dividend"] = float(-drops[i] / gross)

    p_c, _ = _at(bars, dt.datetime.combine(d_pre, dt.time(16, 0), ET), "before")
    p_o = base["p_post"].get("open_0930")
    base["p_close_pre"] = p_c
    base["pdr_literature"] = (p_c - p_o) / gross if (p_c is not None and p_o is not None) else None

    usable = any(v is not None for v in base["pdr"].values())
    return EventResult(usable=usable,
                       exclusion_reason=None if usable else "no post-event bars on the ex-date", **base)


def _excluded(e: CorporateAction, reason: str) -> EventResult:
    return EventResult(
        event_id=e.event_id, symbol=e.symbol, underlying=e.underlying,
        ex_date=e.exchange_ex_date.isoformat(),
        gross_dividend=(float(e.gross_dividend_per_share)
                        if e.gross_dividend_per_share is not None else None),
        net_dividend=(float(e.net_dividend_per_share)
                      if e.net_dividend_per_share is not None else None),
        usable=False, exclusion_reason=reason,
        bars_in_window=0, open_time="", p_pre=None, p_pre_ts=None, p_pre_staleness_h=None,
        dividend_yield_pct=None, p_post={}, p_post_ts={}, pdr={}, market_move_pct={},
        abnormal_move_pct={}, underlying_close_pre=None, underlying_open_ex=None,
        underlying_pdr=None, underlying_div_check="not checked", fee_rate=0.0, fee_label="n/a",
        weekend_list_2026_07_17=e.weekend_list_2026_07_17, stale_extremes=0)


def run(ledger: list[CorporateAction], api: BitgetPublic | None = None) -> list[EventResult]:
    api = api or BitgetPublic()
    uni = api.rtokens()
    proxy = uni.get(MARKET_PROXY)
    cal = MarketCalendar.from_reality(api.market_calendar())
    out = []
    for e in ledger:
        if e.event_type is not EventType.CASH_DIV:
            out.append(_excluded(e, f"event type {e.event_type} is not a cash dividend"))
            continue
        if e.cash_dividend_basis != "GROSS":
            out.append(_excluded(e, f"cash amount basis is {e.cash_dividend_basis}; gross basis required"))
            continue
        if e.gross_dividend_per_share is None or e.net_dividend_per_share is None:
            out.append(_excluded(e, "cash dividend amount is incomplete"))
            continue
        current = uni.get(e.symbol)
        if current is None and not e.instrument_snapshot:
            out.append(_excluded(e, "symbol not in live universe"))
            continue
        if e.spot_symbol is None:
            out.append(_excluded(e, "event has no live spot symbol"))
            continue
        try:
            live = _instrument_for_event(e, current)
            out.append(study_event(api, e, live, cal, proxy, ledger))
        except Exception as exc:
            # One malformed event or transient source failure must be recorded as an
            # exclusion, not discard the rest of the batch.
            out.append(_excluded(e, f"{type(exc).__name__}: {exc}"))
    return out


def main() -> None:
    import json
    from dataclasses import asdict
    from pathlib import Path
    from .calendar import read_ledger
    import argparse
    from .calendar import LEDGER_PATH
    ap = argparse.ArgumentParser(description="Run the ex-date event study")
    ap.add_argument("--ledger", type=Path, default=LEDGER_PATH)
    ap.add_argument("--output", type=Path,
                    default=Path(__file__).resolve().parent.parent / "data" / "results" / "event_results.json")
    args = ap.parse_args()
    out = args.output
    out.parent.mkdir(exist_ok=True)
    res = run(read_ledger(args.ledger))
    out.write_text(json.dumps([asdict(r) for r in res], indent=1, default=str))
    print(f"{sum(r.usable for r in res)} usable of {len(res)} events -> {out}")
    for r in res:
        if not r.usable:
            print(f"  excluded {r.event_id}: {r.exclusion_reason}")


if __name__ == "__main__":
    main()

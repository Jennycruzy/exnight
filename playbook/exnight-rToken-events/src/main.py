"""Exnight corporate-action selection basket for Bitget Reality tokens."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

from getagent import data, runtime


UNDERLYINGS = {
    "RDGRWUSDT": ("DGRW", "WisdomTree U.S. Quality Dividend Growth Fund"),
    "RNXPIUSDT": ("NXPI", "NXP Semiconductors N.V."),
    "RSATAUSDT": ("SATA", "SATA Holdings"),
    "RSTRCUSDT": ("STRC", "Strategy Variable Rate Series A Perpetual Stretch Preferred Stock"),
    "RTLTUSDT": ("TLT", "iShares 20+ Year Treasury Bond ETF"),
}
LOCALES = ("en", "zh", "zh-tw", "es", "ja", "vi")


def _decimal(value: object, default: str = "0") -> Decimal:
    try:
        return Decimal(str(value if value not in (None, "") else default))
    except (InvalidOperation, ValueError):
        return Decimal(default)


def _records(response: object) -> list[dict[str, object]]:
    return [dict(row) for row in data.to_records(response)]


def _date(value: object) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _latest_price(symbol: str) -> tuple[Decimal, str | None]:
    rows = _records(data.crypto.spot.ticker(symbol=symbol, exchange="bitget"))
    if not rows:
        return Decimal("0"), None
    row = rows[-1]
    return _decimal(row.get("last")), str(row.get("timestamp") or "") or None


def _next_declared_dividend(ticker: str, today: date, horizon: date) -> dict[str, object] | None:
    rows = _records(data.equity.fundamental.dividends(
        symbol=ticker,
        start_date=today.isoformat(),
        end_date=horizon.isoformat(),
        event_type="现金分红",
    ))
    eligible = []
    for row in rows:
        ex_date = _date(row.get("ex_dividend_date"))
        declaration = _date(row.get("declaration_date"))
        if ex_date and today <= ex_date <= horizon and declaration and declaration <= today:
            if _decimal(row.get("amount")) > 0:
                eligible.append((ex_date, row))
    return min(eligible, key=lambda item: item[0])[1] if eligible else None


def _decision(price: Decimal, gross: Decimal, pdr: Decimal, fee: Decimal,
              slippage_bps: Decimal, max_withholding: Decimal) -> tuple[str, Decimal, Decimal]:
    round_trip_cost = price * (fee * Decimal("2") + slippage_bps / Decimal("10000"))
    edge_zero = pdr * gross - gross - round_trip_cost
    edge_max = pdr * gross - gross * (Decimal("1") - max_withholding) - round_trip_cost
    verdict = "EXIT" if edge_zero > 0 else "HOLD" if edge_max <= 0 else "ENTITLEMENT_UNCERTAIN"
    return verdict, edge_zero, edge_max


def _localized(text: str) -> dict[str, str]:
    # Stable English fallback is preferable to invented translations of a
    # financial decision. Product clients still receive every required locale.
    return {locale: text for locale in LOCALES}


def run() -> None:
    cfg = runtime.manifest.get("strategy_config", {}) or {}
    symbols = list(cfg.get("trading_symbols") or runtime.manifest.get("trading_symbols") or [])
    today = datetime.now(timezone.utc).date()
    horizon = today + timedelta(days=int(cfg.get("lookahead_days", 45) or 45))
    pdr = _decimal(cfg.get("pdr_estimate"), "0.965611")
    fee = _decimal(cfg.get("taker_fee_rate"), "0.001")
    slip = _decimal(cfg.get("modeled_slippage_bps"), "25")
    max_withholding = _decimal(cfg.get("withholding_max"), "0.30")
    basket = []
    omitted = 0

    for symbol in symbols:
        underlying = UNDERLYINGS.get(symbol)
        if underlying is None:
            omitted += 1
            continue
        ticker, name = underlying
        try:
            event = _next_declared_dividend(ticker, today, horizon)
            price, price_ts = _latest_price(symbol)
        except Exception:
            omitted += 1
            continue
        if event is None or price <= 0:
            omitted += 1
            continue
        gross = _decimal(event.get("amount"))
        verdict, lower, upper = _decision(price, gross, pdr, fee, slip, max_withholding)
        ex_date = str(event.get("ex_dividend_date"))[:10]
        declaration = str(event.get("declaration_date"))[:10]
        thesis = (
            f"{verdict}: declared {gross} dividend for {ex_date}; modeled EXIT edge "
            f"ranges from {lower:.4f} to {upper:.4f} per token."
        )
        risk = (
            "Withholding and Bitget snapshot timing may change entitlement; "
            "execution cost is modeled and public-book liquidity may be absent."
        )
        basket.append({
            "asset": ticker,
            "symbol": symbol,
            "market": "spot",
            "name": name,
            "asset_class": "rwa",
            "reference_price": str(price),
            "thesis": thesis,
            "risk": risk,
            "thesis_i18n": _localized(thesis),
            "risk_i18n": _localized(risk),
            "verdict": verdict,
            "ex_date": ex_date,
            "gross_dividend": str(gross),
            "declaration_date": declaration,
            "price_timestamp": price_ts,
            "exit_edge_zero_withholding": str(lower),
            "exit_edge_max_withholding": str(upper),
        })

    rank = {"EXIT": 0, "ENTITLEMENT_UNCERTAIN": 1, "HOLD": 2}
    basket.sort(key=lambda item: (rank.get(str(item["verdict"]), 9), str(item["ex_date"]), str(item["symbol"])))
    basket = basket[:int(cfg.get("max_assets", 5) or 5)]
    runtime.emit_signal(
        action="watch",
        symbol=str(basket[0]["symbol"]) if basket else "RSATAUSDT",
        confidence=0.0 if not basket else 0.8,
        metrics={
            "basket_size": len(basket),
            "omitted_symbols": omitted,
            "pdr_estimate": float(pdr),
            "modeled_slippage_bps": int(slip),
            "withholding_range_max": float(max_withholding),
        },
        meta={
            "basket": basket,
            "decision_date": today.isoformat(),
            "knowledge_time_rule": "declaration_date must be on or before decision date",
            "execution_label": "MODELED_EXECUTION",
            "auto_trading": False,
        },
    )


if __name__ == "__main__":
    run()

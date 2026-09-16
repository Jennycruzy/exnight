"""C1: build the corporate-action ledger from saved first-party sources.

The 2026-07-24 dividend notice is a structured HTML table, so it is parsed deterministically;
no language model touches these numbers. Model parsing is reserved for unstructured notices
and is not used here.

The output is an append-only JSONL ledger at data/ledger/events.jsonl. Rebuilding it from
the saved sources must reproduce it byte for byte (tests assert this).
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from .events import CorporateAction, EventType
from .market import BitgetPublic, SpotSymbol
from .sources import SOURCES

ROOT = Path(__file__).resolve().parent.parent
LEDGER_PATH = ROOT / "data" / "ledger" / "events.jsonl"
REALITY_RAW_DIR = ROOT / "data" / "raw" / "corporate_actions" / "reality"
REALITY_DIVIDENDS_ENDPOINT = "/api/v3/reality/market/dividends"
STOCK_INFO_ENDPOINT = "/api/v3/reality/market/stock-info"
REALITY_DATE_ZONE = ZoneInfo("Asia/Shanghai")

# DOCUMENTED in the 2026-07-24 notice: "the securities custodian will deduct a 30% federal
# withholding tax on dividend income. Actual Received Amount = Shares × Dividend × 70%".
# This constant applies to that notice only and is attached per event, not globally.
WITHHOLDING_2026_07_24 = Decimal("0.30")


def _text_lines(raw_html: str) -> list[str]:
    t = re.sub(r"<script.*?</script>", "", raw_html, flags=re.S)
    t = re.sub(r"<[^>]+>", "\n", t)
    t = html.unescape(t)
    return [l.strip() for l in t.split("\n") if l.strip()]


def parse_dividend_notice_2026_07_24() -> list[dict]:
    """Rows of (ticker, ex_date, payment_date, dividend_per_share) from the saved notice."""
    src = SOURCES["dividends_2026_07_24"]
    lines = _text_lines(src.read())
    hdr = ["Ticker", "Ex-Dividend Date", "Payment Date", "Dividend per Share"]
    for i in range(len(lines) - 3):
        if lines[i : i + 4] == hdr:
            i += 4
            break
    else:
        raise RuntimeError("dividend table header not found in saved notice")
    rows = []
    while i + 3 < len(lines) and re.fullmatch(r"r[A-Z]+", lines[i]):
        tk, ex, pay, dps = lines[i : i + 4]
        rows.append(
            dict(
                symbol=tk,
                exchange_ex_date=dt.datetime.strptime(ex, "%Y/%m/%d").date(),
                payment_date=dt.datetime.strptime(pay, "%Y/%m/%d").date(),
                gross_dividend_per_share=Decimal(dps),
            )
        )
        i += 4
    if len(rows) != 63:
        raise RuntimeError(f"notice title says 63 stocks; parsed {len(rows)} rows")
    return rows


def parse_weekend_list_2026_07_17() -> set[str]:
    src = SOURCES["weekend_trading_2026_07_17"]
    lines = _text_lines(src.read())
    i = lines.index("Company Name") + 1
    tickers = set()
    while i + 1 < len(lines) and re.fullmatch(r"r[A-Z]+", lines[i]):
        tickers.add(lines[i])
        i += 2
    if len(tickers) != 61:
        raise RuntimeError(f"weekend notice says 61 tokens; parsed {len(tickers)}")
    return tickers


def build_ledger(universe: dict[str, SpotSymbol]) -> list[CorporateAction]:
    src = SOURCES["dividends_2026_07_24"]
    weekend = parse_weekend_list_2026_07_17()
    events = []
    seen: dict[str, int] = {}
    for r in parse_dividend_notice_2026_07_24():
        sym = r["symbol"]
        seen[sym] = seen.get(sym, 0) + 1
        gross = r["gross_dividend_per_share"]
        spot = universe.get(sym)
        notes = [
            "gross amount, ex-date and payment date DOCUMENTED from the notice table",
            "withholding 30% DOCUMENTED from the notice's Distribution Rules",
            "exchange record date not stated by Bitget; left null rather than inferred from T+1",
            "Bitget snapshot time not stated in the notice ('at the time of the snapshot'); "
            "eligibility therefore unverified and BUY signals are suppressed for this event",
        ]
        if spot is None:
            notes.append("no matching rToken in the live spot symbol list on the build date")
        events.append(
            CorporateAction(
                event_id=f"{sym}-{r['exchange_ex_date'].isoformat()}-{seen[sym]}",
                symbol=sym,
                underlying=sym[1:],
                spot_symbol=spot.symbol if spot else None,
                event_type=EventType.CASH_DIV,
                announcement_date=dt.date(2026, 7, 24),
                exchange_ex_date=r["exchange_ex_date"],
                exchange_record_date=None,
                bitget_snapshot_time=None,
                payment_date=r["payment_date"],
                gross_dividend_per_share=gross,
                withholding_rate=WITHHOLDING_2026_07_24,
                net_dividend_per_share=gross * (1 - WITHHOLDING_2026_07_24),
                eligibility_verified=False,
                weekend_list_2026_07_17=sym in weekend,
                source_key=src.key,
                source_url=src.url,
                label="DOCUMENTED",
                notes=notes + [
                    "ex-date timezone is not stated in the notice; ET treatment is ASSUMED for price windows",
                ],
                ex_date_timezone="UNVERIFIED",
                cash_dividend_per_share=gross,
                cash_dividend_basis="GROSS",
                cash_dividend_timestamp=None,
                adjustment_ratio=None,
                trading_halt_start=None,
                trading_halt_end=None,
                status="completed",
                source_endpoint=src.url,
                source_fetched_at=None,
            )
        )
    return events


def _timestamp_ms(value: str | int | None, field: str, required: bool = False) -> dt.datetime | None:
    if value in (None, ""):
        if required:
            raise ValueError(f"Reality action has no {field}")
        return None
    try:
        timestamp = dt.datetime.fromtimestamp(int(value) / 1000, dt.UTC)
    except (TypeError, ValueError, OverflowError, OSError) as exc:
        raise ValueError(f"Reality action has invalid {field}: {value!r}") from exc
    return timestamp


def _date_in_reality_zone(value: dt.datetime) -> dt.date:
    return value.astimezone(REALITY_DATE_ZONE).date()


def _decimal(value: str | int | float | Decimal | None, field: str) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        out = Decimal(str(value))
    except Exception as exc:
        raise ValueError(f"Reality action has invalid {field}: {value!r}") from exc
    if not out.is_finite():
        raise ValueError(f"Reality action has non-finite {field}: {value!r}")
    return out


def _save_raw_response(api: BitgetPublic, endpoint: str, raw_dir: Path | None) -> None:
    if raw_dir is None:
        return
    fetched = api.last_fetch_at or dt.datetime.now(dt.UTC)
    request = api.last_request or {"path": endpoint, "params": {}}
    payload = {
        "endpoint": endpoint,
        "request": request,
        "fetched_at": fetched.isoformat(),
        "raw_response": api.last_raw_response,
    }
    name = f"{fetched:%Y%m%dT%H%M%S.%fZ}.json"
    path = raw_dir / endpoint.rsplit("/", 1)[-1]
    path.mkdir(parents=True, exist_ok=True)
    (path / name).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _reality_action(
    row: dict,
    spot: SpotSymbol,
    code: str,
    ordinal: int,
    fetched_at: dt.datetime,
    notice_by_key: dict[tuple[str, dt.date], dict],
    weekend: set[str],
    as_of: dt.datetime,
) -> CorporateAction:
    action_type = str(row.get("type") or "").lower()
    ex_ts = _timestamp_ms(row.get("exrightDate"), "exrightDate", required=True)
    ex_date = _date_in_reality_zone(ex_ts)
    announcement = _timestamp_ms(row.get("announcementDate"), "announcementDate")
    record = _timestamp_ms(row.get("recordDate"), "recordDate")
    payment = _timestamp_ms(row.get("dividendDate"), "dividendDate")
    source_notes = [
        "Reality market data response OBSERVED at fetch time",
        "Reality timestamps are retained as UTC instants; date fields use the empirically matching Asia/Shanghai calendar date",
        "Reality endpoint does not document the date timezone; the Asia/Shanghai convention is OBSERVED on matched notice dates and remains ASSUMED",
        "Bitget snapshot time is not present; eligibility remains unverified",
    ]
    common = dict(
        event_id=f"{spot.base_coin}-{ex_date.isoformat()}-{ordinal}",
        symbol=spot.base_coin,
        underlying=code,
        spot_symbol=spot.symbol,
        announcement_date=_date_in_reality_zone(announcement) if announcement else None,
        exchange_ex_date=ex_date,
        exchange_record_date=_date_in_reality_zone(record) if record else None,
        bitget_snapshot_time=None,
        payment_date=_date_in_reality_zone(payment) if payment else None,
        eligibility_verified=False,
        weekend_list_2026_07_17=spot.base_coin in weekend,
        source_key=f"reality_dividends_{code}",
        source_url="https://api.bitget.com" + REALITY_DIVIDENDS_ENDPOINT,
        label="OBSERVED",
        notes=source_notes,
        ex_date_timezone="UNVERIFIED",
        cash_dividend_timestamp=payment,
        adjustment_ratio=None,
        trading_halt_start=None,
        trading_halt_end=None,
        status="completed" if ex_date <= as_of.date() else "pending",
        source_endpoint=REALITY_DIVIDENDS_ENDPOINT,
        source_fetched_at=fetched_at,
    )
    if action_type == "cash_dividend":
        amount = _decimal(row.get("dividendPerShare"), "dividendPerShare")
        if amount is None:
            raise ValueError(f"{common['event_id']}: cash dividend has no dividendPerShare")
        notice = notice_by_key.get((spot.base_coin, ex_date))
        if notice is not None and amount == notice["gross_dividend_per_share"]:
            gross = amount
            basis = "GROSS"
            withholding = WITHHOLDING_2026_07_24
            net = gross * (1 - withholding)
            common["notes"].append("source amount matches the saved Bitget notice; gross basis is OBSERVED for this row")
        else:
            gross = None
            basis = "UNRESOLVED"
            withholding = None
            net = None
            common["notes"].append("gross versus net basis is unresolved; this row cannot enter PDR calculations")
        return CorporateAction(
            event_type=EventType.CASH_DIV,
            gross_dividend_per_share=gross,
            withholding_rate=withholding,
            net_dividend_per_share=net,
            cash_dividend_per_share=amount,
            cash_dividend_basis=basis,
            **common,
        )
    if action_type == "stock_split":
        numerator = _decimal(row.get("splitNumerator"), "splitNumerator")
        denominator = _decimal(row.get("splitDenominator"), "splitDenominator")
        if numerator is None or denominator is None or denominator <= 0:
            raise ValueError(f"{common['event_id']}: stock split lacks a valid numerator/denominator")
        ratio = numerator / denominator
        event_type = EventType.SPLIT if ratio > 1 else EventType.REVERSE_SPLIT
        common["notes"].append("Reality split row has no spot halt timestamps; no halt is inferred")
        common["adjustment_ratio"] = ratio
        return CorporateAction(
            event_type=event_type,
            gross_dividend_per_share=None,
            withholding_rate=None,
            net_dividend_per_share=None,
            cash_dividend_per_share=None,
            cash_dividend_basis="UNRESOLVED",
            **common,
        )
    if action_type == "stock_dividend":
        amount = _decimal(row.get("stockDividendPerShare"), "stockDividendPerShare")
        common["notes"].append(f"stockDividendPerShare={amount}; no cash PDR is computed")
        return CorporateAction(
            event_type=EventType.STOCK_DIV,
            gross_dividend_per_share=None,
            withholding_rate=None,
            net_dividend_per_share=None,
            cash_dividend_per_share=None,
            cash_dividend_basis="UNRESOLVED",
            **common,
        )
    common["notes"].append(f"unsupported Reality action type {action_type!r}; retained without arithmetic")
    return CorporateAction(
        event_type=EventType.OTHER,
        gross_dividend_per_share=None,
        withholding_rate=None,
        net_dividend_per_share=None,
        cash_dividend_per_share=None,
        cash_dividend_basis="UNRESOLVED",
        **common,
    )


def build_reality_ledger(
    api: BitgetPublic,
    universe: dict[str, SpotSymbol],
    start_date: dt.date,
    as_of: dt.datetime | None = None,
    raw_dir: Path | None = REALITY_RAW_DIR,
    notice_rows: list[dict] | None = None,
) -> list[CorporateAction]:
    """Build spot actions from Reality market data for the supplied live universe.

    start_date is explicit so a rebuild cannot silently change its historical sample.
    Reality date fields are decoded in the empirically matching UTC+8 calendar zone;
    the raw Unix milliseconds remain in the saved response.
    The saved notice is only an amount-basis reconciliation source; it does not define
    the event universe. Future ex-dates are retained with pending status.
    """
    if isinstance(start_date, dt.datetime) or not isinstance(start_date, dt.date):
        raise TypeError("start_date must be a date")
    as_of = as_of or dt.datetime.now(dt.UTC)
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    notice_rows = parse_dividend_notice_2026_07_24() if notice_rows is None else notice_rows
    notice_by_key = {(r["symbol"], r["exchange_ex_date"]): r for r in notice_rows}
    weekend = parse_weekend_list_2026_07_17()
    events: list[CorporateAction] = []
    for base_coin, spot in sorted(universe.items()):
        info = api.reality_stock_info(spot.symbol)
        _save_raw_response(api, STOCK_INFO_ENDPOINT, raw_dir)
        code = info.get("code")
        if not code:
            raise ValueError(f"{spot.symbol}: Reality stock-info has no code")
        ordinal_by_key: dict[tuple[dt.date, str], int] = {}
        for _, rows in api.iter_reality_dividends(str(code), limit=100):
            fetched_at = api.last_fetch_at or as_of
            _save_raw_response(api, REALITY_DIVIDENDS_ENDPOINT, raw_dir)
            for row in rows:
                if not isinstance(row, dict):
                    raise ValueError(f"{code}: Reality action row is not an object")
                ex_ts = _timestamp_ms(row.get("exrightDate"), "exrightDate")
                if ex_ts is None:
                    # OBSERVED 2026-09-16: KO's 1965-1996 splits carry no exrightDate, only a
                    # (negative-epoch) recordDate. Such rows may be skipped only when another
                    # dated field proves they precede start_date; otherwise fail loudly.
                    fallback = [_timestamp_ms(row.get(f), f) for f in ("recordDate", "splitValidDate")]
                    fallback = [t for t in fallback if t is not None]
                    if fallback and max(_date_in_reality_zone(t) for t in fallback) < start_date:
                        continue
                    raise ValueError(f"{code}: Reality action has no exrightDate and no dated field before {start_date}")
                ex_date = _date_in_reality_zone(ex_ts)
                if ex_date < start_date:
                    continue
                action_type = str(row.get("type") or "").lower()
                key = (ex_date, action_type)
                ordinal_by_key[key] = ordinal_by_key.get(key, 0) + 1
                events.append(_reality_action(
                    row, spot, str(code), ordinal_by_key[key], fetched_at,
                    notice_by_key, weekend, as_of,
                ))
    return sorted(events, key=lambda e: (e.exchange_ex_date, e.symbol, e.event_id))


def write_ledger(events: list[CorporateAction], path: Path = LEDGER_PATH) -> None:
    """Append new event rows and reject changes to an existing event id."""
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, str] = {}
    if path.exists():
        for line in path.read_text().splitlines(keepends=True):
            if not line.strip():
                continue
            payload = json.loads(line)
            event_id = payload.get("event_id")
            if not event_id or event_id in existing:
                raise ValueError(f"invalid or duplicate event id in {path}: {event_id!r}")
            existing[event_id] = line
    mode = "a" if path.exists() else "w"
    with path.open(mode) as f:
        for event in events:
            line = json.dumps(event.model_dump(mode="json"), sort_keys=True) + "\n"
            previous = existing.get(event.event_id)
            if previous is not None:
                if previous != line:
                    raise ValueError(f"event {event.event_id} changed; append-only ledger refuses replacement")
                continue
            f.write(line)
            existing[event.event_id] = line


def read_ledger(path: Path = LEDGER_PATH) -> list[CorporateAction]:
    return [CorporateAction.model_validate(json.loads(l)) for l in path.read_text().splitlines() if l]


def _date_arg(value: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid date: {value}") from exc


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the EXNIGHT corporate-action ledger")
    parser.add_argument("--source", choices=("notice", "reality"), default="notice")
    parser.add_argument("--start-date", type=_date_arg, help="first ex-date for Reality data")
    parser.add_argument("--output", type=Path, default=LEDGER_PATH)
    parser.add_argument("--base-coin", action="append", dest="base_coins",
                        help="limit Reality data to an API-returned baseCoin; repeatable")
    args = parser.parse_args()

    api = BitgetPublic()
    universe = api.rtokens()
    if args.base_coins:
        requested = set(args.base_coins)
        missing = sorted(requested - set(universe))
        if missing:
            parser.error(f"baseCoin not in live universe: {missing}")
        universe = {key: value for key, value in universe.items() if key in requested}
    if args.source == "reality":
        if args.start_date is None:
            parser.error("--start-date is required with --source reality")
        events = build_reality_ledger(api, universe, args.start_date)
    else:
        events = build_ledger(universe)
    write_ledger(events, args.output)
    unresolved = sum(e.cash_dividend_basis == "UNRESOLVED" for e in events)
    print(f"{len(events)} events appended or confirmed in {args.output}")
    print(f"{len({e.symbol for e in events})} distinct API instruments; "
          f"{unresolved} cash rows with unresolved amount basis")


if __name__ == "__main__":
    main()

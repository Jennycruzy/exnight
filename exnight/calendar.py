"""C1: build the corporate-action ledger from saved first-party sources.

The 2026-07-24 dividend notice is a structured HTML table, so it is parsed deterministically;
no language model touches these numbers. Model parsing is reserved for unstructured notices
and is not used here.

The output is an append-only JSONL ledger at data/ledger/events.jsonl. Rebuilding it from
the saved sources must reproduce it byte for byte (tests assert this).
"""
from __future__ import annotations

import datetime as dt
import html
import json
import re
from decimal import Decimal
from pathlib import Path

from .events import CorporateAction, EventType
from .market import BitgetPublic, SpotSymbol
from .sources import SOURCES

LEDGER_PATH = Path(__file__).resolve().parent.parent / "data" / "ledger" / "events.jsonl"

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


def write_ledger(events: list[CorporateAction], path: Path = LEDGER_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for e in events:
            f.write(json.dumps(e.model_dump(mode="json"), sort_keys=True) + "\n")


def read_ledger(path: Path = LEDGER_PATH) -> list[CorporateAction]:
    return [CorporateAction.model_validate(json.loads(l)) for l in path.read_text().splitlines() if l]


def main() -> None:
    universe = BitgetPublic().rtokens()
    events = build_ledger(universe)
    write_ledger(events)
    missing = [e.symbol for e in events if e.spot_symbol is None]
    print(f"{len(events)} events written to {LEDGER_PATH}")
    print(f"{len({e.symbol for e in events})} distinct rTokens; "
          f"{sum(e.weekend_list_2026_07_17 for e in events)} events on weekend-trading tokens; "
          f"{len(missing)} without a live spot symbol: {missing}")
    print("eligibility_verified: 0 of", len(events), "(snapshot time not published)")


if __name__ == "__main__":
    main()

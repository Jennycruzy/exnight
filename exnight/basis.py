"""Forward gross-basis resolution and net-entitlement bounds.

The ledger builder (exnight.calendar) assigns a GROSS basis only when a Reality cash row
matches the 2026-07-24 Bitget notice, which also documents the 30% withholding for that
batch. Every other cash row is UNRESOLVED, so no event after the notice window can enter
the event study or receive a verdict. This module resolves those rows from evidence,
without changing the builder's rule, and keeps two questions apart:

  gross   Is the Reality `dividendPerShare` the issuer's declared (pre-tax) amount?
          Evidence must come from outside Bitget: the NXPI/MDT cases showed Bitget can
          publish a home-country-net figure, and Bitget's Reality feed and perp notices
          share that upstream, so their agreement with each other proves nothing.
  net     What does the holder actually receive? Only the 2026-07-24 notice documents a
          rate (30%) and only for its own batch. The rToken FAQ (2026-06-23) says
          withholding is not universally eliminated and the rate depends on structure,
          parties and treaties. Everything outside the notice therefore carries a range,
          and a verdict must be invariant to it.

Basis tiers (recorded per event in `basis_tier` / `basis_evidence`):
  1  Reality amount matches the 2026-07-24 notice (builder rule). Net DOCUMENTED at 30%.
  2  Reality amount and ex-date match an issuer-declared or realised dividend from a
     third-party feed (Nasdaq declared dividends; Yahoo realised dividend events).
  3  No issuer row exists for the ex-date yet (typical before the ex-date for names the
     Nasdaq feed does not cover). Requires all of: a first-party Bitget document naming
     the same amount and ex-date (perp settlement notice), the issuer's announced next
     ex-date (Yahoo calendar) equal to the Reality ex-date, and the issuer's most recent
     realised dividend equal to the amount. The last condition is the ASSUMED part
     ("amount unchanged from the prior period"); it is what would have caught NXPI.
  -  UNRESOLVED otherwise, with the reason. An issuer amount that disagrees with Reality
     is always UNRESOLVED regardless of any Bitget corroboration.

Raw responses are saved under data/raw/basis/<source>/ with fetch time, and the
resolution table is written to data/results/basis_resolution.csv.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from decimal import Decimal
from pathlib import Path

import httpx

from . import underlying
from .calendar import AMOUNT_MATCH_REL_TOL, _text_lines, read_ledger
from .events import CorporateAction, EventType
from .sources import SOURCES

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw" / "basis"
RESULTS = ROOT / "data" / "results"
RESOLVED_LEDGER = ROOT / "data" / "ledger" / "reality_notice59_resolved.jsonl"

# Withholding outside the 2026-07-24 notice. Base and bounds are ASSUMED: the FAQ says the
# rate "depends on the product structure, relevant parties, tax treaties and the user's
# circumstances" and does not state a figure. 30% is the US statutory non-resident rate and
# the rate the notice documented for its batch; a treaty or structure can only lower it.
WITHHOLDING_BASE = Decimal("0.30")
WITHHOLDING_LOW = Decimal("0")
WITHHOLDING_HIGH = Decimal("0.30")
PRIOR_LOOKBACK_DAYS = 200
_UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}


def _match(a: Decimal | None, b: Decimal | None) -> bool:
    """Reality amount `a` equals source figure `b` up to the source's own rounding.

    Third-party feeds print 3-4 dp (Yahoo 0.049 for SATA's 0.0493), so besides the
    builder's 0.5% relative tolerance a difference of at most half a unit in the
    source's last printed decimal is rounding, not a basis conflict. NXPI-style
    conflicts (ratio 0.85) are far outside both.
    """
    if a is None or b is None or b == 0:
        return False
    half_ulp = Decimal(1).scaleb(b.as_tuple().exponent) / 2 if b.as_tuple().exponent < 0 else Decimal(0)
    return abs(a / b - 1) <= AMOUNT_MATCH_REL_TOL or abs(a - b) <= half_ulp


def parse_perp_dividend_notice_2026_09_16() -> list[dict]:
    """(underlying, ex_date ET, amount) rows from the saved perp settlement notice."""
    lines = _text_lines(SOURCES["perp_dividend_2026_09_16"].read())
    hdr = ["Futures Pair", "Dividend per Share (USD)", "Ex-Dividend Date (ET)", "Settlement Time (UTC+8)"]
    for i in range(len(lines) - 3):
        if lines[i:i + 4] == hdr:
            i += 4
            break
    else:
        raise RuntimeError("dividend table header not found in saved perp notice")
    rows = []
    while i + 3 < len(lines) and re.fullmatch(r"[A-Z]+USDT", lines[i]):
        pair, dps, ex, settle = lines[i:i + 4]
        rows.append(dict(underlying=pair[:-4], amount=Decimal(dps),
                         ex_date=dt.datetime.strptime(ex, "%Y-%m-%d").date(),
                         settlement_utc8=settle, source_key="perp_dividend_2026_09_16"))
        i += 4
    if len(rows) != 2:
        raise RuntimeError(f"perp notice names two pairs; parsed {len(rows)} rows")
    return rows


class IssuerSources:
    """Third-party issuer dividend data, fetched once per ticker per run and saved raw."""

    def __init__(self, raw_dir: Path = RAW_DIR, offline: bool = False):
        self.raw_dir = raw_dir
        self.offline = offline
        self._nasdaq: dict[str, list[dict] | None] = {}
        self._calendar: dict[str, dt.date | None] = {}
        self._yahoo: tuple[httpx.Client, str] | None = None   # session with cookie, crumb

    def _save(self, source: str, ticker: str, payload) -> None:
        d = self.raw_dir / source
        d.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
        path = d / f"{ticker}_{stamp}.json"
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(
            dict(fetched_at=dt.datetime.now(dt.UTC).isoformat(), ticker=ticker, payload=payload)))
        tmp.replace(path)

    def _cached_payload(self, source: str, ticker: str):
        """Return the newest cached response payload, or None when no valid cache exists."""
        paths = sorted((self.raw_dir / source).glob(f"{ticker}_*.json"), reverse=True)
        for path in paths:
            try:
                body = json.loads(path.read_text())
            except (OSError, ValueError):
                continue
            if isinstance(body, dict) and "payload" in body:
                return body["payload"]
            # Accept a raw response too, so an imported cache remains replayable.
            return body
        return None

    @staticmethod
    def _parse_nasdaq(body) -> list[dict] | None:
        if not isinstance(body, dict):
            return None
        rows = (((body.get("data") or {}).get("dividends") or {}).get("rows")) or []
        out = []
        for x in rows:
            try:
                out.append(dict(ex_date=dt.datetime.strptime(x["exOrEffDate"], "%m/%d/%Y").date(),
                                amount=Decimal(x["amount"].replace("$", "").replace(",", "")),
                                declaration_date=x.get("declarationDate"), type=x.get("type")))
            except (KeyError, ValueError, ArithmeticError, AttributeError):
                continue
        return out or None

    def nasdaq_declared(self, ticker: str) -> list[dict] | None:
        """Declared dividends (ex-date, amount) or None when the feed has no rows/fails."""
        if ticker in self._nasdaq:
            return self._nasdaq[ticker]
        out: list[dict] | None = None
        if self.offline:
            out = self._parse_nasdaq(self._cached_payload("nasdaq", ticker))
        else:
            for asset in ("stocks", "etf"):
                try:
                    r = httpx.get(f"https://api.nasdaq.com/api/quote/{ticker}/dividends",
                                  params=dict(assetclass=asset), headers=_UA, timeout=30)
                    r.raise_for_status()
                    body = r.json()
                except (httpx.HTTPError, ValueError):
                    continue
                if not isinstance(body, dict):
                    continue
                rows = (((body.get("data") or {}).get("dividends") or {}).get("rows")) or []
                if rows:
                    self._save("nasdaq", ticker, body)
                    out = self._parse_nasdaq(body)
                    break
        self._nasdaq[ticker] = out
        return out

    def yahoo_realised(self, ticker: str, ex_date: dt.date) -> list[dict] | None:
        """Realised dividend events around ex_date (cached raw by exnight.underlying)."""
        start = ex_date - dt.timedelta(days=PRIOR_LOOKBACK_DAYS)
        end = ex_date + dt.timedelta(days=2)
        try:
            rows = underlying.dividends(ticker, start, end, offline=self.offline)
        except underlying.UnderlyingDataError:
            return None
        return [dict(ex_date=r["ex_date"], amount=Decimal(str(r["amount"]))) for r in rows]

    def yahoo_calendar(self, ticker: str) -> dt.date | None:
        """Issuer's announced next ex-dividend date, or None if unavailable."""
        if ticker in self._calendar:
            return self._calendar[ticker]
        out = None
        if self.offline:
            body = self._cached_payload("yahoo_calendar", ticker)
            try:
                res = ((body.get("quoteSummary") or {}).get("result") or [{}])[0]
                raw = ((res.get("calendarEvents") or {}).get("exDividendDate") or {}).get("raw")
                if raw is not None:
                    out = dt.datetime.fromtimestamp(int(raw), dt.UTC).date()
            except (AttributeError, IndexError, TypeError, ValueError, OSError):
                out = None
        else:
            try:
                if self._yahoo is None:
                    s = httpx.Client(headers=_UA, timeout=20)
                    s.get("https://fc.yahoo.com", follow_redirects=False)      # sets the A3 cookie
                    crumb = s.get("https://query2.finance.yahoo.com/v1/test/getcrumb")
                    if crumb.status_code != 200 or not crumb.text:
                        raise ValueError(f"yahoo crumb {crumb.status_code}")
                    self._yahoo = (s, crumb.text)
                s, crumb = self._yahoo
                r = s.get(f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{ticker}",
                          params=dict(modules="calendarEvents", crumb=crumb), timeout=30)
                r.raise_for_status()
                body = r.json()
                if not isinstance(body, dict):
                    raise ValueError("Yahoo calendar response is not an object")
                res = ((body.get("quoteSummary") or {}).get("result") or [{}])[0]
                raw = ((res.get("calendarEvents") or {}).get("exDividendDate") or {}).get("raw")
                if raw:
                    out = dt.datetime.fromtimestamp(int(raw), dt.UTC).date()
                self._save("yahoo_calendar", ticker, body)
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                out = None
        self._calendar[ticker] = out
        return out


def resolve_event(e: CorporateAction, src: IssuerSources, perp_rows: list[dict]) -> tuple[CorporateAction, dict]:
    """Return the (possibly) resolved event and a resolution record."""
    rec = dict(event_id=e.event_id, symbol=e.symbol, underlying=e.underlying, ex_date=e.exchange_ex_date.isoformat(),
               reality_amount=str(e.cash_dividend_per_share) if e.cash_dividend_per_share is not None else None,
               basis_before=e.cash_dividend_basis, basis_after=e.cash_dividend_basis, tier=e.basis_tier,
               issuer_declared=None, issuer_realised=None, perp_notice=None, calendar_ex_date=None,
               prior_realised=None, evidence="", reason="")
    if e.event_type is not EventType.CASH_DIV:
        rec["reason"] = "not a cash dividend"
        return e, rec
    if e.cash_dividend_basis == "GROSS" and e.basis_tier == 1:
        rec["evidence"] = "; ".join(e.basis_evidence)
        rec["reason"] = "tier 1: 2026-07-24 notice match (builder rule)"
        return e, rec
    if e.cash_dividend_basis != "UNRESOLVED":
        rec["reason"] = f"basis {e.cash_dividend_basis} left as written"
        return e, rec

    tk, ex, amount = e.underlying, e.exchange_ex_date, e.cash_dividend_per_share
    evidence: list[str] = []
    conflicts: list[str] = []
    issuer_match = False

    declared = src.nasdaq_declared(tk)
    if declared is not None:
        same = [d for d in declared if d["ex_date"] == ex and (d.get("type") or "Cash") == "Cash"]
        if same:
            rec["issuer_declared"] = str(same[0]["amount"])
            if _match(amount, same[0]["amount"]):
                issuer_match = True
                evidence.append(f"nasdaq_declared: {same[0]['amount']} ex {ex} declared {same[0].get('declaration_date')} (third-party)")
            else:
                conflicts.append(f"nasdaq_declared {same[0]['amount']} vs Reality {amount} (ratio {float(amount / same[0]['amount']):.3f})")

    realised = src.yahoo_realised(tk, ex)
    prior = None
    if realised is not None:
        same = [d for d in realised if d["ex_date"] == ex]
        if same:
            rec["issuer_realised"] = str(same[0]["amount"])
            if _match(amount, same[0]["amount"]):
                issuer_match = True
                evidence.append(f"yahoo_realised: {same[0]['amount']} ex {ex} (third-party)")
            else:
                conflicts.append(f"yahoo_realised {same[0]['amount']} vs Reality {amount} (ratio {float(amount / same[0]['amount']):.3f})")
        before = [d for d in realised if d["ex_date"] < ex]
        prior = before[-1] if before else None
        if prior is not None:
            rec["prior_realised"] = f"{prior['amount']} ex {prior['ex_date']}"

    perp = [p for p in perp_rows if p["underlying"] == tk and p["ex_date"] == ex]
    perp_match = False
    if perp:
        rec["perp_notice"] = str(perp[0]["amount"])
        if _match(amount, perp[0]["amount"]):
            perp_match = True
            evidence.append(f"{perp[0]['source_key']}: {perp[0]['amount']} ex {ex} (first-party; amount only, no tax statement)")
        else:
            conflicts.append(f"perp notice {perp[0]['amount']} vs Reality {amount}")

    if conflicts:
        rec["reason"] = "amount conflict: " + "; ".join(conflicts)
        rec["evidence"] = "; ".join(evidence)
        e = e.model_copy(update=dict(notes=e.notes + [f"basis resolution: {rec['reason']}; stays UNRESOLVED"]))
        return e, rec

    tier: int | None = None
    if issuer_match:
        tier = 2
    else:
        cal = src.yahoo_calendar(tk)
        rec["calendar_ex_date"] = cal.isoformat() if cal else None
        cal_match = cal == ex
        prior_match = prior is not None and _match(amount, prior["amount"])
        if cal_match:
            evidence.append(f"yahoo_calendar: announced next ex-date {cal} (third-party)")
        if prior_match:
            evidence.append(f"prior realised {prior['amount']} ex {prior['ex_date']} equals amount (ASSUMED unchanged)")
        if perp_match and cal_match and prior_match:
            tier = 3
        else:
            missing = [n for ok, n in ((perp_match, "first-party amount corroboration"),
                                       (cal_match, "issuer announced ex-date"),
                                       (prior_match, "prior-period amount")) if not ok]
            rec["reason"] = "no issuer row at ex-date; tier 3 needs " + ", ".join(missing)

    rec["evidence"] = "; ".join(evidence)
    if tier is None:
        e = e.model_copy(update=dict(notes=e.notes + [f"basis resolution: {rec['reason']}; stays UNRESOLVED"]))
        return e, rec

    gross = amount
    net = gross * (1 - WITHHOLDING_BASE)
    e = e.model_copy(update=dict(
        cash_dividend_basis="GROSS", gross_dividend_per_share=gross, withholding_rate=WITHHOLDING_BASE,
        net_dividend_per_share=net, basis_tier=tier, basis_evidence=evidence, net_dividend_verified=False,
        withholding_rate_low=WITHHOLDING_LOW, withholding_rate_high=WITHHOLDING_HIGH,
        notes=e.notes + [f"basis resolution tier {tier}: gross basis from issuer evidence; "
                         f"withholding {WITHHOLDING_BASE} ASSUMED with range [{WITHHOLDING_LOW}, {WITHHOLDING_HIGH}] "
                         "per rtoken_faq_2026_06_23; net entitlement not verified for this event"]))
    e = CorporateAction.model_validate(e.model_dump(mode="json"))   # re-run the model checks
    rec.update(basis_after="GROSS", tier=tier, reason=f"tier {tier}")
    return e, rec


def resolve(events: list[CorporateAction], src: IssuerSources | None = None) -> tuple[list[CorporateAction], list[dict]]:
    src = src or IssuerSources()
    perp_rows = parse_perp_dividend_notice_2026_09_16()
    out, recs = [], []
    for e in events:
        r, rec = resolve_event(e, src, perp_rows)
        out.append(r)
        recs.append(rec)
    return out, recs


def main() -> None:
    import argparse
    import csv
    ap = argparse.ArgumentParser(description="Resolve gross basis and net-entitlement bounds for ledger rows")
    ap.add_argument("--ledger", type=Path, default=ROOT / "data" / "ledger" / "reality_notice59.jsonl")
    ap.add_argument("--output", type=Path, default=RESOLVED_LEDGER)
    ap.add_argument("--table", type=Path, default=RESULTS / "basis_resolution.csv")
    ap.add_argument("--offline", action="store_true", help="use cached raw files only")
    args = ap.parse_args()
    events = read_ledger(args.ledger)
    resolved, recs = resolve(events, IssuerSources(offline=args.offline))
    output_text = "".join(json.dumps(e.model_dump(mode="json"), sort_keys=True) + "\n" for e in resolved)
    tmp_output = args.output.with_name(args.output.name + ".tmp")
    tmp_output.write_text(output_text)
    tmp_output.replace(args.output)
    args.table.parent.mkdir(parents=True, exist_ok=True)
    tmp_table = args.table.with_name(args.table.name + ".tmp")
    with tmp_table.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(recs[0].keys()))
        w.writeheader()
        w.writerows(recs)
    tmp_table.replace(args.table)
    cash = [r for r in recs if r["reason"] != "not a cash dividend"]
    tiers = {t: sum(r["tier"] == t for r in cash) for t in (1, 2, 3)}
    unresolved = [r for r in cash if r["basis_after"] == "UNRESOLVED"]
    print(f"{len(cash)} cash rows -> tier1 {tiers[1]}, tier2 {tiers[2]}, tier3 {tiers[3]}, unresolved {len(unresolved)}")
    for r in unresolved:
        print(f"  {r['event_id']:24s} {r['reason']}")
    print(f"wrote {args.output} and {args.table}")


if __name__ == "__main__":
    main()

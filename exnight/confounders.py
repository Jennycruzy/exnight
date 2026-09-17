"""C5a: deterministic confounder flags for every event result.

Each flag is computed from saved first-party data (Reality ledger, event results, live
symbol metadata) or from the cached third-party Yahoo chart metadata, and carries its
evidence label in FLAG_LABELS. An event is `clean` when no flag is raised. The flags are
inputs to the clean-sample analysis; they never change a PDR value.

  gross_basis_conflict     notice amount differs from the Reality amount by more than 0.5%
                           (Reality rounds to 3-4 dp; rUPRO 0.298729 vs 0.299 is rounding). OBSERVED
                           2026-09-16 on rNXPI (0.8619 vs 1.014 = 0.85) and rMDT (0.54 vs
                           0.72 = 0.75): the notice figure is already net of a home-country
                           withholding, so the notice-based PDR denominator is too small.
  adjacent_cash_event      another cash dividend on the same symbol within +-1 calendar day
                           of the ex-date (daily payers such as rSATA): the pre/post window
                           straddles more than one dividend.
  noncash_action_30d       a split / reverse split on the same symbol within 30 days.
  relisted_after_event     the current spot listing's openTime is later than the ex-date
                           (Bitget re-lists tokens around corporate actions; the event's
                           bars belong to a previous listing). listing_age_days is recorded
                           for every event; the 2026-06-10 batch listing is not a flag.
  ex_date_after_gap        the ex-date follows a weekend or holiday, so the 20:00 rung spans
                           a closed market and the pre bar is up to 72h old.
  pre_bar_stale_24h        p_pre is more than 24h before the 20:00 ET cutoff.
  market_move_1pct         |rSPY move| over the pre->20:00 rung exceeds 1% (beta=1 proxy).
  high_yield_2pct          gross dividend > 2% of p_pre (special / large distribution).
  underlying_check_failed  Yahoo disagrees with the notice on ex-date or amount.
  leveraged_name_hint      Yahoo longName matches a leveraged/inverse ETF naming pattern.
                           ASSUMED: third-party name heuristic, not a product parameter.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

import pandas as pd

from .calendar import LEDGER_PATH, read_ledger

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "data" / "results"
REALITY_LEDGER = ROOT / "data" / "ledger" / "reality_notice59.jsonl"
UNDERLYING_RAW = ROOT / "data" / "raw" / "underlying"
AMOUNT_REL_TOL = 0.005   # Reality rounds to 3-4 dp; the notice carries up to 8 dp
LEVERAGED_RE = re.compile(r"\b(2x|3x|ultra(?:pro|short)?|bull|bear|inverse|daily)\b", re.I)
FLAG_LABELS = {
    "gross_basis_conflict": "OBSERVED (notice vs Reality)", "adjacent_cash_event": "OBSERVED (Reality)",
    "noncash_action_30d": "OBSERVED (Reality)", "relisted_after_event": "OBSERVED (instruments openTime)",
    "ex_date_after_gap": "OBSERVED (event study)", "pre_bar_stale_24h": "OBSERVED (event study)",
    "market_move_1pct": "OBSERVED (rSPY proxy, beta=1 ASSUMED)", "high_yield_2pct": "OBSERVED (event study)",
    "underlying_check_failed": "OBSERVED (third-party Yahoo)", "leveraged_name_hint": "ASSUMED (third-party name heuristic)",
    "reality_row_ambiguous": "OBSERVED (multiple Reality rows on same symbol/date)",
}


def yahoo_meta(ticker: str) -> dict:
    files = list(UNDERLYING_RAW.glob(f"{ticker}_*.json"))
    if not files:
        return {}
    return json.loads(max(files, key=lambda p: p.stat().st_mtime).read_text()).get("meta", {})


def flags_for(r: dict, notice: dict, reality: list[dict]) -> dict:
    ex = dt.date.fromisoformat(r["ex_date"])
    sym = r["symbol"]
    same = [a for a in reality if a["symbol"] == sym]
    match = [a for a in same if a["event_type"] == "CASH_DIV" and a["exchange_ex_date"] == r["ex_date"]]
    reality_amt = float(match[0]["cash_dividend_per_share"]) if len(match) == 1 and match[0].get("cash_dividend_per_share") is not None else None
    notice_amt = float(notice["gross_dividend_per_share"]) if notice.get("gross_dividend_per_share") is not None else None
    ratio = (notice_amt / reality_amt) if (reality_amt and notice_amt) else None
    cash_days = sorted(abs((dt.date.fromisoformat(a["exchange_ex_date"]) - ex).days)
                       for a in same if a["event_type"] == "CASH_DIV" and a["exchange_ex_date"] != r["ex_date"])
    noncash_days = sorted(abs((dt.date.fromisoformat(a["exchange_ex_date"]) - ex).days)
                          for a in same if a["event_type"] != "CASH_DIV")
    open_time = dt.datetime.fromisoformat(r["open_time"]).date() if r.get("open_time") else None
    meta = yahoo_meta(r["underlying"])
    mm = (r.get("market_move_pct") or {}).get("overnight_2000")
    f = dict(
        event_id=r["event_id"], symbol=sym, ex_date=r["ex_date"], usable=r["usable"],
        notice_amount=notice_amt, reality_amount=reality_amt, notice_over_reality=ratio,
        reality_matched=len(match) == 1, reality_row_ambiguous=len(match) > 1,
        nearest_cash_days=cash_days[0] if cash_days else None,
        nearest_noncash_days=noncash_days[0] if noncash_days else None,
        open_time=open_time.isoformat() if open_time else None,
        listing_age_days=(ex - open_time).days if open_time else None,
        instrument_type=meta.get("instrumentType"), long_name=meta.get("longName"),
        gross_basis_conflict=ratio is not None and abs(ratio - 1) > AMOUNT_REL_TOL,
        adjacent_cash_event=bool(cash_days) and cash_days[0] <= 1,
        noncash_action_30d=bool(noncash_days) and noncash_days[0] <= 30,
        relisted_after_event=open_time is not None and open_time > ex,
        ex_date_after_gap=bool(r.get("ex_date_is_monday")),
        pre_bar_stale_24h=(r.get("p_pre_staleness_h") or 0) > 24,
        market_move_1pct=mm is not None and abs(mm) > 1.0,
        high_yield_2pct=(r.get("dividend_yield_pct") or 0) > 2.0,
        underlying_check_failed=not str(r.get("underlying_div_check", "")).startswith("Yahoo agrees"),
        leveraged_name_hint=bool(meta.get("longName")) and bool(LEVERAGED_RE.search(meta["longName"])),
    )
    raised = [k for k in FLAG_LABELS if f[k]]
    f["flags"] = ";".join(raised)
    f["n_flags"] = len(raised)
    f["clean"] = r["usable"] and not raised
    return f


def build(results: list[dict], notice_ledger: list[dict], reality_ledger: list[dict]) -> pd.DataFrame:
    # Notice and Reality ledgers number same-day events differently (rSATA), so match on the
    # API symbol and the ex-date rather than on event_id.
    notice_by_key = {(e["symbol"], e["exchange_ex_date"]): e for e in notice_ledger}
    return pd.DataFrame([flags_for(r, notice_by_key.get((r["symbol"], r["ex_date"]), {}), reality_ledger) for r in results])


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="Flag confounders for an event-results file")
    ap.add_argument("--results", type=Path, default=RESULTS / "event_results.json")
    ap.add_argument("--output", type=Path, default=RESULTS / "confounders.csv")
    args = ap.parse_args()
    results = json.loads(args.results.read_text())
    notice = [e.model_dump(mode="json") for e in read_ledger(LEDGER_PATH)]
    reality = [e.model_dump(mode="json") for e in read_ledger(REALITY_LEDGER)]
    df = build(results, notice, reality)
    df.to_csv(args.output, index=False)
    print(f"{len(df)} events; {int(df.usable.sum())} usable; {int(df.clean.sum())} clean (no flag)")
    counts = {k: int(df[k].sum()) for k in FLAG_LABELS}
    for k, v in counts.items():
        print(f"  {k:26s} {v:3d}   {FLAG_LABELS[k]}")
    print("gross-basis conflicts:")
    print(df[df.gross_basis_conflict][["event_id", "notice_amount", "reality_amount", "notice_over_reality"]].to_string(index=False))
    print("clean events:", ", ".join(df[df.clean].event_id))


if __name__ == "__main__":
    main()

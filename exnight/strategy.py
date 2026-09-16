"""C3: BUY / EXIT / HOLD verdicts, and what each one requires.

A verdict is issued only when every input it depends on is resolved; otherwise the row
carries NO_SIGNAL and the reason. Nothing is defaulted.

  HOLD    the default for a holder: keep the token through the ex-date and receive the net
          dividend (gross x (1 - withholding)).
  EXIT    sell before the 20:00 ET cutoff and buy back at the first overnight bar. Issued
          only when the *lower bound* of the expected price drop beats what the holder
          forfeits plus the round trip:
              (pdr_hat - Z * se) * gross - net - cost_per_share > 0
          pdr_hat / se are the M1 estimate for the 20:00 rung (ESTIMATED, sample named in
          the row); cost_per_share is fee + walk from the latest after-hours book (sell) and
          overnight book (buy) for the notional (OBSERVED-NOW scenario).
  BUY     buy before the snapshot to collect the net dividend. Suppressed on every event
          while `eligibility_verified` is false, because Bitget has not published the
          snapshot time; the row shows what the arithmetic would be, labelled suppressed.

Ex-post mode applies the same rule to realised events, replacing the estimate with the
realised 20:00 PDR, so the rule's hit rate can be reported instead of asserted.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pandas as pd

from .calendar import read_ledger
from .costs import NOTIONALS, latest_samples, load_depth, walk_cost

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "data" / "results"
Z = 2.0
EXIT_RUNG = "overnight_2000"
SELL_SESSION, BUY_SESSION = "after_hours", "overnight"   # sell before 20:00 ET, buy back after


def estimate(summary: dict, sample: str) -> dict:
    s = summary[sample]["rungs"][EXIT_RUNG]["slope"]
    if s["pdr"] is None or s["se"] is None:
        raise ValueError(f"{sample}: no {EXIT_RUNG} slope estimate")
    return dict(pdr_hat=float(s["pdr"]), se=float(s["se"]), n=int(s["n"]), sample=sample)


def round_trip_cost(samples: dict, spot: str | None, price: float, fee: float, notional: int) -> tuple[float | None, str | None, dict]:
    """Per-share cost of selling in after-hours and buying back overnight at `price`."""
    sell_s = samples.get((spot, SELL_SESSION)) if spot else None
    buy_s = samples.get((spot, BUY_SESSION)) if spot else None
    ws, why_s = walk_cost(sell_s, "sell", notional)
    wb, why_b = walk_cost(buy_s, "buy", notional)
    meta = dict(sell_book_ts=getattr(sell_s, "ts", None), sell_book_source=getattr(sell_s, "book_source", None),
                buy_book_ts=getattr(buy_s, "ts", None), buy_book_source=getattr(buy_s, "book_source", None))
    if ws is None or wb is None:
        return None, "; ".join(x for x in (why_s and f"sell: {why_s}", why_b and f"buy: {why_b}") if x), meta
    return 2 * fee * price + (ws + wb) * price, None, meta


def verdict_row(*, event_id: str, symbol: str, spot: str | None, ex_date: str, gross: float | None, net: float | None,
                basis: str, eligible: bool, price: float | None, price_label: str, fee: float, fee_label: str,
                drop_ratio: float, drop_se: float, drop_label: str, samples: dict, notional: int) -> dict:
    row = dict(event_id=event_id, symbol=symbol, spot_symbol=spot, ex_date=ex_date, notional_usd=notional,
               gross_dividend=gross, net_dividend=net, basis=basis, price=price, price_label=price_label,
               fee_rate=fee, fee_label=fee_label, drop_ratio=drop_ratio, drop_se=drop_se, drop_label=drop_label,
               cost_per_share=None, exit_edge_lower=None, exit_edge_point=None, buy_edge_point=None,
               verdict="NO_SIGNAL", buy="SUPPRESSED: eligibility snapshot time unpublished" if not eligible else None,
               reason=None, **{k: None for k in ("sell_book_ts", "sell_book_source", "buy_book_ts", "buy_book_source")})
    if basis != "GROSS" or gross is None or net is None:
        row["reason"] = f"cash basis {basis}; gross basis required"; return row
    if price is None:
        row["reason"] = "no reference price"; return row
    cost, why, meta = round_trip_cost(samples, spot, price, fee, notional)
    row.update(meta)
    if cost is None:
        row["reason"] = why; return row
    row["cost_per_share"] = cost
    row["exit_edge_point"] = drop_ratio * gross - net - cost
    row["exit_edge_lower"] = (drop_ratio - Z * drop_se) * gross - net - cost
    row["buy_edge_point"] = net - drop_ratio * gross - cost
    row["verdict"] = "EXIT" if row["exit_edge_lower"] > 0 else "HOLD"
    if eligible and row["buy_edge_point"] > 0:
        row["buy"] = "BUY"
    return row


def ex_ante(pending: list[dict], tickers: dict[str, dict], samples: dict, est: dict, fee_by_spot: dict[str, float]) -> pd.DataFrame:
    rows = []
    for e in pending:
        spot = e["spot_symbol"]
        t = tickers.get(spot, {})
        last = float(t["lastPrice"]) if t.get("lastPrice") else None
        for n in NOTIONALS:
            rows.append(verdict_row(
                event_id=e["event_id"], symbol=e["symbol"], spot=spot, ex_date=e["exchange_ex_date"],
                gross=float(e["gross_dividend_per_share"]) if e["gross_dividend_per_share"] is not None else None,
                net=float(e["net_dividend_per_share"]) if e["net_dividend_per_share"] is not None else None,
                basis=e["cash_dividend_basis"], eligible=bool(e["eligibility_verified"]),
                price=last, price_label="OBSERVED ticker lastPrice at run time",
                fee=fee_by_spot[spot], fee_label="OBSERVED live symbol takerFeeRate",
                drop_ratio=est["pdr_hat"], drop_se=est["se"],
                drop_label=f"ESTIMATED M1 {est['sample']} {EXIT_RUNG} slope, n={est['n']}",
                samples=samples, notional=n))
    return pd.DataFrame(rows)


def ex_post(results: list[dict], ledger_by_id: dict[str, dict], samples: dict) -> pd.DataFrame:
    rows = []
    for r in results:
        if not r["usable"] or r["pdr"].get(EXIT_RUNG) is None:
            continue
        e = ledger_by_id[r["event_id"]]
        for n in NOTIONALS:
            rows.append(verdict_row(
                event_id=r["event_id"], symbol=r["symbol"], spot=e["spot_symbol"], ex_date=r["ex_date"],
                gross=r["gross_dividend"], net=r["net_dividend"], basis=e["cash_dividend_basis"],
                eligible=bool(e["eligibility_verified"]), price=r["p_pre"], price_label="OBSERVED p_pre",
                fee=float(r["fee_rate"]), fee_label=r["fee_label"],
                drop_ratio=float(r["pdr"][EXIT_RUNG]), drop_se=0.0, drop_label=f"REALISED {EXIT_RUNG} PDR",
                samples=samples, notional=n))
    return pd.DataFrame(rows)


def main() -> None:
    import argparse
    from .market import BitgetPublic
    ap = argparse.ArgumentParser(description="Issue BUY/EXIT/HOLD verdicts")
    ap.add_argument("--ledger", type=Path, default=ROOT / "data" / "ledger" / "reality_notice59.jsonl")
    ap.add_argument("--results", type=Path, default=RESULTS / "event_results_reality.json")
    ap.add_argument("--summary", type=Path, default=RESULTS / "summary_reality.json")
    ap.add_argument("--sample", default="floor_None", help="summary block supplying the 20:00 estimate")
    args = ap.parse_args()

    ledger = [e.model_dump(mode="json") for e in read_ledger(args.ledger)]
    by_id = {e["event_id"]: e for e in ledger}
    samples = latest_samples(load_depth())
    est = estimate(json.loads(args.summary.read_text()), args.sample)

    api = BitgetPublic()
    uni = api.rtokens()
    fee_by_spot = {s.symbol: float(s.taker_fee) for s in uni.values()}
    tickers = {t["symbol"]: t for t in api.tickers()}
    today = dt.date.today().isoformat()
    pending = [e for e in ledger if e["event_type"] == "CASH_DIV" and e["exchange_ex_date"] > today and e["spot_symbol"] in fee_by_spot]
    ante = ex_ante(pending, tickers, samples, est, fee_by_spot)
    ante.to_csv(RESULTS / "signals.csv", index=False)

    post = ex_post(json.loads(args.results.read_text()), by_id, samples)
    post.to_csv(RESULTS / "signals_expost.csv", index=False)

    print(f"estimate: {est['sample']} {EXIT_RUNG} pdr_hat={est['pdr_hat']:.3f} se={est['se']:.3f} (n={est['n']}), Z={Z}")
    print(f"ex-ante: {len(pending)} pending events -> {ante.verdict.value_counts().to_dict()}; BUY: {ante.buy.value_counts().to_dict()}")
    print(ante[ante.notional_usd == 5000][["event_id", "ex_date", "price", "gross_dividend", "net_dividend", "cost_per_share", "exit_edge_lower", "verdict", "reason"]]
          .sort_values("ex_date").head(12).to_string(index=False))
    priced = post.dropna(subset=["cost_per_share"])
    print(f"ex-post: {len(post)} rows, {len(priced)} priced -> {priced.verdict.value_counts().to_dict()}; "
          f"realised exit edge > 0 on {(priced.exit_edge_point > 0).mean():.0%} of priced rows")


if __name__ == "__main__":
    main()

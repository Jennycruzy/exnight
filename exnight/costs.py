"""C4: deterministic round-trip cost fields for every event result.

Two evidence classes are kept apart and never mixed in one number without a label:

  event-time (OBSERVED at the event)   p_pre, p_post[rung], holding hours, fee rate in force
                                       on the ex-date, gross / withholding / net dividend.
  current-book scenario (OBSERVED-NOW) spread and depth-walk cost from the latest row in
                                       data/results/depth_samples.csv for the same symbol in
                                       the session that matches the rung. No historical book
                                       exists, so this is a scenario, not the event's fill.

Per (event, rung, notional) the EXIT round trip is: sell at p_pre before the cutoff, forfeit
the net dividend, buy back at p_post[rung].

  exit_gross_per_share   = p_pre - p_post                       (what the drop returned)
  cost_per_share         = fee*(p_pre + p_post) + walk_sell*p_pre + walk_buy*p_post
  exit_net_per_share     = exit_gross_per_share - net_dividend - cost_per_share
  exit_breakeven_pdr     = (net_dividend + cost_per_share) / gross_dividend

The mirror BUY leg (buy at p_pre, collect net, sell at p_post) is computed for symmetry but
flagged `buy_suppressed` because Bitget's eligibility snapshot time is unpublished.

Walk cost is the average fill premium over mid for a market order of the given notional,
taken from the sampled book (public book) or, for ticker-only symbols, the half ticker
spread when the notional fits inside the visible top-of-book on that side — otherwise None
with the reason. Nothing here defaults: any missing input yields None and a `cost_reason`.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pandas as pd

from .calendar import read_ledger

RESULTS = Path(__file__).resolve().parent.parent / "data" / "results"
NOTIONALS = (1_000, 5_000, 25_000)
# Which live session a rung's fill would take place in (rung times are session starts).
RUNG_SESSION = {"overnight_2000": "overnight", "premarket_0400": "pre_market",
                "open_0930": "regular", "open_1000": "regular", "close_1600": "after_hours"}
PRE_SESSION = "after_hours"   # p_pre is the last bar before 20:00 ET, i.e. inside after-hours


def latest_samples(depth: pd.DataFrame, *, as_of: dt.datetime | None = None,
                   max_age_seconds: int | None = None) -> dict[tuple[str, str], pd.Series]:
    """Most recent sample row per (spot_symbol, session), optionally freshness-gated."""
    if depth.empty:
        return {}
    d = depth.sort_values("ts")
    out = {(r.symbol, r.session): r for r in d.itertuples(index=False)}
    if as_of is None or max_age_seconds is None:
        return out
    now = pd.Timestamp(as_of)
    if now.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    return {
        key: row for key, row in out.items()
        if now - pd.Timestamp(row.ts).tz_convert("UTC") <= dt.timedelta(seconds=max_age_seconds)
    }


def walk_cost(sample: pd.Series | None, side: str, notional: int) -> tuple[float | None, str | None]:
    """Fill premium over mid as a fraction (not bp) for `side` in {'buy','sell'}, or (None, reason)."""
    if sample is None:
        return None, "no depth sample for this symbol/session"
    src = getattr(sample, "book_source", None)
    if src == "public_book":
        v = getattr(sample, f"{side}_walk_bp_{notional}")
        if v is None or pd.isna(v):
            return None, f"public book cannot fill ${notional:,} {side}"
        return float(v) / 1e4, None
    if src == "ticker_only":
        top = getattr(sample, "ticker_ask1_notional" if side == "buy" else "ticker_bid1_notional")
        spread_bp = getattr(sample, "ticker_spread_bp")
        if top is None or pd.isna(top) or spread_bp is None or pd.isna(spread_bp):
            return None, "ticker quote incomplete"
        if notional > float(top):
            return None, f"${notional:,} exceeds visible top-of-book (${float(top):,.0f}) on ticker-only symbol"
        return float(spread_bp) / 2e4, None
    return None, f"no quote surface (book_source={src})"


def cost_rows(results: list[dict], depth: pd.DataFrame, ledger_by_id: dict[str, dict]) -> list[dict]:
    samples = latest_samples(depth)
    out = []
    for r in results:
        if not r["usable"]:
            continue
        led = ledger_by_id.get(r["event_id"])
        spot = led["spot_symbol"] if led else None
        wr = led.get("withholding_rate") if led else None
        gross, net, p_pre = r["gross_dividend"], r["net_dividend"], r["p_pre"]
        fee = float(r["fee_rate"])
        pre_s = samples.get((spot, PRE_SESSION)) if spot else None
        for rung, session in RUNG_SESSION.items():
            p_post = r["p_post"].get(rung)
            post_s = samples.get((spot, session)) if spot else None
            hold_h = None
            if p_post is not None and r["p_post_ts"].get(rung) and r["p_pre_ts"]:
                hold_h = (pd.Timestamp(r["p_post_ts"][rung]) - pd.Timestamp(r["p_pre_ts"])).total_seconds() / 3600
            for n in NOTIONALS:
                row = dict(event_id=r["event_id"], symbol=r["symbol"], spot_symbol=spot, ex_date=r["ex_date"],
                           rung=rung, notional_usd=n, gross_dividend=gross, withholding_rate=None if wr is None else float(wr),
                           net_dividend=net, p_pre=p_pre, p_post=p_post, holding_hours=hold_h,
                           fee_rate=fee, fee_label=r["fee_label"],
                           pre_session=PRE_SESSION, post_session=session,
                           pre_book_ts=getattr(pre_s, "ts", None), pre_book_source=getattr(pre_s, "book_source", None),
                           post_book_ts=getattr(post_s, "ts", None), post_book_source=getattr(post_s, "book_source", None),
                           cost_basis="OBSERVED-NOW book scenario; fee/prices event-time",
                           exit_gross_per_share=None, fee_per_share=None, walk_sell_frac=None, walk_buy_frac=None,
                           walk_per_share=None, cost_per_share=None, exit_net_per_share=None, exit_breakeven_pdr=None,
                           buy_net_per_share=None, buy_suppressed="eligibility snapshot time unpublished",
                           cost_reason=None)
                if p_post is None:
                    row["cost_reason"] = f"no {rung} price"; out.append(row); continue
                ws, why_s = walk_cost(pre_s, "sell", n)
                wb, why_b = walk_cost(post_s, "buy", n)
                row["walk_sell_frac"], row["walk_buy_frac"] = ws, wb
                row["exit_gross_per_share"] = p_pre - p_post
                row["fee_per_share"] = fee * (p_pre + p_post)
                if ws is None or wb is None:
                    row["cost_reason"] = "; ".join(x for x in (why_s and f"sell: {why_s}", why_b and f"buy: {why_b}") if x)
                    out.append(row); continue
                row["walk_per_share"] = ws * p_pre + wb * p_post
                row["cost_per_share"] = row["fee_per_share"] + row["walk_per_share"]
                row["exit_net_per_share"] = row["exit_gross_per_share"] - net - row["cost_per_share"]
                row["exit_breakeven_pdr"] = (net + row["cost_per_share"]) / gross
                # BUY mirror: buy at p_pre (buy walk in the pre session), collect net, sell at p_post.
                wb_pre, _ = walk_cost(pre_s, "buy", n); ws_post, _ = walk_cost(post_s, "sell", n)
                if wb_pre is not None and ws_post is not None:
                    row["buy_net_per_share"] = net - (p_pre - p_post) - row["fee_per_share"] - (wb_pre * p_pre + ws_post * p_post)
                out.append(row)
    return out


def load_depth(path: Path = RESULTS / "depth_samples.csv") -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


def main() -> None:
    import argparse
    from .calendar import LEDGER_PATH
    ap = argparse.ArgumentParser(description="Price round-trip costs for an event-results file")
    ap.add_argument("--results", type=Path, default=RESULTS / "event_results.json")
    ap.add_argument("--ledger", type=Path, default=LEDGER_PATH)
    ap.add_argument("--output", type=Path, default=RESULTS / "event_costs.csv")
    args = ap.parse_args()
    results = json.loads(args.results.read_text())
    ledger = {e.event_id: e.model_dump(mode="json") for e in read_ledger(args.ledger)}
    rows = cost_rows(results, load_depth(), ledger)
    df = pd.DataFrame(rows)
    df.to_csv(args.output, index=False)
    priced = df.dropna(subset=["exit_net_per_share"])
    print(f"{len(df)} (event, rung, notional) rows; {len(priced)} fully priced, "
          f"{df.cost_reason.notna().sum()} with a cost_reason")
    if len(priced):
        g = priced.groupby(["rung", "notional_usd"])
        print(g.exit_breakeven_pdr.median().round(3).unstack().to_string())
        print("share of priced rows with exit_net > 0 by rung:")
        print((priced.exit_net_per_share > 0).groupby(priced.rung).mean().round(2).to_string())
    print("top cost_reasons:"); print(df.cost_reason.value_counts().head(6).to_string())


if __name__ == "__main__":
    main()

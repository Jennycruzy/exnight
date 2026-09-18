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

Net entitlement. Only events matched to the 2026-07-24 notice have a documented
withholding rate. For the rest the ledger carries a range (exnight.basis), and the
holder's net is bounded by net_low = gross x (1 - w_high) and net_high = gross x (1 - w_low).
A verdict is issued only if it is the same across that range:
  EXIT  if the lower-bound edge is positive even at net_high (the most the holder forfeits)
  HOLD  if the lower-bound edge is not positive even at net_low (the least they forfeit)
  otherwise NO_SIGNAL "net entitlement unresolved" with both edges shown.
`exit_edge_lower_zero_net` reports the edge if the dividend were withheld entirely; when
that is negative, HOLD does not depend on the withholding assumption at all.

Ex-post mode applies the same rule to realised events, replacing the estimate with the
realised 20:00 PDR, so the rule's hit rate can be reported instead of asserted.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import subprocess
import math
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from .calendar import read_ledger
from .costs import NOTIONALS, latest_samples, load_depth, walk_cost

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "data" / "results"
Z = 2.0
EXIT_RUNG = "overnight_2000"
SELL_SESSION, BUY_SESSION = "after_hours", "overnight"   # sell before 20:00 ET, buy back after
MAX_DEPTH_AGE_SECONDS = 26 * 60 * 60
RULES = ROOT / "strategy"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_run_manifest(rule: dict | None, *, rule_path: Path | None, inputs: list[Path], outputs: list[Path], tag: str) -> Path:
    """Save the exact rule/input/output hashes used for one strategy run."""
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True,
                                text=True, check=True, timeout=5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        commit = None
    payload = dict(
        generated_at=dt.datetime.now(dt.UTC).isoformat(), commit=commit,
        rule_id=rule.get("rule_id") if rule else None,
        rule_file=str(rule_path.relative_to(ROOT)) if rule_path else None,
        inputs={str(p.relative_to(ROOT)): _sha256(p) for p in inputs if p.exists()},
        outputs={str(p.relative_to(ROOT)): _sha256(p) for p in outputs if p.exists()},
    )
    path = RESULTS / f"run_manifest{tag}.json"
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n")
    tmp.replace(path)
    return path


def load_rule(path: Path) -> dict:
    """A frozen rule file. Its constants must equal the code's; a mismatch is an error so
    that a rule cannot silently mean something different from what was committed."""
    from . import basis
    rule = json.loads(path.read_text())
    for key, actual in (("z", Z), ("sell_session", SELL_SESSION), ("buy_session", BUY_SESSION),
                        ("notionals_usd", list(NOTIONALS)),
                        ("withholding_base", str(basis.WITHHOLDING_BASE)),
                        ("withholding_low", str(basis.WITHHOLDING_LOW)),
                        ("withholding_high", str(basis.WITHHOLDING_HIGH))):
        if rule[key] != actual:
            raise ValueError(f"{path.name}: {key}={rule[key]!r} but the code uses {actual!r}")
    if rule["rung"] not in ("overnight_2000", "premarket_0400", "open_0930", "open_1000", "close_1600"):
        raise ValueError(f"{path.name}: unknown rung {rule['rung']}")
    return rule


def estimate(summary: dict, sample: str, rung: str = EXIT_RUNG) -> dict:
    s = summary[sample]["rungs"][rung]["slope"]
    if (s["pdr"] is None or s["se"] is None or s.get("n", 0) < 3
            or not math.isfinite(float(s["pdr"])) or not math.isfinite(float(s["se"]))
            or float(s["se"]) < 0):
        raise ValueError(f"{sample}: no {rung} slope estimate")
    return dict(pdr_hat=float(s["pdr"]), se=float(s["se"]), n=int(s["n"]), sample=sample, rung=rung)


def round_trip_cost(samples: dict, spot: str | None, sell_price: float, fee: float,
                    notional: int, buy_price: float | None = None) -> tuple[float | None, str | None, dict]:
    """Per-share cost with the actual sell and buy prices when both are known.

    Ex-ante mode projects the post-event price from the estimated drop. Ex-post mode passes
    its realised post price. The two legs are never silently priced at the same value.
    """
    if buy_price is None:
        buy_price = sell_price
    if (not math.isfinite(sell_price) or sell_price <= 0 or not math.isfinite(buy_price)
            or buy_price <= 0):
        return None, "invalid reference price", {}
    sell_s = samples.get((spot, SELL_SESSION)) if spot else None
    buy_s = samples.get((spot, BUY_SESSION)) if spot else None
    ws, why_s = walk_cost(sell_s, "sell", notional)
    wb, why_b = walk_cost(buy_s, "buy", notional)
    meta = dict(sell_book_ts=getattr(sell_s, "ts", None), sell_book_source=getattr(sell_s, "book_source", None),
                buy_book_ts=getattr(buy_s, "ts", None), buy_book_source=getattr(buy_s, "book_source", None))
    if ws is None or wb is None:
        return None, "; ".join(x for x in (why_s and f"sell: {why_s}", why_b and f"buy: {why_b}") if x), meta
    return fee * (sell_price + buy_price) + ws * sell_price + wb * buy_price, None, meta


def verdict_row(*, event_id: str, symbol: str, spot: str | None, ex_date: str, gross: float | None, net: float | None,
                basis: str, eligible: bool, price: float | None, price_label: str, fee: float, fee_label: str,
                drop_ratio: float, drop_se: float, drop_label: str, samples: dict, notional: int,
                buy_price: float | None = None, net_low: float | None = None, net_high: float | None = None,
                net_verified: bool = True, basis_tier: int | None = None) -> dict:
    if net_low is None:
        net_low = net
    if net_high is None:
        net_high = net
    row = dict(event_id=event_id, symbol=symbol, spot_symbol=spot, ex_date=ex_date, notional_usd=notional,
               gross_dividend=gross, net_dividend=net, net_low=net_low, net_high=net_high, net_verified=net_verified,
               basis=basis, basis_tier=basis_tier, price=price, buy_price=buy_price,
               price_label=price_label,
               fee_rate=fee, fee_label=fee_label, drop_ratio=drop_ratio, drop_se=drop_se, drop_label=drop_label,
               cost_per_share=None, exit_edge_lower=None, exit_edge_point=None,
               exit_edge_lower_net_low=None, exit_edge_lower_net_high=None, exit_edge_lower_zero_net=None,
               buy_edge_point=None,
               verdict="NO_SIGNAL", buy="SUPPRESSED: eligibility snapshot time unpublished" if not eligible else None,
               reason=None, **{k: None for k in ("sell_book_ts", "sell_book_source", "buy_book_ts", "buy_book_source")})
    if basis != "GROSS" or gross is None or net is None:
        row["reason"] = f"cash basis {basis}; gross basis required"; return row
    if not all(math.isfinite(x) for x in (net_low, net_high)) or not (net_low <= net <= net_high):
        row["reason"] = "net entitlement range must bracket the base net"; return row
    if price is None:
        row["reason"] = "no reference price"; return row
    if not math.isfinite(price) or price <= 0:
        row["reason"] = "invalid reference price"; return row
    if not math.isfinite(drop_ratio) or not math.isfinite(drop_se) or drop_se < 0:
        row["reason"] = "invalid price-drop estimate"; return row
    if buy_price is None:
        buy_price = price - drop_ratio * gross
        row["buy_price"] = buy_price
    if not math.isfinite(buy_price) or buy_price <= 0:
        row["reason"] = "invalid post-event price"; return row
    cost, why, meta = round_trip_cost(samples, spot, price, fee, notional, buy_price)
    row.update(meta)
    if cost is None:
        row["reason"] = why; return row
    row["cost_per_share"] = cost
    lower_drop = (drop_ratio - Z * drop_se) * gross
    row["exit_edge_point"] = drop_ratio * gross - net - cost
    row["exit_edge_lower"] = lower_drop - net - cost
    row["exit_edge_lower_net_low"] = lower_drop - net_low - cost
    row["exit_edge_lower_net_high"] = lower_drop - net_high - cost
    row["exit_edge_lower_zero_net"] = lower_drop - cost
    row["buy_edge_point"] = net - drop_ratio * gross - cost
    if row["exit_edge_lower_net_high"] > 0:
        row["verdict"] = "EXIT"          # justified even if the holder would have kept the most
    elif row["exit_edge_lower_net_low"] <= 0:
        row["verdict"] = "HOLD"          # not justified even if the holder would have kept the least
    else:
        row["reason"] = (f"net entitlement unresolved: EXIT edge {row['exit_edge_lower_net_low']:+.4f}/share at "
                         f"net={net_low:.4f} but {row['exit_edge_lower_net_high']:+.4f} at net={net_high:.4f}")
    if eligible and row["buy_edge_point"] > 0:
        row["buy"] = "BUY"
    return row


def net_bounds(e: dict) -> dict:
    """net / net_low / net_high / net_verified / basis_tier from a ledger row (JSON form)."""
    gross = float(e["gross_dividend_per_share"]) if e.get("gross_dividend_per_share") is not None else None
    net = float(e["net_dividend_per_share"]) if e.get("net_dividend_per_share") is not None else None
    verified = bool(e.get("net_dividend_verified"))
    lo, hi = e.get("withholding_rate_low"), e.get("withholding_rate_high")
    if gross is None or net is None or verified or lo is None or hi is None:
        return dict(net=net, net_low=net, net_high=net, net_verified=verified, basis_tier=e.get("basis_tier"))
    return dict(net=net, net_low=gross * (1 - float(hi)), net_high=gross * (1 - float(lo)),
                net_verified=False, basis_tier=e.get("basis_tier"))


def ex_ante(pending: list[dict], tickers: dict[str, dict], samples: dict, est: dict, fee_by_spot: dict[str, float],
            rule_id: str | None = None) -> pd.DataFrame:
    rows = []
    rung = est.get("rung", EXIT_RUNG)
    for e in pending:
        spot = e["spot_symbol"]
        t = tickers.get(spot, {})
        last = float(t["lastPrice"]) if t.get("lastPrice") else None
        for n in NOTIONALS:
            rows.append(verdict_row(
                event_id=e["event_id"], symbol=e["symbol"], spot=spot, ex_date=e["exchange_ex_date"],
                gross=float(e["gross_dividend_per_share"]) if e["gross_dividend_per_share"] is not None else None,
                **net_bounds(e),
                basis=e["cash_dividend_basis"], eligible=bool(e["eligibility_verified"]),
                price=last, price_label="OBSERVED ticker lastPrice at run time",
                fee=fee_by_spot[spot], fee_label="OBSERVED live symbol takerFeeRate",
                drop_ratio=est["pdr_hat"], drop_se=est["se"],
                drop_label=f"ESTIMATED {est['sample']} {rung} slope, n={est['n']}",
                samples=samples, notional=n) | dict(rule=rule_id))
    return pd.DataFrame(rows)


def ex_post(results: list[dict], ledger_by_id: dict[str, dict], samples: dict, rung: str = EXIT_RUNG,
            rule_id: str | None = None) -> pd.DataFrame:
    rows = []
    for r in results:
        if not r["usable"] or r["pdr"].get(rung) is None:
            continue
        e = ledger_by_id[r["event_id"]]
        post_price = None
        if r["p_pre"] is not None and r["gross_dividend"] is not None:
            post_price = r["p_pre"] - float(r["pdr"][rung]) * r["gross_dividend"]
        for n in NOTIONALS:
            rows.append(verdict_row(
                event_id=r["event_id"], symbol=r["symbol"], spot=e["spot_symbol"], ex_date=r["ex_date"],
                gross=r["gross_dividend"], **net_bounds(e), basis=e["cash_dividend_basis"],
                eligible=bool(e["eligibility_verified"]), price=r["p_pre"], price_label="OBSERVED p_pre",
                fee=float(r["fee_rate"]), fee_label=r["fee_label"],
                drop_ratio=float(r["pdr"][rung]), drop_se=0.0, drop_label=f"REALISED {rung} PDR",
                samples=samples, notional=n, buy_price=post_price) | dict(rule=rule_id))
    return pd.DataFrame(rows)


def main() -> None:
    import argparse
    from .market import BitgetPublic
    ap = argparse.ArgumentParser(description="Issue BUY/EXIT/HOLD verdicts")
    ap.add_argument("--ledger", type=Path, default=ROOT / "data" / "ledger" / "reality_notice59_resolved.jsonl",
                    help="ledger after exnight.basis; carries basis tiers and withholding ranges")
    ap.add_argument("--results", type=Path, default=RESULTS / "event_results_reality.json")
    ap.add_argument("--summary", type=Path, default=RESULTS / "summary_reality.json")
    ap.add_argument("--sample", default="floor_None", help="summary block supplying the estimate")
    ap.add_argument("--rule", type=Path, help="frozen rule file (strategy/strategy_v1.json); overrides --summary/--sample and the rung")
    ap.add_argument("--tag", default="", help="suffix for signals outputs")
    args = ap.parse_args()
    rule = load_rule(args.rule) if args.rule else None
    rung = rule["rung"] if rule else EXIT_RUNG
    if rule:
        args.summary = ROOT / rule["estimate"]["summary_file"]
        args.sample = rule["estimate"]["sample"]
        args.ledger = ROOT / rule["ledger_file"]

    ledger = [e.model_dump(mode="json") for e in read_ledger(args.ledger)]
    by_id = {e["event_id"]: e for e in ledger}
    samples = latest_samples(load_depth(), as_of=dt.datetime.now(dt.UTC),
                             max_age_seconds=MAX_DEPTH_AGE_SECONDS)
    est = estimate(json.loads(args.summary.read_text()), args.sample, rung)
    if rule:
        want = rule["estimate"]
        if abs(est["pdr_hat"] - want["pdr_hat"]) > 1e-9 or abs(est["se"] - want["se"]) > 1e-9 or est["n"] != want["n"]:
            raise ValueError(f"{args.rule.name}: summary estimate {est} differs from the frozen {want}")

    api = BitgetPublic()
    uni = api.rtokens()
    fee_by_spot = {s.symbol: float(s.taker_fee) for s in uni.values()}
    tickers = {t["symbol"]: t for t in api.tickers()}
    today = dt.datetime.now(dt.UTC).astimezone(ZoneInfo("America/New_York")).date().isoformat()
    pending = [e for e in ledger if e["event_type"] == "CASH_DIV" and e["exchange_ex_date"] > today and e["spot_symbol"] in fee_by_spot]
    rule_id = rule["rule_id"] if rule else None
    ante = ex_ante(pending, tickers, samples, est, fee_by_spot, rule_id)
    ante.to_csv(RESULTS / f"signals{args.tag}.csv", index=False)

    post = ex_post(json.loads(args.results.read_text()), by_id, samples, rung, rule_id)
    post.to_csv(RESULTS / f"signals_expost{args.tag}.csv", index=False)
    manifest = write_run_manifest(
        rule, rule_path=args.rule if rule else None,
        inputs=[args.summary, args.ledger, args.results],
        outputs=[RESULTS / f"signals{args.tag}.csv", RESULTS / f"signals_expost{args.tag}.csv"],
        tag=args.tag,
    )

    print(f"rule: {rule_id or 'none'}; estimate: {est['sample']} {rung} pdr_hat={est['pdr_hat']:.3f} se={est['se']:.3f} (n={est['n']}), Z={Z}")
    print(f"run manifest: {manifest}")
    print(f"ex-ante: {len(pending)} pending events -> {ante.verdict.value_counts().to_dict()}; BUY: {ante.buy.value_counts().to_dict()}")
    print(ante[ante.notional_usd == 5000][["event_id", "ex_date", "price", "gross_dividend", "net_dividend", "cost_per_share", "exit_edge_lower", "verdict", "reason"]]
          .sort_values("ex_date").head(12).to_string(index=False))
    priced = post.dropna(subset=["cost_per_share"])
    print(f"ex-post: {len(post)} rows, {len(priced)} priced -> {priced.verdict.value_counts().to_dict()}; "
          f"realised exit edge > 0 on {(priced.exit_edge_point > 0).mean():.0%} of priced rows")


if __name__ == "__main__":
    main()

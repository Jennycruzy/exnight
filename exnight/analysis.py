"""Aggregate the per-event results into the numbers the write-up reports.

Estimator. Dividing each event's price move by its dividend gives a ratio whose noise is
inversely proportional to the dividend yield: a $0.15 dividend on a $1,000 stock (MU) turns
ordinary minute-to-minute noise into a PDR of ±200. The literature therefore estimates the
ex-day effect cross-sectionally: regress the ex-day return on the dividend yield,

    (P_post - P_pre) / P_pre  =  a  -  PDR * (D / P_pre)  +  e

so PDR is the slope, every event contributes in proportion to how much it can tell us, and
the standard error is honest. The same regression is run for the underlying so the two are
compared on identical footing. A second regression uses the saved market-adjusted return
for each rung as an analytic confounder check; it is not substituted into the execution
strategy, which must price the actual token move. Simple mean and median of the raw ratios are reported too,
with and without a yield floor, so the reader can see how much the estimator choice moves
the answer (it moves it a lot; that is a finding, not a nuisance).

Nothing here touches Bitget. It only reads data/results/event_results.json.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

RESULTS = Path(__file__).resolve().parent.parent / "data" / "results"
RUNG_ORDER = ["overnight_2000", "premarket_0400", "open_0930", "open_1000", "close_1600"]


def load() -> list[dict]:
    return json.loads((RESULTS / "event_results.json").read_text())


def frame(rows: list[dict]) -> pd.DataFrame:
    out = []
    for r in rows:
        d = dict(event_id=r["event_id"], symbol=r["symbol"], usable=r["usable"],
                 reason=r["exclusion_reason"], gross=r["gross_dividend"], p_pre=r["p_pre"],
                 yield_pct=r["dividend_yield_pct"], u_pdr=r["underlying_pdr"],
                 u_close=r["underlying_close_pre"], u_open=r["underlying_open_ex"],
                 div_check=r["underlying_div_check"], weekend=r["weekend_list_2026_07_17"],
                 p_close_pre=r.get("p_close_pre"), pdr_literature=r.get("pdr_literature"),
                 gap_min=r.get("gap_pre_to_2000_min"), monday=r.get("ex_date_is_monday"),
                 jump_ts=r.get("jump_ts"), jump_over_div=r.get("jump_over_dividend"))
        for k in RUNG_ORDER:
            d[f"pdr_{k}"] = r["pdr"].get(k)
            d[f"p_{k}"] = r["p_post"].get(k)
            d[f"abnormal_{k}"] = (r.get("abnormal_move_pct") or {}).get(k)
        out.append(d)
    return pd.DataFrame(out)


def _robust_standard_errors(x: np.ndarray, y: np.ndarray, groups: np.ndarray | None = None) -> tuple[float | None, float | None]:
    """Return HC3 and one-way cluster-by-group slope standard errors.

    The frozen strategy keeps the original OLS `se`; these diagnostics make repeated
    symbols and leverage visible without silently changing strategy_v1.
    """
    if len(x) < 3:
        return None, None
    X = np.column_stack((np.ones(len(x)), x))
    try:
        xtx_inv = np.linalg.inv(X.T @ X)
        beta = xtx_inv @ X.T @ y
        resid = y - X @ beta
        leverage = np.einsum("ij,jk,ik->i", X, xtx_inv, X)
        denom = np.maximum(1.0 - leverage, 1e-8)
        meat_hc3 = X.T @ ((resid / denom)[:, None] ** 2 * X)
        hc3 = xtx_inv @ meat_hc3 @ xtx_inv
        hc3_se = float(np.sqrt(max(hc3[1, 1], 0.0)))
        cluster_se = None
        if groups is not None:
            unique = np.unique(groups)
            if len(unique) >= 2:
                meat = np.zeros((2, 2))
                for group in unique:
                    z = X[groups == group].T @ resid[groups == group]
                    meat += np.outer(z, z)
                correction = (len(unique) / (len(unique) - 1)) * ((len(x) - 1) / (len(x) - 2))
                clustered = correction * xtx_inv @ meat @ xtx_inv
                cluster_se = float(np.sqrt(max(clustered[1, 1], 0.0)))
        return hc3_se, cluster_se
    except (FloatingPointError, np.linalg.LinAlgError, ValueError):
        return None, None


def slope_pdr(p_pre: pd.Series, p_post: pd.Series, gross: pd.Series,
              groups: pd.Series | None = None) -> dict:
    """OLS slope plus robust diagnostic errors; returns n used."""
    m = p_pre.notna() & p_post.notna() & gross.notna()
    x = (gross[m] / p_pre[m]).to_numpy(float)
    y = (p_post[m] / p_pre[m] - 1).to_numpy(float)
    group_values = groups[m].to_numpy() if groups is not None else None
    if len(x) < 3:
        return dict(n=int(len(x)), pdr=None, se=None, hc3_se=None, cluster_se=None,
                    intercept=None, r2=None)
    if not np.isfinite(x).all() or not np.isfinite(y).all() or np.allclose(x, x[0]):
        return dict(n=int(len(x)), pdr=None, se=None, hc3_se=None, cluster_se=None,
                    intercept=None, r2=None)
    res = stats.linregress(x, y)
    hc3_se, cluster_se = _robust_standard_errors(x, y, group_values)
    return dict(n=int(len(x)), pdr=-res.slope, se=res.stderr, intercept=res.intercept,
                hc3_se=hc3_se, cluster_se=cluster_se, r2=res.rvalue ** 2, p_value=res.pvalue)


def slope_market_adjusted(p_pre: pd.Series, abnormal_pct: pd.Series, gross: pd.Series,
                          groups: pd.Series | None = None) -> dict:
    """Estimate PDR after subtracting the saved proxy return for the same interval."""
    m = p_pre.notna() & abnormal_pct.notna() & gross.notna()
    x = (gross[m] / p_pre[m]).to_numpy(float)
    y = (abnormal_pct[m] / 100).to_numpy(float)
    group_values = groups[m].to_numpy() if groups is not None else None
    if len(x) < 3:
        return dict(n=int(len(x)), pdr=None, se=None, hc3_se=None, cluster_se=None,
                    intercept=None, r2=None)
    if not np.isfinite(x).all() or not np.isfinite(y).all() or np.allclose(x, x[0]):
        return dict(n=int(len(x)), pdr=None, se=None, hc3_se=None, cluster_se=None,
                    intercept=None, r2=None)
    res = stats.linregress(x, y)
    hc3_se, cluster_se = _robust_standard_errors(x, y, group_values)
    return dict(n=int(len(x)), pdr=-res.slope, se=res.stderr, intercept=res.intercept,
                hc3_se=hc3_se, cluster_se=cluster_se, r2=res.rvalue ** 2, p_value=res.pvalue)


def robustness(u: pd.DataFrame, k: str) -> dict:
    """How much the slope depends on a few high-yield points."""
    base = slope_pdr(u.p_pre, u[f"p_{k}"], u.gross, u.symbol)
    if base["pdr"] is None:
        return dict(n=base["n"])
    loo = [slope_pdr(u.drop(i).p_pre, u.drop(i)[f"p_{k}"], u.drop(i).gross)["pdr"] for i in u.index]
    top3 = u.sort_values("yield_pct").iloc[:-3]
    m = u.p_pre.notna() & u[f"p_{k}"].notna()
    return dict(n=base["n"], loo_min=float(min(loo)), loo_max=float(max(loo)),
                drop_top3_yield=slope_pdr(top3.p_pre, top3[f"p_{k}"], top3.gross),
                ratio_of_sums=float((u.p_pre[m] - u[f"p_{k}"][m]).sum() / u.gross[m].sum()),
                top3_symbols=list(u.sort_values("yield_pct").symbol.iloc[-3:]))


def summarize(df: pd.DataFrame, yield_floor_pct: float | None = None,
              clean_2000: bool = False, max_gap_min: float = 5.0,
              keep_ids: set[str] | None = None) -> dict:
    """clean_2000 restricts to events whose 20:00 ET pre and post bars are within
    `max_gap_min` minutes and whose ex-date follows a normal trading day, so that the
    rung measures the adjustment itself and not a weekend or an illiquid gap.
    keep_ids restricts to an explicit event set (the confounder-clean sample)."""
    u = df[df.usable].copy()
    if yield_floor_pct is not None:
        u = u[u.yield_pct >= yield_floor_pct]
    if clean_2000:
        u = u[(u.gap_min <= max_gap_min) & (~u.monday.astype(bool))]
    if keep_ids is not None:
        u = u[u.event_id.isin(keep_ids)]
    out = dict(events_total=int(len(df)), events_usable=int(df.usable.sum()),
               yield_floor_pct=yield_floor_pct, clean_2000=clean_2000,
               confounder_clean=keep_ids is not None, n_after_floor=int(len(u)),
               robustness_2000=robustness(u, "overnight_2000"),
               exclusions=df[~df.usable][["event_id", "reason"]].to_dict("records"), rungs={})
    for k in RUNG_ORDER:
        col = u[f"pdr_{k}"].dropna()
        out["rungs"][k] = dict(
            n=int(len(col)), mean=float(col.mean()) if len(col) else None,
            median=float(col.median()) if len(col) else None,
                slope=slope_pdr(u.p_pre, u[f"p_{k}"], u.gross, u.symbol),
            market_adjusted_slope=slope_market_adjusted(u.p_pre, u[f"abnormal_{k}"], u.gross, u.symbol),
        )
    lit = u.pdr_literature.dropna()
    out["rtoken_literature_convention"] = dict(
        n=int(len(lit)), mean=float(lit.mean()) if len(lit) else None,
        median=float(lit.median()) if len(lit) else None,
               slope=slope_pdr(u.p_close_pre, u.p_open_0930, u.gross, u.symbol))
    ucol = u.u_pdr.dropna()
    out["underlying"] = dict(n=int(len(ucol)), mean=float(ucol.mean()) if len(ucol) else None,
                             median=float(ucol.median()) if len(ucol) else None,
                             slope=slope_pdr(u.u_close, u.u_open, u.gross, u.symbol))
    return out


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="Summarise an event-results file")
    ap.add_argument("--results", type=Path, default=RESULTS / "event_results.json")
    ap.add_argument("--confounders", type=Path, default=RESULTS / "confounders.csv")
    ap.add_argument("--tag", default="", help="suffix for event_table/summary outputs")
    args = ap.parse_args()
    df = frame(json.loads(args.results.read_text()))
    df.to_csv(RESULTS / f"event_table{args.tag}.csv", index=False)
    report = {f"floor_{f}": summarize(df, f) for f in (None, 0.2, 0.5)}
    report["clean_2000"] = summarize(df, None, clean_2000=True)
    report["clean_2000_floor_0.2"] = summarize(df, 0.2, clean_2000=True)
    conf = args.confounders
    if conf.exists():   # written by exnight.confounders; absent -> no clean-sample block, never a default
        clean_ids = set(pd.read_csv(conf).query("clean").event_id)
        report["confounder_clean"] = summarize(df, None, keep_ids=clean_ids)
        report["confounder_clean_2000"] = summarize(df, None, clean_2000=True, keep_ids=clean_ids)
    (RESULTS / f"summary{args.tag}.json").write_text(json.dumps(report, indent=1, default=str))
    for name, s in report.items():
        print(f"\n== {name}: {s['n_after_floor']} of {s['events_usable']} usable of {s['events_total']} events")
        print(f"{'rung':16s} {'n':>3s} {'mean':>8s} {'median':>8s} | {'slope PDR':>9s} {'se':>7s} {'n':>3s}")
        for k, r in s["rungs"].items():
            sl = r["slope"]
            print(f"{k:16s} {r['n']:3d} {r['mean'] if r['mean'] is not None else float('nan'):8.3f} "
                  f"{r['median'] if r['median'] is not None else float('nan'):8.3f} | "
                  f"{(sl['pdr'] if sl['pdr'] is not None else float('nan')):9.3f} "
                  f"{(sl['se'] if sl['se'] is not None else float('nan')):7.3f} {sl['n']:3d}")
        lt = s["rtoken_literature_convention"]; sl = lt["slope"]
        print(f"{'rTOKEN close->open':16s} {lt['n']:3d} {lt['mean']:8.3f} {lt['median']:8.3f} | "
              f"{sl['pdr']:9.3f} {sl['se']:7.3f} {sl['n']:3d}")
        rb = s["robustness_2000"]
        if "loo_min" in rb:
            d3 = rb["drop_top3_yield"]
            print(f"  20:00 robustness: LOO [{rb['loo_min']:.2f}, {rb['loo_max']:.2f}]; drop top-3 yield {rb['top3_symbols']} -> "
                  f"{d3['pdr']:.2f} ± {d3['se']:.2f} (n={d3['n']}); ratio of sums {rb['ratio_of_sums']:.2f}")
        uu = s["underlying"]; sl = uu["slope"]
        print(f"{'UNDERLYING':16s} {uu['n']:3d} {uu['mean']:8.3f} {uu['median']:8.3f} | "
              f"{sl['pdr']:9.3f} {sl['se']:7.3f} {sl['n']:3d}")


if __name__ == "__main__":
    main()

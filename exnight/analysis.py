"""Aggregate the per-event results into the numbers the write-up reports.

Estimator. Dividing each event's price move by its dividend gives a ratio whose noise is
inversely proportional to the dividend yield: a $0.15 dividend on a $1,000 stock (MU) turns
ordinary minute-to-minute noise into a PDR of ±200. The literature therefore estimates the
ex-day effect cross-sectionally: regress the ex-day return on the dividend yield,

    (P_post - P_pre) / P_pre  =  a  -  PDR * (D / P_pre)  +  e

so PDR is the slope, every event contributes in proportion to how much it can tell us, and
the standard error is honest. The same regression is run for the underlying so the two are
compared on identical footing. Simple mean and median of the raw ratios are reported too,
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
                 div_check=r["underlying_div_check"], weekend=r["weekend_trading"],
                 p_close_pre=r.get("p_close_pre"), pdr_literature=r.get("pdr_literature"))
        for k in RUNG_ORDER:
            d[f"pdr_{k}"] = r["pdr"].get(k)
            d[f"p_{k}"] = r["p_post"].get(k)
        out.append(d)
    return pd.DataFrame(out)


def slope_pdr(p_pre: pd.Series, p_post: pd.Series, gross: pd.Series) -> dict:
    """Slope estimator with standard error; returns n used."""
    m = p_pre.notna() & p_post.notna() & gross.notna()
    x = (gross[m] / p_pre[m]).to_numpy(float)
    y = (p_post[m] / p_pre[m] - 1).to_numpy(float)
    if len(x) < 3:
        return dict(n=int(len(x)), pdr=None, se=None, intercept=None, r2=None)
    res = stats.linregress(x, y)
    return dict(n=int(len(x)), pdr=-res.slope, se=res.stderr, intercept=res.intercept,
                r2=res.rvalue ** 2, p_value=res.pvalue)


def summarize(df: pd.DataFrame, yield_floor_pct: float | None = None) -> dict:
    u = df[df.usable].copy()
    if yield_floor_pct is not None:
        u = u[u.yield_pct >= yield_floor_pct]
    out = dict(events_total=int(len(df)), events_usable=int(df.usable.sum()),
               yield_floor_pct=yield_floor_pct, n_after_floor=int(len(u)),
               exclusions=df[~df.usable][["event_id", "reason"]].to_dict("records"), rungs={})
    for k in RUNG_ORDER:
        col = u[f"pdr_{k}"].dropna()
        out["rungs"][k] = dict(
            n=int(len(col)), mean=float(col.mean()) if len(col) else None,
            median=float(col.median()) if len(col) else None,
            slope=slope_pdr(u.p_pre, u[f"p_{k}"], u.gross),
        )
    lit = u.pdr_literature.dropna()
    out["rtoken_literature_convention"] = dict(
        n=int(len(lit)), mean=float(lit.mean()) if len(lit) else None,
        median=float(lit.median()) if len(lit) else None,
        slope=slope_pdr(u.p_close_pre, u.p_open_0930, u.gross))
    ucol = u.u_pdr.dropna()
    out["underlying"] = dict(n=int(len(ucol)), mean=float(ucol.mean()) if len(ucol) else None,
                             median=float(ucol.median()) if len(ucol) else None,
                             slope=slope_pdr(u.u_close, u.u_open, u.gross))
    return out


def main() -> None:
    df = frame(load())
    df.to_csv(RESULTS / "event_table.csv", index=False)
    report = {f"floor_{f}": summarize(df, f) for f in (None, 0.2, 0.5)}
    (RESULTS / "summary.json").write_text(json.dumps(report, indent=1, default=str))
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
        uu = s["underlying"]; sl = uu["slope"]
        print(f"{'UNDERLYING':16s} {uu['n']:3d} {uu['mean']:8.3f} {uu['median']:8.3f} | "
              f"{sl['pdr']:9.3f} {sl['se']:7.3f} {sl['n']:3d}")


if __name__ == "__main__":
    main()

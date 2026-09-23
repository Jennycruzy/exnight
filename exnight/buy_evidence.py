"""Would buying before the ex-date to collect the dividend have paid?

Descriptive, over the 127 usable discovery events: buy at the last pre-cutoff price, sell at the
04:00 ET rung, receive the dividend if counted as a holder, pay the taker fee on both legs plus
round-trip slippage. The scenarios bracket what cannot be known in advance: whether Bitget's
unpublished snapshot counts the buyer, and how much tax is withheld.

This uses realised prices, so it is not a strategy test. It shows whether the BUY side could be
worth enabling if the snapshot time were known. It could not: the price falls by about the whole
dividend, so even the most favourable case loses the costs.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "data" / "results"
EVENT_RESULTS = RESULTS / "event_results_resolved.json"
OUTPUT = RESULTS / "buy_capture_evidence.json"
RUNG = "premarket_0400"
SCENARIOS = (  # (label, counted as holder, withholding)
    ("counted, no withholding", True, 0.0),
    ("counted, 30% withholding", True, 0.30),
    ("not counted", False, None),
)
SLIPPAGE_BPS = (10, 25)


def frame() -> pd.DataFrame:
    rows = [dict(event_id=r["event_id"], symbol=r["symbol"], p0=r["p_pre"],
                 p1=(r["p_post"] or {}).get(RUNG), gross=r["gross_dividend"], fee=r["fee_rate"])
            for r in json.loads(EVENT_RESULTS.read_text()) if r["usable"]]
    return pd.DataFrame(rows).dropna()


def build() -> dict:
    d = frame()
    out = {"label": "DESCRIPTIVE_REALISED_PRICES_NOT_A_STRATEGY_TEST", "rung": RUNG, "events": len(d),
           "definition": "buy at the last pre-cutoff price, sell at the 04:00 ET rung, receive the dividend if counted, "
                         "pay taker fee on both legs plus round-trip slippage",
           "scenarios": []}
    for label, counted, withholding in SCENARIOS:
        dividend = d.gross * (1 - withholding) if counted else 0.0
        for slip in SLIPPAGE_BPS:
            r = (d.p1 - d.p0 + dividend) / d.p0 - (2 * d.fee + slip / 10_000)
            out["scenarios"].append(dict(
                scenario=label, counted=counted, withholding=withholding, slippage_bps=slip,
                mean_bps=float(1e4 * r.mean()), median_bps=float(1e4 * r.median()),
                share_positive=float((r > 0).mean()),
                mean_bps_excluding_rsata=float(1e4 * r[d.symbol != "rSATA"].mean())))
    OUTPUT.write_text(json.dumps(out, indent=2) + "\n")
    return out


if __name__ == "__main__":
    for s in build()["scenarios"]:
        print(f"{s['scenario']:26} slip {s['slippage_bps']:>3} bps: mean {s['mean_bps']:6.1f} bps, "
              f"wins {100 * s['share_positive']:.0f}%")

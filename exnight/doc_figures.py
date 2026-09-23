"""Regenerate the figures quoted in docs/m2.md and docs/v3.md from committed inputs.

Every value is formatted exactly as the document prints it, so a test can assert that each
published row still appears verbatim. Nothing here is new analysis: the slopes use
`exnight.analysis.slope_pdr`, and the cluster bootstrap is the one described in docs/m2.md
(resample symbols with replacement, 2,000 draws, percentile 95% interval) with a fixed seed.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .analysis import slope_pdr

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "data" / "results"
LEDGER = ROOT / "data" / "ledger" / "reality_notice59_resolved.jsonl"
EVENT_RESULTS = RESULTS / "event_results_resolved.json"
V3_DIAGNOSTIC = RESULTS / "v3_historical_diagnostic.json"
V3_SIGNALS = RESULTS / "signals_v3.csv"
RUNGS = ("overnight_2000", "premarket_0400", "open_0930")
BOOTSTRAP_DRAWS = 2000
BOOTSTRAP_SEED = 0


def usable_frame() -> pd.DataFrame:
    ledger = {e["event_id"]: e for e in map(json.loads, LEDGER.read_text().splitlines())}
    rows = []
    for r in json.loads(EVENT_RESULTS.read_text()):
        if not r["usable"]:
            continue
        row = dict(event_id=r["event_id"], symbol=r["symbol"], ex_date=r["ex_date"], p_pre=r["p_pre"],
                   gross=r["gross_dividend"], tier=ledger[r["event_id"]].get("basis_tier"))
        row |= {rung: (r["p_post"] or {}).get(rung) for rung in RUNGS}
        rows.append(row)
    return pd.DataFrame(rows)


def _fit(frame: pd.DataFrame, rung: str) -> dict:
    return slope_pdr(frame.p_pre, frame[rung].astype(float), frame.gross, frame.symbol)


def _num(value: float) -> str:
    """Two decimals with a true minus sign, as the documents print them."""
    return f"{value:.2f}".replace("-", "−")


def _slope(frame: pd.DataFrame, rung: str, r2: bool = False) -> str:
    s = _fit(frame, rung)
    text = f"{_num(s['pdr'])} ± {s['se']:.2f}"
    return text + f" (r² {s['r2']:.2f}".replace("0.", ".", 1) + ")" if r2 else text


def cluster_ci(frame: pd.DataFrame, rung: str = "overnight_2000") -> str:
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    symbols = frame.symbol.unique()
    by_symbol = {s: frame[frame.symbol == s] for s in symbols}
    draws = []
    for _ in range(BOOTSTRAP_DRAWS):
        sample = pd.concat([by_symbol[s] for s in rng.choice(symbols, len(symbols), replace=True)])
        fit = slope_pdr(sample.p_pre, sample[rung].astype(float), sample.gross)
        if fit["pdr"] is not None:
            draws.append(fit["pdr"])
    lo, hi = np.percentile(draws, [2.5, 97.5])
    return f"[{_num(lo)}, {_num(hi)}]"


def m2_rows() -> list[str]:
    """Table rows of docs/m2.md section 2, in document order."""
    u = usable_frame()
    no_sata = u[u.symbol != "rSATA"]
    tier23 = u[u.tier.isin([2, 3])]
    cuts = [
        ("all usable", u, (True, False, False)),
        ("tier 1 (notice batch, Jun–Jul)", u[u.tier == 1], (True, False, False)),
        ("tier 2/3 (issuer-verified)", tier23, (True, True, True)),
        ("tier 2/3 excl. rSATA", tier23[tier23.symbol != "rSATA"], (False, True, False)),
        ("all excl. rSATA", no_sata, (False, False, False)),
    ]
    rows = []
    for label, frame, show_r2 in cuts:
        rows.append(f"| {label} | {len(frame)} | {_slope(frame, 'overnight_2000', show_r2[0])} | "
                    f"{cluster_ci(frame)} | {_slope(frame, 'premarket_0400', show_r2[1])} | "
                    f"{_slope(frame, 'open_0930', show_r2[2])} |")
    windows = [
        # docs/m2.md (a frozen, hashed input) labels this window "1 Jun – 6 Jul", but its figures
        # were computed on ex-dates through 1 July (51 events); the two 6 July events are not in
        # it. The label is kept verbatim and the erratum is in docs/verification.md.
        ("1 Jun – 6 Jul", no_sata[no_sata.ex_date <= "2026-07-01"]),
        ("August", no_sata[(no_sata.ex_date >= "2026-08-01") & (no_sata.ex_date <= "2026-08-31")]),
        ("September", no_sata[no_sata.ex_date >= "2026-09-01"]),
    ]
    for label, frame in windows:
        rows.append(f"| {label} | {len(frame)} | {_slope(frame, 'overnight_2000')} | "
                    f"{_slope(frame, 'premarket_0400')} | {_slope(frame, 'open_0930')} |")
    return rows


def m2_robustness() -> str:
    u = usable_frame().assign(yield_=lambda d: d.gross / d.p_pre)
    trimmed = u.drop(u.yield_.nlargest(3).index)
    no_sata = u[u.symbol != "rSATA"]
    no_sata_trimmed = no_sata.drop(no_sata.yield_.nlargest(3).index)
    return (f"all-usable 20:00 without the three highest-yield events {_slope(trimmed, 'overnight_2000')}; "
            f"all excl.\nrSATA without top-3 {_slope(no_sata_trimmed, 'overnight_2000')}.")


def v3_rows() -> list[str]:
    """Rows and figures of docs/v3.md's results section."""
    report = json.loads(V3_DIAGNOSTIC.read_text())
    rows = []
    for fold, label in zip(report["runs"]["primary__hardest"]["folds"], ("August", "September")):
        e = fold["estimate"]
        rows.append(f"| {label} | {e['pdr']:.3f} ± {e['se']:.3f} | {e['n']} | {e['lower_ratio']:.3f} | "
                    f"{fold['exit']} | {fold['hold']} | {fold['no_signal']} |")
    signals = pd.read_csv(V3_SIGNALS)
    first = signals.iloc[0]
    rows.append(f"`{first.pdr_hat:.3f} ± {first.pdr_se:.3f}`")
    rows.append(f"**{first.lower_ratio:.3f}**")
    rows.append(f"The sample is {report['sample']['total']} events: the {report['sample']['frozen_ex_ante']} frozen "
                f"pre-decision events plus the {report['sample']['verified_additions']} issuer-verified additions")
    return rows

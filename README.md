# EXNIGHT

Some price moves are news. Some are arithmetic. EXNIGHT measures which is which on tokenized stocks.

A corporate-action factor for Bitget Reality rTokens: how the 24/5 market reprices the ex-dividend
date, and whether a holder should HOLD through it or EXIT and re-enter.

## Result (2026-09-17, `docs/m1.md`)

- 185 Reality corporate actions on 59 rTokens since 2026-06-01; 58 events with a verified gross basis.
- At 20:00 ET on ex-date eve the rToken has already dropped by **1.11 ± 0.12 ×** the gross dividend
  (leave-one-out 1.02–1.23), the same as the underlying share (1.01 ± 0.42). The adjustment is complete
  in the first overnight bar; 04:00 and 09:30 add nothing.
- The holder receives 0.70 × gross (30 % withholding, DOCUMENTED). Selling before 20:00 and buying back
  after therefore captures ≈ 0.4 D at the point estimate — about 12 bp of price at the median 0.29 % yield,
  against a 20 bp round-trip taker fee. **Verdict: HOLD on the broad universe; EXIT clears costs only on
  yield ≥ 1 % events (6 of 58).** With the realised drop known, EXIT has a positive net edge on 3 of 38
  priced events (`data/results/signals_expost.csv`).
- BUY is suppressed on every event: Bitget has not published the eligibility snapshot time.
- Forward verdicts (`data/results/signals.csv`, issued 2026-09-17 before the events): rAVGO ex
  2026-09-21 **HOLD** at $1k/$5k/$25k, rVST ex 2026-09-21 **HOLD** at $1k — both invariant to the
  withholding rate and negative even if the dividend were withheld entirely. Gross basis for these
  comes from issuer evidence (`exnight/basis.py`), not from Bitget's own figures.

## What is in the repository

- `exnight/market.py` — public Bitget v3/v2 adapter; universe from `instruments` (`symbolType=stock, isReality=yes`), fees, candles with history pagination.
- `exnight/calendar.py` — Reality corporate-action ledger with live market calendar; gross basis only on an exact notice match.
- `exnight/basis.py` — tiered gross-basis resolver (issuer-declared / realised dividends, first-party corroboration) and net-entitlement bounds; verdicts must be invariant to the withholding range.
- `exnight/eventstudy.py`, `analysis.py` — per-event PDR at session rungs, slope regressions, leave-one-out and drop-top-3 robustness, market-adjusted slope.
- `exnight/confounders.py` — deterministic confounder flags with evidence labels.
- `exnight/costs.py`, `strategy.py` — round-trip cost from sampled depth; BUY/EXIT/HOLD with NO_SIGNAL when any input is unresolved.
- `scripts/depth_snapshot.py`, `scripts/paper_trade.py` — session-labelled depth sampler; Agent Hub dry-run / demo / guarded live order path with an evidence chain.
- `docs/verification.md` — every product rule and API parameter, with how it was verified.

Every claim is labelled DOCUMENTED (first-party Bitget page), OBSERVED (we ran it, date given) or ASSUMED.

## Reproduce

    python -m pytest -q
    python -m exnight.calendar --source reality --start-date 2026-06-01 --output data/ledger/reality_notice59.jsonl
    python -m exnight.basis
    python -m exnight.eventstudy --ledger data/ledger/reality_notice59.jsonl --output data/results/event_results_reality.json
    python -m exnight.confounders --results data/results/event_results_reality.json --output data/results/confounders_reality.csv
    python -m exnight.analysis --results data/results/event_results_reality.json --confounders data/results/confounders_reality.csv --tag _reality
    python -m exnight.costs --results data/results/event_results_reality.json --ledger data/ledger/reality_notice59.jsonl --output data/results/event_costs_reality.csv
    python -m exnight.strategy

## Known limits

No historical order book exists for the event dates (Tardis carries the public Reality book only
≈12:00–23:00 UTC for symbols with a real book, and no trades); current depth is an OBSERVED-NOW scenario.
Forward events resolve only where issuer evidence exists; 8 pending events remain UNRESOLVED and most
ticker-only symbols cannot be sized beyond $1k.
The demo venue rejects Reality spot orders, so paper execution is dry-run only.

# EXNIGHT handoff — 2026-09-17

EXNIGHT is a research and guarded execution prototype for Bitget Reality rTokens. It is
not a blanket production trading system. The saved event-study outputs are measurement
artifacts and must be regenerated after source-rule changes.

Source hardening commit: `888a12a`. Validation on the VPS: 56 tests pass. A no-submit live-market
dry run for `RAVGOUSDT` completed and produced the expected order payload/evidence; no real
order was sent. A $10 request was correctly rejected after precision rounding put it below
the exchange minimum, and a $15 request passed the dry-run guard.

## Verified foundation

- The live Bitget instruments response selects Reality stock tokens; token names are not
  inferred.
- Reality corporate actions are saved with request, response, fetch time and source labels.
- The event study uses Bitget's live Reality market calendar and market-state windows.
- Split normalization uses the inverse of Reality's new-shares/old-shares ratio and rejects
  an in-listing split that has no verified halt window. A prior split at a relisting boundary
  is not applied to the new listing's series.
- Cash-dividend gross basis is assigned only for an exact symbol/ex-date notice match.
  Unmatched rows remain `UNRESOLVED`.
- Event-study failures are recorded per event, so one bad source row does not abort a batch.
- Strategy costs can use separate sell and buy prices. Current depth remains an
  `OBSERVED-NOW` scenario, not historical fill evidence.
- `scripts/paper_trade.py` supports dry-run, demo (`--live-paper`) and guarded real (`--live`)
  modes. It uses live symbol precision/minimums, executable-side liquidity, least-privilege
  environment variables, status polling and cancellation of an order that remains open.

## Reproduction

Use the VPS virtual environment:

    .venv/bin/python -m pytest -q
    .venv/bin/python -m exnight.calendar --source reality --start-date 2026-06-01 --output data/ledger/reality_notice59.jsonl
    .venv/bin/python -m exnight.basis          # -> data/ledger/reality_notice59_resolved.jsonl, data/results/basis_resolution.csv
    .venv/bin/python -m exnight.eventstudy --ledger data/ledger/reality_notice59.jsonl --output data/results/event_results_reality.json
    .venv/bin/python -m exnight.confounders --results data/results/event_results_reality.json --output data/results/confounders_reality.csv
    .venv/bin/python -m exnight.analysis --results data/results/event_results_reality.json --confounders data/results/confounders_reality.csv --tag _reality
    .venv/bin/python -m exnight.costs --results data/results/event_results_reality.json --ledger data/ledger/reality_notice59.jsonl --output data/results/event_costs_reality.csv
    .venv/bin/python -m exnight.strategy

Depth collection can run repeatedly; it stores raw responses in a microsecond-stamped run
directory and deduplicates the results CSV by timestamp, symbol and session.

The corrected Reality artifacts are installed and downstream reports regenerated (2026-09-17):
185 actions, 124 unresolved cash bases, 58 usable event rows, 27 confounder-clean rows.
Headline: 20:00 ET slope 1.11 ± 0.12 (all usable), leave-one-out [1.02, 1.23] — the rToken
reprices by the gross dividend in the first overnight bar, the same as the underlying. The
pre-fix 0.66 result is withdrawn (docs/m1.md §3). Cost report: 870 event/rung/notional
scenarios, 351 fully priced. Strategy report: 174 ex-post rows (58 events × notionals), 81
priced, EXIT on 3 events (rLABD, rSPXU, rSTRC), HOLD otherwise; the EXIT edge clears the
20 bp round-trip fee only on yield ≥ 1 % events. Ex-ante: 75 pending events, all NO_SIGNAL,
because no Reality row after the July notice window has a resolved gross basis — a basis
rule for Reality rows is required before any forward verdict can be issued. BUY remains
suppressed (snapshot time unpublished). These are measurement and guarded-execution
outputs, not proof of a profitable or historically executable strategy.

Tardis (probed 2026-09-17, free first-of-month sample): Bitget Reality symbols are archived
(RAVGO from 2026-06-05, RTSM 06-08, RSPY 06-10, RKO 07-01, RBABA 07-30). `books`/`books1`
carry a real Reality book only for symbols with a public book and only ≈12:00–23:00 UTC;
empty 00:00–10:00 UTC (the overnight window) and empty all day for routed-liquidity symbols
(RSPY, RBITI). `publicTrade`/`trade` are empty everywhere. Usable for the 19:59 ET sell-leg
spread on real-book symbols only.

## Basis resolution and forward verdicts (2026-09-17, item 2)

`exnight/basis.py` resolves gross basis for rows the builder left UNRESOLVED, without
changing the builder rule. Gross and net are separate questions:

- Gross tiers: 1 = 2026-07-24 notice match (builder); 2 = Reality amount and ex-date match
  an issuer-declared (Nasdaq) or realised (Yahoo) dividend; 3 = no issuer row yet, but the
  perp settlement notice (first-party, amount only), the issuer's announced next ex-date and
  the prior realised amount all agree (ASSUMED "unchanged"). Agreement between Bitget
  surfaces alone never resolves a basis. Issuer disagreement always leaves UNRESOLVED.
- Net: only tier 1 has a documented rate (30%). Others carry withholding base 0.30 with
  range [0, 0.30] (ASSUMED, per the rToken FAQ saved as `rtoken_faq_2026_06_23`). A verdict
  is issued only if unchanged across the range; `exit_edge_lower_zero_net` shows whether
  HOLD would survive full withholding.
- Result on the Reality ledger: 182 cash rows -> tier 1: 61, tier 2: 109, tier 3: 1,
  unresolved 11 (rTSM 2026-09-16 issuer ratio 0.79; rCRM/rHPE 2026-09-17 no issuer row yet
  and no first-party corroboration; rAPH, rSTM, rMDT, rMPWR, rPWR, rTSM Dec, rSTM Dec/Mar
  likewise). Raw evidence under `data/raw/basis/`.
- Ex-ante (`signals.csv`, 25 pending events): 24 HOLD rows, 51 NO_SIGNAL. rAVGO 2026-09-21
  (tier 2): HOLD at $1k/$5k/$25k, invariant to withholding and negative even at zero net
  (-0.55/-1.47/-3.17 per share; cost 1.12-3.73 vs 0.65 dividend). rVST 2026-09-21 (tier 3):
  HOLD at $1k (zero-net edge -0.18), NO_SIGNAL at $5k/$25k because only $1,410 is visible at
  bid1 on a ticker-only book. Remaining NO_SIGNAL reasons: 24 rows basis UNRESOLVED (8
  events), 27 rows notional exceeds visible top-of-book on ticker-only symbols. The only
  HOLD that depends on the withholding assumption is rSTRC 2026-09-30 at $1k.
- The ex-post study (`event_results_reality.json`) still uses the 58 tier-1 events; the
  resolved ledger admits up to 170 GROSS rows and has not yet been re-run through the
  event study.

## Frozen rule and forward recording (2026-09-17)

- `strategy/strategy_v1.json` is the first frozen rule: 04:00 ET rung, estimate from all 127
  issuer-verified events (0.966 ± 0.183), Z = 2, net range [0, 0.30], sessions, notionals and
  the sha256 of the code and inputs. It is never edited; a change is `strategy_v2.json`.
  `python -m exnight.strategy --rule strategy/strategy_v1.json --results data/results/event_results_resolved.json --tag _v1`
  writes `signals_v1.csv` / `signals_expost_v1.csv`; `run_manifest_v1.json` records the commit
  and hashes of that run. Decisions on record before the events: rAVGO 2026-09-21 HOLD at all
  notionals; rVST 2026-09-21 HOLD at $1k, NO_SIGNAL above.
- `scripts/record_event.py` samples ticker + public book for RAVGOUSDT, RVSTUSDT, RSATAUSDT once
  a minute from a system crontab (`crontab -l`), 2026-09-17 09:00Z to 2026-09-21 14:30Z, into
  `data/raw/recorder/20260921_rAVGO_rVST/<date>.jsonl` (append-only, raw). Commit the files at
  milestones; `cron.log` is ignored. rVST and rSATA show an empty public book with a live
  ticker (routed liquidity), rAVGO a real book — as in the depth samples.
- Scoring after 2026-09-21: fetch the 1m candles, rerun the event study for the two events,
  apply the rule with the realised 04:00 PDR, compare with `signals_v1.csv`. The rule file and
  the recorded signals are not touched. A Monday ex-date: the adjustment may land in the
  weekend session (rAVGO is on the 24/7 list; rVST is not) rather than Friday 20:00.

## Important limits

- No historical order book exists for the event dates. Current book/ticker observations do
  not prove historical execution.
- Overnight, pre-market, weekend and holiday coverage must be established before using a
  strategy estimate. Ticker-only quotes are marked separately from public depth.
- Bitget's dividend snapshot/eligibility time is unpublished; BUY remains suppressed.
- A complete spot split with a verified halt has not been observed in the saved sample.
- The current Reality ledger covers the notice assets, not the full live token universe.
- Statistical outputs are ordinary descriptive OLS estimates and remain sensitive to events;
  they are not a guarantee of profitability.

## Order safety

The real-order path is intentionally separate from the demo path. It does not alter SSH,
login keys, sudo, firewall, VSCode, Claude processes or scheduled tasks. A real order is not
placed by an ordinary dry run. After the script computes the symbol, side, price and
quantity, it requires:

    --live --confirm-live '<SYMBOL> <SIDE> <COMPUTED_QUANTITY>'

Use a small IOC/FOK limit order first. Confirm the live symbol, available balance, minimum
notional, displayed quote and exact computed quantity immediately before submission.

During this work no SSH service, login key, sudo rule, firewall, VSCode connection, Claude
process, or scheduled task was disabled, restarted, or modified. Existing SSH sessions were
left untouched; process counts can change naturally when a task finishes.

# EXNIGHT handoff — 2026-09-17

EXNIGHT is a research and guarded execution prototype for Bitget Reality rTokens. It is
not a blanket production trading system. The saved event-study outputs are measurement
artifacts and must be regenerated after source-rule changes.

Current code commit: `888a12a`. Validation on the VPS: 56 tests pass. A no-submit live-market
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
    .venv/bin/python -m exnight.calendar --source reality --start-date 2026-06-01 --output /tmp/reality.jsonl
    .venv/bin/python -m exnight.eventstudy --ledger /tmp/reality.jsonl
    .venv/bin/python -m exnight.analysis --results data/results/event_results.json
    .venv/bin/python -m exnight.costs

Depth collection can run repeatedly; it stores raw responses in a microsecond-stamped run
directory and deduplicates the results CSV by timestamp, symbol and session.

The saved Reality ledger and Reality event-study reports still contain the pre-fix derived
artifacts. A temporary post-fix rebuild validated 185 actions, 124 unresolved cash bases and
58 usable events, but it was intentionally not installed when this handoff was stopped.
Regenerate and review the downstream reports before using any strategy output.

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

During this session the SSH service remained active, two SSH sessions and two Claude
processes remained present, and the hourly depth task was not disabled or modified.

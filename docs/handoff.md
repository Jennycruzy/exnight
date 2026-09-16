# Project status — 2026-09-16

EXNIGHT is a Bitget Genesis Season 2 Alpha Factory research project. The current repository contains a live public-market adapter, a saved 63-event study, a split normaliser, and 17 passing tests.

## Current evidence

- The spot universe is selected from the live isReality and symbolType fields. The current response omits isRwa for the Reality rows.
- Bitget's public Reality market data now supplies spot corporate actions by Reality code. The older cash-dividend records endpoint remains a futures-only cross-check.
- The July notice has 63 rows across 59 assets and is spread over six weeks of ex-dates; it is not a single simultaneous batch.
- The saved event study has 60 usable price paths of 63 notice rows. Its point estimates are not net of observed execution costs.
- Spot split observations show old-token to new-token listing boundaries. A continuous spot split transition is not present in the current sample.
- platformTurnover24h is platform turnover, not order-book depth. The existing depth snapshot was taken at 07:48 ET, which is pre-market. It cannot answer regular-session executable liquidity.
- Eligibility timing is unpublished, so no BUY signal is permitted.

## Reproduction

Use the repository virtual environment:

    .venv/bin/python -m exnight.calendar
    .venv/bin/python -m exnight.eventstudy
    .venv/bin/python -m exnight.analysis
    .venv/bin/python scripts/render_m0.py

The first command still rebuilds the saved-notice ledger. The next calendar change should use Reality market data and retain the raw response, request parameters, fetch time and date-conversion label.

## Next work

1. Build the spot calendar from Reality dividends, with the saved notice as a reconciliation source. Keep unresolved amount basis and date timezone explicit.
2. Replace the fixed US holiday set with the live Bitget Reality calendar while retaining the source timezone.
3. Run depth snapshots during regular US hours at more than one time, and classify pre-market, regular, after-hours, overnight, weekend and holiday sessions separately.
4. Add deterministic fees, spread, depth walk and slippage to each event result. Historical books are unavailable, so current depth must be labelled as a scenario rather than an event-time fill.
5. Complete confounder review, then implement deterministic BUY, EXIT and HOLD outputs. Eligibility remains a hard suppression for BUY until Bitget documents the snapshot rule.
6. Use Agent Hub paper trading for the end-to-end demonstration after confirming the standard UTA order surface accepts Reality spot symbols.

The event study should not be reframed as a trading result until the calendar source and net execution model are corrected.

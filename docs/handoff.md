# Project status — 2026-09-16

EXNIGHT is a Bitget Genesis Season 2 Alpha Factory research project. The repository contains a live public-market adapter, a saved 63-row event study, a Reality corporate-action builder, a halt-aware normaliser, and 23 passing tests.

## What is verified

- The spot universe is selected from the live `instruments` response using `isReality == "yes"` and `symbolType == "stock"`. The current response omits `isRwa` for these rows, so it is recorded when present but is not used as the filter. No token-name pattern is used to construct the universe.
- Bitget's public Reality market data supplies spot corporate actions by Reality code. The older `cash-dividend-records` endpoint is a futures-only cross-check; it does not provide the spot event universe.
- The July notice has 63 rows across 59 assets and spans six weeks of ex-dates. It is not a single simultaneous batch.
- Reality timestamps are retained as raw UTC instants. The calendar date currently uses the UTC+8 convention that matches the saved first-party notice dates; Bitget does not document this timezone, so the conversion remains explicitly ASSUMED.
- Reality cash amounts that do not reconcile exactly to the saved notice remain `UNRESOLVED`. They cannot enter PDR arithmetic.
- The saved event study has 60 usable price paths of 63 notice rows. Those results are measurement output, not a net execution result.
- The event-study runner now records unresolved amounts, non-cash actions, missing live symbols, and missing spot symbols as exclusions. It passes the full event list into the normaliser so matching split records can be applied when they exist.
- Spot split observations show old-token to new-token listing boundaries. A continuous spot split transition is not present in the current sample, so the halt path is tested but not verified on a completed spot event.
- `platformTurnover24h` is platform turnover, not order-book depth. The existing depth observation was taken at 07:48 ET, which is pre-market; it cannot answer regular-session executable liquidity.
- Bitget stock spot access is 24/5, with weekend trading limited to a published subset. It is not universal 24/7 trading.
- Eligibility timing is unpublished. No BUY signal is permitted until the Bitget snapshot rule is verified.

## Reproduction

Use the repository virtual environment:

    .venv/bin/python -m exnight.calendar
    .venv/bin/python -m exnight.eventstudy
    .venv/bin/python -m exnight.analysis
    .venv/bin/python scripts/render_m0.py
    .venv/bin/pytest -q

The default calendar command rebuilds the saved-notice ledger. The Reality source is explicit and should first be written to a separate output while it is reconciled, for example:

    .venv/bin/python -m exnight.calendar --source reality --start-date 2026-06-01 --base-coin rMU --output /tmp/reality-rmu.jsonl

`rMU` above is an example of a value returned by the live `instruments` endpoint, not a hardcoded universe rule. A full Reality rebuild should enumerate the live API response and preserve each raw response, request, fetch time, and date-conversion label before replacing any saved ledger.

## Known limitations

- The event study still uses a fixed 2026 US holiday set. It must consume Bitget's live Reality calendar before another historical run is treated as final.
- The current results do not contain event-time spread, depth-walk slippage, or a complete round-trip cost. The visible book is a current scenario, not a historical fill. The event-study fee field is not sufficient to claim net P&L.
- `scripts/depth_snapshot.py` now labels sessions from the live `reality/market/states` and `reality/market/calendar` responses (regular, pre_market, after_hours, overnight, weekend, holiday) and stores every raw book, ticker and config under `data/raw/depth/<run>/`. Only one regular-session window (15:17–15:19 ET, 2026-09-16) has been sampled so far; off-hours windows are still missing.
- OBSERVED 2026-09-16 15:19 ET (regular session): 43 of 59 ledger symbols return an **empty public order book** while the ticker carries `bid1Price`/`ask1Price` with sizes (median ticker spread 3.9 bp, median ask1 notional ≈ $23k). Their `platformTurnover24h` is mostly 0. This is consistent with routed (StockRoute) liquidity that the public book does not display; it is not evidence that the token is untradeable. The 16 symbols with a public book show 2.6–14.6 bp spreads, ≈$60k–$780k resting within ±2%, and $5k / $25k buy walk costs of 1–28 bp / 1–54 bp. The depth column is recorded as `book_source` (`public_book` / `ticker_only`). Whether a ticker-only quote is actually fillable at `ask1Size` must be verified with a paper order, not inferred.
- The live `/api/v3/market/orderbook` response uses short keys `a`/`b`; the adapter normalises them to `asks`/`bids`.
- Of the 21 Sep forward events, `RAVGOUSDT` has a public book (8 bp, ≈$150k two-sided at ±2%) and `RVSTUSDT` is ticker-only (5 bp, platform turnover ≈ $20k/24h).
- The Reality endpoint has not supplied a spot split halt in the observed sample. Do not present the futures split-records halt as a spot observation.
- The Reality amount basis is only gross for rows that match the saved notice. Other rows remain unresolved.
- No strategy engine, paper order path, evidence view, or Agent Hub order verification has been completed.

## Next work

1. Build a separate Reality ledger for the live spot universe, starting with the 59 notice assets and then expanding to the full API universe. Compare dates, codes, amounts, action types, and listing continuity without inferring identifiers.
2. Replace the fixed holiday logic with the live Reality calendar and keep its timezone label in every result.
3. Run `scripts/depth_snapshot.py` again in after-hours, overnight, pre-market and weekend windows (regular is done once). Report ±0.5% and ±2% depth and walk costs at $1k, $5k, and $25k by session and by `book_source`.
4. Add deterministic fee, spread, depth-walk, slippage, holding-period, and withholding fields to each event result. Keep current-book scenarios separate from event-time observations.
5. Rebuild the event study from the Reality ledger, retain the full and clean samples, and complete the confounder review. Do not publish a trading verdict from the notice-only result.
6. Implement BUY, EXIT, and HOLD only after eligibility, gross/net basis, and net costs are resolved. Keep BUY suppressed when eligibility is unknown.
7. Confirm the standard UTA order surface accepts Reality spot symbols, then demonstrate paper execution with the evidence chain attached.

The repository is paused at a clean, reproducible measurement foundation. The strategy framing should remain undecided until the Reality calendar and executable-liquidity measurements are complete.

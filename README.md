# EXNIGHT

EXNIGHT measures how Bitget Reality rTokens reprice scheduled corporate actions and exposes
guarded HOLD / EXIT / BUY arithmetic. It is a research system with a manually confirmed order
path, not an unattended trading bot.

## Current status — 2026-09-19

- **90 tests pass** on the VPS with `python -m pytest`.
- `strategy/strategy_v1.json` is the untouched forward-validation rule. `strategy_v2.json`
  records corrected projected-buy-price and fresh-depth semantics for later use.
- The one-minute forward recorder is active for the September 21 events. The scoring script is
  offline and will not substitute a new quote or place an order.
- Optional Qwen evidence analysis is configured with `BITGET_QWEN_API_KEY`,
  `QWEN_BASE_URL=https://hackathon.bitgetops.com/v1`, and `QWEN_MODEL=qwen3.8-max`. Qwen never
  changes strategy verdicts.
- The Reality rebuild completed for 1,653 instruments, producing 1,695 validated events in
  `data/ledger/reality_full.jsonl`. Progress and recovered failures are recorded in
  `data/results/reality_full_build.json`. Not every instrument has an event in the date range.
- The full online basis pass resolved 1,374 cash rows and left 298 cash rows explicitly
  unresolved. The full event study has 568 usable rows; its outputs are tagged `full_online`.
- The online cost run produced 8,520 event/rung/notional scenarios, with 754 fully priced from
  current depth/ticker evidence. The remaining rows carry explicit liquidity reasons.

## Modules

- `exnight/market.py` — validated Bitget public adapter with bounded retries and candle paging.
- `exnight/calendar.py` — saved-source and Reality corporate-action ledgers.
- `exnight/basis.py` — issuer evidence, gross-basis tiers, and event-level withholding bounds.
- `exnight/normalizer.py` — inverse split-ratio adjustment with halt validation.
- `exnight/eventstudy.py`, `exnight/analysis.py` — session-rung PDR, market adjustment and
  OLS/robust diagnostics.
- `exnight/confounders.py`, `exnight/ai_confounder.py` — deterministic flags and optional,
  replayable Qwen prose evidence.
- `exnight/costs.py`, `exnight/strategy.py` — freshness-gated round-trip costs and
  deterministic BUY/EXIT/HOLD/NO_SIGNAL decisions.
- `scripts/record_event.py` — locked, deduplicated forward recorder.
- `scripts/depth_snapshot.py` — session-labelled depth with raw-response SHA-256 manifests.
- `scripts/score_forward.py` — offline forward-window scorer.
- `scripts/build_reality_ledger.py` — resumable complete-universe Reality ledger builder.
- `scripts/paper_trade.py` — precision-safe dry-run/guarded-live Agent Hub order evidence chain.
- `exnight/trading.py` — small wrapper around Bitget's official `bgc` Agent Hub CLI.
- `scripts/verify_evidence.py`, `scripts/healthcheck.py` — offline evidence and scheduler gates.

## Reproduce

    .venv/bin/python -m pytest -q
    .venv/bin/python scripts/verify_evidence.py
    .venv/bin/python scripts/build_reality_ledger.py --start-date 2026-06-01
    .venv/bin/python -m exnight.calendar --source reality --start-date 2026-06-01 --output data/ledger/reality_notice59.jsonl
    .venv/bin/python -m exnight.basis
    .venv/bin/python -m exnight.eventstudy --ledger data/ledger/reality_notice59.jsonl --output data/results/event_results_reality.json
    .venv/bin/python -m exnight.confounders --results data/results/event_results_reality.json --output data/results/confounders_reality.csv --reality-ledger data/ledger/reality_notice59_resolved.jsonl
    .venv/bin/python -m exnight.analysis --results data/results/event_results_reality.json --confounders data/results/confounders_reality.csv --tag _reality
    .venv/bin/python -m exnight.costs --results data/results/event_results_reality.json --ledger data/ledger/reality_notice59.jsonl --output data/results/event_costs_reality.csv
    .venv/bin/python -m exnight.strategy --rule strategy/strategy_v1.json --tag _v1

## Score the September 21 forward window

Run only after the recorder window ends:

    .venv/bin/python scripts/score_forward.py \
      data/raw/recorder/20260921_rAVGO_rVST/*.jsonl \
      --symbols RAVGOUSDT RVSTUSDT RSATAUSDT \
      --event-date 2026-09-21 \
      --rule strategy/strategy_v1.json \
      --ledger data/ledger/reality_notice59_resolved.jsonl \
      --signals data/results/signals_v1.csv \
      --output data/results/forward_score_v1.json

The result is incomplete if a cutoff sample is missing or late. Ticker-only quotes are labelled
as such and are not treated as public-depth fill evidence.

The latest health report is intentionally red because the recorder has one shared 57-minute
gap. The latest depth snapshot is fresh, but RVST and RSATA have ticker-only quotes rather than
two-sided public books. The system reports those limits instead of inventing fills.

## Safety and limits

- BUY remains suppressed because Bitget's eligibility snapshot time is unpublished.
- Historical event-time order books do not exist; current depth is an `OBSERVED-NOW` scenario.
- Unresolved issuer/tax rows remain explicit and cannot produce a non-invariant verdict.
- A real order requires a funded live UTA trade credential (or authorized Agentic account), a
  fresh displayed quote, the exact computed quantity, a two-sided public book, an
  available-balance check, and
  `--live --confirm-live '<SYMBOL> <SIDE> <QUANTITY>'`. One-order real notional is capped at
  $100 by default. `--live-paper` is refused because Bitget's generic demo path does not accept
  Reality symbols.
- The configured Bitget credential currently authenticates only with the documented demo header;
  the mainnet API returns environment error `40099`. Agent Hub is installed for the ubuntu user
  and sends Reality orders through the regular UTA `/api/v3/trade/place-order` surface. Bitget's
  current announcement says Reality order placement/cancellation does not require whitelist
  registration; Reality depth and platform-fills endpoints still do. The two-sided public-book
  guard therefore remains in force.
- Remaining work is tracked in [`docs/handoff.md`](docs/handoff.md): score the September 21
  window, install/authorize a funded live Agent Hub account, and perform a manually confirmed
  live preflight.
- See [`docs/handoff.md`](docs/handoff.md) for the full operational state and the host-security
  boundary. SSH/login configuration is deliberately not modified by the application.

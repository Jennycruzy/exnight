# EXNIGHT handoff — 2026-09-19

EXNIGHT is a research and guarded-execution system for Bitget Reality rTokens. It is not
an unattended trading bot. The strategy decision remains deterministic; Qwen is an optional
evidence/confounder analyst and cannot issue BUY, EXIT, or HOLD decisions.

## Current verified state

- VPS: `ubuntu@99.80.93.71`, project `/home/ubuntu/exnight`.
- Full regression suite: **88 passed** with `python -m pytest`.
- Existing VS Code SSH access was preserved. No SSH config, authorized key, sudo rule,
  firewall, reboot, or login setting was changed.
- `.env` is mode `600`; the supplied Bitget hackathon Qwen credential is read only as
  `BITGET_QWEN_API_KEY`.
- Qwen uses `https://hackathon.bitgetops.com/v1` and `qwen3.8-max`. A real request and a
  schema-valid confounder record were saved under `data/raw/ai_confounder/`.
- `strategy/strategy_v1.json` remains untouched. `strategy_v2.json` records the corrected
  projected-buy-price and fresh-depth semantics for later use.
- The Reality rebuild completed for 1,653 instruments with 1,695 schema-valid rows and no
  duplicate event IDs in `data/ledger/reality_full.jsonl`. Not all instruments have events.
  Resume now validates existing output and archives failures only when every instrument in
  the failed batch is complete, including retries with different batch boundaries.
  `data/results/reality_full_build.json` preserves recovered failures for audit.
- Full online basis resolution produced 1,374 gross-basis cash rows and 298 unresolved cash
  rows in `data/ledger/reality_full_resolved_online.jsonl`.
- The complete online event study produced 568 usable rows in
  `data/results/event_results_full_online.json`. The matching summary, confounders, costs and
  strategy outputs use the `full_online` suffix.
- The cost run produced 8,520 scenarios; 754 are fully priced from current depth/ticker
  evidence. The rest retain explicit missing-depth or insufficient-liquidity reasons.

## Implemented safeguards

- Bitget public calls now validate success envelopes and retry transient transport, 429 and
  5xx failures with bounded backoff.
- Reality rows are sorted canonically before ordinals are assigned, so API row order does not
  change event IDs within a rebuild.
- New Reality ledger rows retain an immutable instrument snapshot: listing time, status, fees,
  precision and minimum notional. Historical analysis uses that snapshot when present.
- Split normalization uses the inverse new-shares/old-shares ratio and rejects an in-listing
  split without both halt timestamps. Production-style 2:1 and 1:10 tests are present.
- Analysis reports OLS plus HC3 and symbol-clustered diagnostic errors; the frozen rule's OLS
  estimate is not silently changed.
- Ex-ante strategy costs use the projected post-event buy price rather than pricing both legs
  at the same value. Stale depth samples are excluded from the live strategy path.
- Recorder writes are locked, flushed and deduplicated by `(timestamp, symbol)`. Recording
  validation checks gaps, duplicates, ordering, too-fast samples and fresh timestamps.
- Depth runs write per-file SHA-256 manifests. `scripts/verify_evidence.py` verifies saved
  source, ledger, depth and Qwen evidence offline.
- `scripts/score_forward.py` scores the completed forward window from recorder data only; it
  never fetches a replacement quote or places an order.
- Cached Nasdaq and Yahoo-calendar responses replay offline, and missing Yahoo dividend caches
  now fail closed without a network fallback. The offline resolver verified 182 cash rows from
  the saved 185-action ledger: tier 1 = 61, tier 2 = 109, tier 3 = 1, unresolved = 11.
- Paper/live order sizing uses the executable side, exchange precision and minimum notional,
  requires a two-sided public book for live mode, performs a final quote and balance recheck,
  caps one real order at $100 by default, polls status and cancels an unfilled Reality order.
- The missing `bgc` dependency was removed. Native HMAC-signed calls use Bitget's Reality
  placement, order-info and cancellation endpoints. The official Reality endpoint is
  whitelist-only; `--live-paper` refuses because the generic demo path does not accept rTokens.
- Read-only authenticated preflight identified the configured Bitget trading key as demo-only:
  mainnet account assets returns environment error `40099`, while the documented `paptrading: 1`
  header authenticates. No mainnet trading key is installed and no live order was attempted.

## Scheduler

The existing one-minute forward recorder remains in the user crontab. Two additional user-level
jobs were added without touching SSH:

- minute 5 of every hour: `scripts/depth_snapshot.py`
- minute 10 of every hour: `scripts/healthcheck.py`, writing `data/results/health.json`

The scheduler is not a guarantee of executable liquidity. Public books may be empty while a
ticker still reports routed liquidity; those rows remain labelled `ticker_only`.

## Current monitoring result

The latest evidence check passed source, depth-manifest and Qwen-hash verification. The latest
health report deliberately remains **red** for recorder cadence: all three forward symbols have
one shared 3,419-second (about 57-minute) gap. Depth is fresh after a manual snapshot, but
`RVSTUSDT` and `RSATAUSDT` still have ticker-only quotes with no two-sided public book. This is
an evidence limitation, not something to hide by filling the gap with synthetic rows.

## Current build and remaining work

1. Full ledger ingestion, online basis resolution, event study, confounder analysis, cost
   scenarios and exploratory strategy outputs are complete. The 298 unresolved cash rows and
   current-book liquidity limits remain explicit in those artifacts.
2. Keep the recorder running through the September 21 window and score the actual 04:00 ET
   result against the frozen `strategy_v1.json` rule.
3. Treat a real order as a separate, manually confirmed preflight only. No unattended order,
   login change, firewall change, SSH restart, or key rotation is part of the application fix.

## September 21 forward score

After the recorder window ends, run:

    .venv/bin/python scripts/score_forward.py \
      data/raw/recorder/20260921_rAVGO_rVST/*.jsonl \
      --symbols RAVGOUSDT RVSTUSDT RSATAUSDT \
      --event-date 2026-09-21 \
      --rule strategy/strategy_v1.json \
      --ledger data/ledger/reality_notice59_resolved.jsonl \
      --signals data/results/signals_v1.csv \
      --output data/results/forward_score_v1.json

The report is `PASS` only when every requested event has on-time pre/post samples. A missing
weekend quote, late sample, empty book, or incomplete cost remains visible rather than being
converted into a fill assumption.

## Remaining evidence limits

- No historical order book exists for the old event dates. Current depth is an
  `OBSERVED-NOW` scenario; it is not historical fill evidence.
- Bitget's dividend eligibility snapshot time is unpublished, so BUY remains suppressed.
- Some issuer/basis rows remain `UNRESOLVED`; the strategy uses event-level withholding bounds
  and refuses a verdict when the answer changes across the range.
- The complete saved Reality ledger covers all 1,653 live rTokens; 999 instruments had at least
  one event in the selected date range.
- A real rToken fill has not been proven. The live path still requires credentials, displayed
  liquidity, a small notional, and the explicit confirmation string.

## Host-security boundary

The VPS still has the previously observed root-key and `NOPASSWD` exposure, inactive UFW and
old sensitive shell/session history. Those are host-maintenance items, not application changes.
They were intentionally not changed in this session because changing them without a second
verified access path could lock out the current VS Code SSH connection. The Qwen key supplied
for the hackathon was not rotated.

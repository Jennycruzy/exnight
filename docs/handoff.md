# EXNIGHT handoff — 2026-09-18

EXNIGHT is a research and guarded-execution system for Bitget Reality rTokens. It is not
an unattended trading bot. The strategy decision remains deterministic; Qwen is an optional
evidence/confounder analyst and cannot issue BUY, EXIT, or HOLD decisions.

## Current verified state

- VPS: `ubuntu@99.80.93.71`, project `/home/ubuntu/exnight`.
- Full regression suite: **79 passed**.
- Existing VS Code SSH access was preserved. No SSH config, authorized key, sudo rule,
  firewall, reboot, or login setting was changed.
- `.env` is mode `600`; the supplied Bitget hackathon Qwen credential is read only as
  `BITGET_QWEN_API_KEY`.
- Qwen uses `https://hackathon.bitgetops.com/v1` and `qwen3.8-max`. A real request and a
  schema-valid confounder record were saved under `data/raw/ai_confounder/`.
- `strategy/strategy_v1.json` remains untouched. `strategy_v2.json` records the corrected
  projected-buy-price and fresh-depth semantics for later use.

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
  source, depth and Qwen evidence offline.
- `scripts/score_forward.py` scores the completed forward window from recorder data only; it
  never fetches a replacement quote or places an order.
- Paper/live order sizing uses the executable side, exchange precision and minimum notional,
  performs a final quote recheck, caps one real order at $100 by default, polls status and
  attempts cancellation when an order remains open.

## Scheduler

The existing one-minute forward recorder remains in the user crontab. Two additional user-level
jobs were added without touching SSH:

- minute 5 of every hour: `scripts/depth_snapshot.py`
- minute 10 of every hour: `scripts/healthcheck.py`, writing `data/results/health.json`

The scheduler is not a guarantee of executable liquidity. Public books may be empty while a
ticker still reports routed liquidity; those rows remain labelled `ticker_only`.

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
- The current saved Reality ledger is the researched event set, not a complete rebuild of all
  1,653 live rTokens.
- A real rToken fill has not been proven. The live path still requires credentials, displayed
  liquidity, a small notional, and the explicit confirmation string.

## Host-security boundary

The VPS still has the previously observed root-key and `NOPASSWD` exposure, inactive UFW and
old sensitive shell/session history. Those are host-maintenance items, not application changes.
They were intentionally not changed in this session because changing them without a second
verified access path could lock out the current VS Code SSH connection. The Qwen key supplied
for the hackathon was not rotated.

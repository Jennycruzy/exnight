# Handoff — state as of 2026-09-16 ~12:00 UTC

Project **EXNIGHT** (repo name; the spec still says TAPE). Bitget AI Genesis S2, Alpha Factory.
Submissions close **2026-09-21**. Commit as jennycruzy, no AI attribution, maintainer-style messages.

## Where things stand

Done and pushed (`main`): market client (v3 instruments + v2 fees, candles with history fallback,
throttled), event ledger from Bitget's 24 July notice (63 events / 59 tokens), normaliser
(re-listing-aware, stale-extreme flag), event study (60 of 63 usable), analysis with robustness,
`docs/m0.md` rendered by `scripts/render_m0.py`, `docs/verification.md`, 11 tests passing
(`.venv/bin/pytest -q`; `-m "not live"` for offline).

Regenerate everything: `python -m exnight.calendar && python -m exnight.eventstudy && python -m exnight.analysis && python scripts/render_m0.py`.

## Findings that stand (all in verification.md / m0.md)
- Ex-date adjustment lands in the first bar after **20:00 ET on D−1**; clean subset slope
  1.01 ± 0.13 (n=20) but carried by 3 leveraged ETFs; without them 0.79 ± 0.60. Verdict: "EXIT
  indicated, not established". Close→open: rToken ≈ underlying, H₀ not rejected.
- Spot tokens are **re-listed** around splits (`launchTime` moves, old intraday history gone).
  `split-records` and `cash-dividend-records` are **perps-only**. `cashDividendPerShare` is **gross** (4 events).
- Candle `volume` = US consolidated tape. `platformTurnover24h` = Bitget internal matching only
  (StockRoute flow to Nasdaq/NYSE during US hours does not appear in it) — **do not conclude
  untradeable from it**.
- Fee: 0.05% promo to 31 Aug, 0.10% base now; StockRoute (US-hours) orders are charged **taker
  regardless**; off-hours the internal engine distinguishes maker/taker. Not yet in the cost model.
- Snapshot/eligibility time unpublished → every BUY suppressed (Law 9).

## The open decision (do this first next session)
Framing (Part VII) hinges on **US-hours executable depth**, not turnover.
1. Run `.venv/bin/python scripts/depth_snapshot.py` **between 09:30 and 16:00 ET on a weekday**
   (ideally twice, e.g. 10:00 and 14:00 ET). Off-hours sample already appended to
   `data/results/depth_samples.csv` (2026-09-16 07:48 ET: 43/59 empty; the 16 quoted had median
   ±2% depth $180k and all filled $25k).
2. If US-hours depth is real for most sample names → **strategy-first framing**, execution
   constrained to regular sessions (sell before 16:00 ET D−1 close, rebuy after 09:30 ET on D —
   the hold spans the 20:00 adjustment, no off-hours trade needed), two taker fees in the cost
   model. If depth is absent both sessions → measurement-first framing.
3. Either way, fold `platformTurnover24h` and the depth samples into the event table and m0 as
   stated constraints, labelled OBSERVED-NOW.

## Remaining build steps (spec v2 numbering)
- 5/7: extend C1 with perps `cash-dividend-records?type=pending` as forward calendar + cross-check;
  make C4 halt-aware for perps series (spot needs re-listing awareness, already done).
- 9: LLM confounder detection (Claude; classify only, record beside deterministic result).
- 10: rToken-vs-underlying chart (data in `data/results/event_table.csv`: `pdr_literature`, `u_pdr`).
- 11: C3 strategy engine — per-event BUY/EXIT/HOLD with PDR as a distribution, costs = fee(session) + spread/walk from depth samples, min-edge gate; BUY always suppressed.
- 12: C5 paper trade via Agent Hub `bgc` (`--paper-trading`, `--dry-run`); verify rToken spot
  orders are in the UTA surface first. Live forward event: **rAVGO and rVST ex 2026-09-21**
  (perps settle 2026-09-19 08:00 UTC+8). Install: `npx @bitget-ai/bitget-agent-installer upgrade-all --target all`.
- 13: C6 evidence layer, README, 3-minute video. Demo beat 0:00 should be the **re-listing**
  (symbol discontinuity fools an agent), not a 50% price drop — no continuous spot split exists.
- Still to verify: Bitget snapshot rule; hackathon developer guide tool requirements (login-gated);
  whether `fee-group` `weight` is a multiplier.

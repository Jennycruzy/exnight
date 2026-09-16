# Verification log

Every product rule and market parameter used in this repo, with how it was verified.
Labels: **DOCUMENTED** (first-party Bitget page), **OBSERVED** (we ran it, date given),
**ASSUMED** (not yet verified; any result depending on it carries the label).

Where the working spec and Bitget disagree, Bitget wins and the difference is noted here.

## Symbols and fees — OBSERVED 2026-09-16

Sources: `GET /api/v3/market/instruments?category=SPOT` (DOCUMENTED at bitget.com/api-doc/uta;
carries `symbolType`, `isReality`, `launchTime`, precisions, min order amount) and
`GET /api/v2/spot/public/symbols` (carries `makerFeeRate`/`takerFeeRate`, which v3 does not).
Both unauthenticated; the client joins them at runtime.

| Fact | Observation |
|---|---|
| rToken identifier (documented) | `symbolType = "stock"` and `isReality = "yes"` on v3 instruments; 1,653 symbols. Identical to the set with `baseCoin` matching `^r[A-Z]`; the client raises if the two sets ever differ |

| rToken identifier (observed) | `baseCoin` is `r` + upper-case ticker: `rAAPL`, `rMU`, `rQQQ`, `rTSM` |
| Spot symbol format | `upper(baseCoin) + quoteCoin`, e.g. `RMUUSDT`. Holds for every rToken in the list |
| Quote currency | USDT only |
| Universe size | **1,653** rTokens online (the spec said "600+"; the live list is larger) |
| Fee fields | `makerFeeRate = takerFeeRate = 0.001` on every rToken symbol. BTCUSDT shows 0.002 on the same endpoint, so the field is symbol-specific and not a placeholder |
| Price precision | 2 decimals on the tokens checked (tick = 0.01 USDT); read per symbol at runtime |
| Min order | `minTradeUSDT = 10` |
| Listing times | `openTime` clusters at 2026-06-10 and 2026-09-11 (batches), one on 2026-08-11 |

Open question 5 (is rToken spot commission-free?) — the public symbol endpoint reports
**0.1% maker and taker**. That is the rate the cost model uses. Whether an account-level
promotion overrides it is **ASSUMED unknown**; it can only be checked from an authenticated
fee-tier call and will be re-verified there.

## Candles — OBSERVED 2026-09-16

`GET /api/v3/market/candles?category=SPOT&symbol=RMUUSDT&interval=...`

| Fact | Observation |
|---|---|
| Max `limit` | 1000. `limit=1001` → code `40020 Parameter limit error` |
| Intervals | Docs list `1m 3m 5m 15m 30m 1H 4H 6H 12H 1D`; the live API rejects `3m` with `48001 Parameter validation failed`. Doc/live disagreement; the client uses only intervals that were observed to work |
| `/api/v3/market/history-candles` | DOCUMENTED for data older than 90 days. OBSERVED: same row shape; `limit` capped at **100** (101 → 40020); `endTime` is interpreted as "bars closing at or before endTime", whereas `/candles` includes the bar stamped at `endTime`. The client pages one interval past each boundary and dedupes; verified to reproduce the cached `/candles` bars exactly (RSQQQUSDT 2026-06-22, 1,406 of 1,406) |
| Rate limit | documented 20 req/s/IP; the client caps itself at 10 |
| **Candle volume is not rToken trading** | 1D base volume on RQQQUSDT 2026-07-06 = 36.4M vs QQQ consolidated 30.2M shares (Yahoo); RKOUSDT 20.2M vs 19.0M; RSCHDUSDT 20.9M vs 24.0M. The `volume`/`quote_volume` fields track the US consolidated tape (with Bitget's 16:00 UTC day boundary), not on-platform fills. **No inference about rToken liquidity may be drawn from candle volume.** |
| Row shape | `[ts_ms, open, high, low, close, base_volume, quote_volume]` |
| 1m depth | `endTime=2026-07-25` returned 1000 bars back to 2026-07-24 07:21 UTC; pagination by `endTime` reaches earlier pages. 1m history exists for the 24 July batch |
| 1D bars | Timestamped at **16:00 UTC** (00:00 UTC+8). Daily "open/close" therefore refer to Hong Kong midnight, not any US session boundary. Event-study measurement points must be taken from intraday bars, not 1D |
| 1D depth for RMUUSDT | first bar 2026-06-18, although the symbol's `openTime` is 2026-06-10. Not yet explained |

`GET /api/v2/spot/market/history-candles?symbol=RMUUSDT&granularity=1min`

- Without `endTime` → code `400172 Parameter verification failed`. `endTime` is required.
- With `endTime=2026-06-15` it returned 200 bars spanning 2026-06-12 21:03 → 2026-06-14 13:00
  UTC, i.e. bars with no trades are **omitted**, not zero-filled. Gap handling is therefore
  the caller's job and is treated as a data-integrity check, not filled.

## Dividend notice of 2026-07-24 — DOCUMENTED

Source: https://www.bitget.com/support/articles/12560603890079, saved verbatim under
`data/sources/` and checksummed in `exnight/sources.py`.

- 63 rows, **59 distinct rTokens**; rSATA appears five times (daily-paying ETF).
- Ex-dates run from **2026-06-11 to 2026-07-21**. The working spec described the batch as
  "63 events at a single moment"; it is not. It is one *payment* batch covering six weeks
  of ex-dates. The sample is still cross-sectional in the sense that all events sit on the
  same infrastructure and fee schedule, but they are not simultaneous.
- Withholding: "the securities custodian will deduct a 30% federal withholding tax ...
  Actual Received Amount = Number of Shares Held × Dividend per Share × 70%".
- Eligibility: "Users holding the corresponding assets at the time of the snapshot". **The
  snapshot time is not stated.** `bitget_snapshot_time` is null for every event and
  `eligibility_verified` is false; every BUY signal is suppressed until this is resolved.
- Exchange record dates are not stated and are left null rather than inferred.

## Trading hours, fees at the time — DOCUMENTED

- Support article 12560603887176: "Bitget stock spot trading currently supports extended
  trading across a 24/5 schedule." Weekend trading exists only for a listed subset:
  61 tokens as of 2026-07-17 (article 12560603889487), "over 100" per the later Academy FAQ.
  The spec's "all 24/7" is wrong; the overnight ex-date repricing this project measures
  happens in the weekday overnight session for all tokens, and additionally over weekends
  for the listed subset. Weekend prices are "reference quotes ... based on Friday's closing
  price, combined with market maker quotations".
- Academy FAQ: "During the current promotional period through August 31, 2026, the standard
  trading fee is 0.05%". Every event in the July notice falls inside that period, so the
  cost model uses **0.05%** for those events and the live symbol rate (0.1% today) for
  anything after 2026-08-31. Fee is therefore a per-event field, not a constant.
- PTP notice 2026-09-15 (article 12560603895180): PTP-related rTokens carry 37%/21%
  withholding and a potential 10% sale tax; all currently listed PTP rTokens are exempt
  today. No ticker in the July notice is on the PTP list, but the withholding rate must
  stay per event.

## Split adjustment and history provenance — OBSERVED 2026-09-16

Three underlying splits fell inside the sample window: CrowdStrike 4:1 (first adjusted trading
2026-07-02), Amphenol 2:1 (executed 2026-09-03) and Direxion SOXS 1:10 reverse (2026-07-15,
per Yahoo Finance split events). All three underlyings have rTokens.

| Observation | Implication |
|---|---|
| A scan of 1D candles for all 1,653 rTokens (2026-06-01 → 09-16) found **no** open/prev-close ratio outside [0.6, 1.6] | no raw split gaps exist in the daily series |
| RCRWDUSDT 1D closes run 171 → 196 → 195 across 2026-07-02 with 5-decimal prices such as 175.48125 (= 701.925 ÷ 4) | pre-split history is **back-adjusted** by the split ratio |
| RAPHUSDT 1D closes run 79.9 → 81.0 → 82.5 across 2026-09-03; but the 2026-09-02 bar has high = 146.784 vs close 80.997 | back-adjusted, with a **stale un-adjusted print surviving in `high`**. Extremes cannot be trusted across an adjustment |
| RAPHUSDT `launchTime` = 2026-09-03 10:51 UTC (split day), although rAPH paid a dividend in June; RSOXSUSDT `launchTime` = 2026-07-15, the day of its 1:10 reverse split; RTZAUSDT also 2026-07-15 | Bitget **re-lists** a token around a corporate action; the symbol's `launchTime` moves and intraday history before it is gone. Bitget's dividend table shows rSOXS at 0.0375 where Yahoo's split-adjusted figure is 0.38 — consistent with the same 1:10 |
| 1D bars start 2026-06-21 for tokens listed in July and September (rCRWD, rAPH, rSOXS) | **daily history is a backfilled reference series**, not a record of rToken trading. It must not be used to measure the Bitget market |
| 1m bars exist only from `openTime` onward | an event is reconstructable only if its window lies after the symbol's `openTime` |

Consequences for the code:
1. The normaliser does **not** divide by split ratios; Bitget already has. It verifies
   continuity across known corporate actions and flags stale extremes.
2. Measurement uses intraday bars after `openTime` only.
3. Open question 2 is answered for the backfilled series. Whether a split that occurs while
   a token stays listed (no re-list) is back-adjusted in place remains **ASSUMED**; no such
   case exists in the sample.

## Corporate-action endpoints — OBSERVED 2026-09-16 (spec v2 ambiguities A and B)

| Endpoint | Observation |
|---|---|
| `GET /api/v3/market/cash-dividend-records?symbol=RMUUSDT&type=paid` | `40034 Parameter RMUUSDT does not exist`. With the **perps** symbol `MUUSDT` it returns `{exDividendDate: 2026-07-06, cashDividendPerShare: 0.15, cashDividendTimestamp: 1783036800000}`. **The endpoint serves RWA stock perps only, as its documentation says; it does not cover spot rTokens.** Ambiguity A: C1 for spot stays on Bitget's published distribution notice (DOCUMENTED, parsed deterministically). The perps endpoint is used as a cross-check and, with `type=pending`, as a forward calendar for underlyings that have a perp |
| `cashDividendPerShare` gross or net? | For the 4 sample events that have a perps record (rAVGO 0.65, rMU 0.15, rCSCO 0.42, rCMCSA 0.33) it equals the spot notice's figure to the cent, and the spot notice applies ×70% *on top of* that figure. MU's declared dividend is $0.15. **Ambiguity B: gross.** Only 25 of 59 sample underlyings have a perp and only 4 of those have a June/July record, so the cross-check covers 4 events |
| `cashDividendTimestamp` | 1783036800000 = 2026-07-03 00:00 UTC = Thu 2026-07-02 20:00 ET for a Mon 2026-07-06 ex-date with Fri 07-03 an NYSE holiday: the perps settlement time, holiday-aware, at the US after-hours close. Consistent with article 12560603895292 |
| `GET /api/v3/market/split-records` | 4 records, all `status=completed`: KORUUSDT 20 (ex 2026-07-15), MUUUSDT 20 (07-15), SOXSUSDT 0.1 (07-15), MSTUUSDT 0.1 (08-24); `exDividendDateTimezone=ET`; halt windows of 7–13 h ending 13:35 UTC (09:35 ET). **All four symbols are `USDT-FUTURES` instruments; none is a spot symbol, and Amphenol's 2:1 (spot rAPH, 2026-09-03) is absent.** The spot rToken for each is (re-)listed *after* the halt ends: RSOXSUSDT `launchTime` 14:37 UTC vs halt end 13:35; RMSTUUSDT 2026-08-25 02:42 vs halt end 08-24 13:35 |
| Spot series across a split | There is none. The pre-split spot token's intraday history ends; the new listing starts after the halt. The spec's "halt then gap in one series" describes the perps; for spot it is "old token gone, new token listed". The normaliser therefore (a) drops bars before `launchTime`, (b) is halt-aware for any series that does span a `split-records` window, (c) still asserts no split-shaped gap in what remains |
| `GET /api/v3/market/tickers?category=SPOT` | Carries `platformTurnover24h` (on-platform rToken turnover) beside `turnover24h` (US tape). RMUUSDT: **$290,798** platform vs $11.0B tape. For the 59 sample symbols on 2026-09-16: median platform turnover **$119**, 28 of 63 events' tokens at **$0**, 51 below $10k; the largest are rAVGO $393k, rMU $291k, rQQQ $228k, rTLT $109k. This is the liquidity of the market that produced the measured prices |
| `GET /api/v3/market/fee-group?category=SPOT` | Three groups with MM1–MM5 and PRO1–PRO6 tiers; an `rtoken` label (1,668 symbols, weight 1.00) sits in GROUP_A with `core_mainstream`. The response carries no ordinary-user base tier; the 0.10% base still comes from v2 symbols. What `weight` means is not documented — **ASSUMED** to be a multiplier and not used |

## US market calendar — DOCUMENTED (NYSE), not a Bitget parameter

The last cum-dividend session is the last NYSE trading day before the ex-date. NYSE 2026
full-day closures are hardcoded in `eventstudy.py` from the NYSE holiday calendar; the two
inside the sample are Fri 2026-06-19 (Juneteenth) and Fri 2026-07-03 (Independence Day
observed). Bitget rTokens printed bars on both days (OBSERVED), which is why the calendar
cannot be inferred from the candle data.

## Still ASSUMED (blocks the paths listed)

| # | Question | Blocks |
|---|---|---|
| 1 | Bitget dividend snapshot time vs exchange ex/record date (neither endpoint returns one) | every BUY signal |
| 2 | In-place adjustment of a split without a re-list | any future series that spans such a split |
| 3 | Withholding is exactly 30% on every event in the batch | net-dividend arithmetic |
| 4 | Account-level fee tier vs the published 0.05% (to 31 Aug) / 0.1% (after) | cost model |
| 5 | Overnight book depth at realistic size | slippage model |

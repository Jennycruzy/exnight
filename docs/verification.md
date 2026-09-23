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
| rToken filter | `symbolType = "stock"` and `isReality = "yes"` on v3 instruments; 1,653 symbols. The current response omits `isRwa` for these rows, so it is recorded when present but is not a filter |
| API identifiers | `baseCoin` and `symbol` are retained exactly as returned by `instruments`; no name pattern is used to build the universe |
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

## Corporate-action endpoints — OBSERVED 2026-09-16

The working specification named two different public APIs. The live product has a third, newer Reality endpoint that is the correct source for spot actions.

| Endpoint | Observation |
|---|---|
| GET /api/v3/reality/market/stock-info?symbol=RMUUSDT | HTTP 200. The response data is a one-element list containing the Reality code, trading sessions and weekend flag. |
| GET /api/v3/reality/market/dividends?code=MU | HTTP 200. The response data is an object with list and cursor. Rows include cash_dividend, stock_dividend and stock_split records with announcement, record, ex-right, payment and split fields. This is the observed spot corporate-action source. |
| GET /api/v3/market/cash-dividend-records?symbol=RMUUSDT&type=paid | HTTP 40034, symbol does not exist. The same request with the futures symbol MUUSDT returns a record. The endpoint remains futures-only, as its documentation says; it is a cross-check, not the spot calendar. |
| GET /api/v3/market/split-records | Four completed records were returned and all were USDT-FUTURES symbols. No corresponding spot split record was returned. The records include adjustmentRatio, an ET date and halt timestamps. |
| cashDividendPerShare basis | Four futures records match the saved spot notice amounts exactly: rAVGO 0.65, rMU 0.15, rCSCO 0.42 and rCMCSA 0.33. The notice applies the documented 70% credit factor separately. This is gross evidence for those four observations only. |

The Reality dividend endpoint does not state an ET timezone for its timestamp fields. Its date conversion is therefore labelled ASSUMED until Bitget confirms the convention. The spot builder must retain the raw timestamp, the response time and the conversion label.

The saved July notice remains useful as a first-party cross-check and as the only source that states the snapshot wording and the 30% deduction for that distribution. It should not remain the only spot event source now that Reality market data is public.

### Splits and listing continuity

The four live split-records rows are futures rows. The spot observations for rAPH, rSOXS and rTZA show a listing boundary around the corporate action, not a continuous spot series through the halt. The halt-and-ratio normaliser is therefore applicable when a series actually spans a split record, but its completed-spot path is not verified by the current sample. A spot re-list boundary must be represented as a symbol-history discontinuity and must not be treated as a zero-return split transition.

### Turnover and executable liquidity

The tickers response labels platformTurnover24h as rToken-only platform turnover and also carries turnover24h for the reference tape. Platform turnover is not order-book depth and cannot establish whether StockRoute liquidity is present. The existing depth observation must be split by session before it is used for a framing decision.

## US market calendar — OBSERVED from Bitget and the exchange

The last cum-dividend session is the last US trading session before the ex-date. Bitget's
Reality calendar endpoint returns a timezone label and explicit holiday windows; the
market-state endpoint returns pre-market, regular, after-hours and overnight boundaries.
The event-study path consumes that live calendar and retains the source label. Bitget rTokens
printed bars on the two known 2026 exchange holidays inside the sample, so candle presence is
not a holiday source.

## Still ASSUMED (blocks the paths listed)

| # | Question | Blocks |
|---|---|---|
| 1 | Bitget dividend snapshot time vs exchange ex/record date (neither endpoint returns one) | every BUY signal |
| 2 | In-place adjustment of a split without a re-list | any future series that spans such a split |
| 3 | Withholding is exactly 30% on every event in the batch | net-dividend arithmetic |
| 4 | Account-level fee tier vs the published 0.05% (to 31 Aug) / 0.1% (after) | cost model |
| 5 | Overnight book depth at realistic size | slippage model |

## Authenticated Reality order surface — OBSERVED 2026-09-19

The official Bitget Agent Hub CLI (`bgc`) is installed for the ubuntu user and is now the
active order adapter. It signs requests locally and routes EXNIGHT's guarded order flow through
the standard UTA surface:

| Fact | Observation |
|---|---|
| Reality placement endpoint | Agent Hub `bgc order --action place` → `POST /api/v3/trade/place-order` with `category=SPOT`, symbol, side, limit price, quantity and time-in-force. Bitget's 11 August announcement says Reality order placement/cancellation is fully open without whitelist registration. |
| Order lifecycle | Agent Hub `order --action detail` → `GET /api/v3/trade/order-info`; `order --action cancel` → `POST /api/v3/trade/cancel-order`. |
| Whitelist boundary | Reality order-book/depth and platform-fills endpoints remain whitelist-gated. By default the live path requires a fresh two-sided public book. `--allow-ticker-only` is an explicit opt-in that sizes against the ticker's best quote instead; it was added on 23 September to test whether routed liquidity fills. |
| Demo (`--live-paper`) | Refused explicitly. Bitget's generic demo environment rejects Reality symbols, so EXNIGHT does not pretend that a demo response proves a live rToken path. |
| Configured private key | Until 20 September the configured key was demo-only (`40099 exchange environment is incorrect` on mainnet). On 23 September a mainnet key was configured. `GET /api/v3/account/info` reports it as `read_and_write` with `uta_trade` only; it cannot read balances (`40014`, needs UTA management). A second read-only key with `uta_mgt` (`BITGET_READ_*`) is used for the balance preflight. Neither key has withdrawal permission. |
| Dry-run | A public-data dry run for `RAVGOUSDT` at requested $20 recorded a precision-valid payload without credentials or order submission. A $5 attempt was correctly refused below the $10 exchange minimum. |
| Live safeguards | Live mode requires a two-sided public book (unless `--allow-ticker-only`), final quote recheck, available-balance preflight, the $100 one-order cap and the exact `--live --confirm-live '<SYMBOL> <SIDE> <QUANTITY>'` string. |

**One live order has been submitted (23 September 2026).** The operator ran the command in their
own terminal: buy 0.2783 RTOWNUSDT, IOC limit 36.29, with `--allow-ticker-only`. It **filled in
full at 36.28** (value 10.097837 USDT, fee 0.01009783 USDT) against a 36.28/36.29 ticker quote,
with an empty public book. See [the live-fill note](live_fill_20260923.md). No Reality whitelist
was needed for placement. Reality depth and fills data remain whitelist-gated.

## Errata for frozen documents — 2026-09-23

`docs/m2.md` is a hashed input of the frozen competition manifest, so it is not edited.
Every figure in its section 2 regenerates with `exnight.doc_figures`, and a test checks them.
The cluster bootstrap reproduces the printed intervals with seed 0 and 2,000 draws. One label
is wrong:

- The window table's first row is labelled **"1 Jun – 6 Jul"**, but its figures (n = 51) were
  computed on ex-dates **through 1 July**. The two 6 July events, rCSCO and rMU, are not in
  it. Including them gives n = 53 and a 04:00 ET slope of 1.18 ± 0.42, which does not change
  the section's conclusion.

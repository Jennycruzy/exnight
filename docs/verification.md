# Verification log

Every product rule and market parameter used in this repo, with how it was verified.
Labels: **DOCUMENTED** (first-party Bitget page), **OBSERVED** (we ran it, date given),
**ASSUMED** (not yet verified; any result depending on it carries the label).

Where the working spec and Bitget disagree, Bitget wins and the difference is noted here.

## Symbols and fees — OBSERVED 2026-09-16

Source: `GET https://api.bitget.com/api/v2/spot/public/symbols`, unauthenticated.

| Fact | Observation |
|---|---|
| rToken identifier | `baseCoin` is `r` + upper-case ticker: `rAAPL`, `rMU`, `rQQQ`, `rTSM` |
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
| Intervals | `1m 5m 15m 1H 4H 1D`. `3m` → code `48001 Parameter validation failed` |
| Row shape | `[ts_ms, open, high, low, close, base_volume, quote_volume]` |
| 1m depth | `endTime=2026-07-25` returned 1000 bars back to 2026-07-24 07:21 UTC; pagination by `endTime` reaches earlier pages. 1m history exists for the 24 July batch |
| 1D bars | Timestamped at **16:00 UTC** (00:00 UTC+8). Daily "open/close" therefore refer to Hong Kong midnight, not any US session boundary. Event-study measurement points must be taken from intraday bars, not 1D |
| 1D depth for RMUUSDT | first bar 2026-06-18, although the symbol's `openTime` is 2026-06-10. Not yet explained |

`GET /api/v2/spot/market/history-candles?symbol=RMUUSDT&granularity=1min`

- Without `endTime` → code `400172 Parameter verification failed`. `endTime` is required.
- With `endTime=2026-06-15` it returned 200 bars spanning 2026-06-12 21:03 → 2026-06-14 13:00
  UTC, i.e. bars with no trades are **omitted**, not zero-filled. Gap handling is therefore
  the caller's job and is treated as a data-integrity check, not filled.

## Still ASSUMED (blocks the paths listed)

| # | Question | Blocks |
|---|---|---|
| 1 | Bitget dividend snapshot time vs exchange ex/record date | every BUY signal |
| 2 | Are historical candles split-adjusted? | every series that spans a split |
| 3 | Withholding is exactly 30% on every event in the batch | net-dividend arithmetic |
| 4 | Account-level fee tier vs the 0.1% symbol rate | cost model |
| 5 | Overnight book depth at realistic size | slippage model |

# Exnight run records

In the handbook's order of priority: live, then backtest. Every figure below is read from
files committed in this repository; `python scripts/run_backtest.py` regenerates this page.

## 1. Live order on Bitget

A real order placed through Bitget Agent Hub to check that an rToken with an empty public
order book fills at its quote. Saved request and response files: [`data/raw/paper/20260923T182547.240457Z/`](../data/raw/paper/20260923T182547.240457Z/);
write-up: [`docs/live_fill_20260923.md`](../docs/live_fill_20260923.md).

| Timestamp (UTC) | Instrument | Direction | Price | Quantity | Fee | Balance change |
|---|---|---|---:|---:|---:|---|
| 2026-09-23T18:25:49.760Z | RTOWNUSDT | buy | 36.28 (limit 36.29, limit ioc) | 0.2783 | 0.01009783 USDT | USDT 13 → 2.89206496; rTOWN 0 → 0.2783 |

Order `1486721505797718016`, status `filled`, value 10.097837 USDT; balances read 2026-09-23T18:26:49Z with a read-only key.

**Since the order.** Exnight's frozen call for rTOWN's ex-date was NO_SIGNAL: no step-out, so
the position was held through it. Read-only snapshot 2026-10-07T02:07:11.646Z ([`data/raw/paper/20261007T020711Z_rTOWN_position/`](../data/raw/paper/20261007T020711Z_rTOWN_position/)):

| | |
|---|---|
| Holding | 0.2783 rTOWN, held through the 2026-09-25 ex-date |
| Paid, with fee | 10.1079 USDT |
| Worth now | 9.8530 USDT (last 35.41; quote 35.04 / 35.98) |
| Change since the buy, fee included | -0.2549 USDT, before the dividend |
| Dividend due | 0.28 per share: 0.0779 USDT gross, 0.0545 if 30% is withheld |
| Dividend credited? | not yet: Bitget lists payment at 2026-10-08T16:00:00Z; the ledger has 2 rows, the buy only |

The credit will show what withholding Bitget actually applies to an rToken holder, which the backtest has to assume. `scripts/check_dividend_credit.py` checks for it read-only every 15 minutes after the payment time and records it here when it lands.

## 2. Live forward test

16 high-dividend ex-dates from 25 September to 8 October, chosen and scheduled before the first
one. Each decision is committed to Git (and, from 5 October, anchored on Arbitrum One) before
the 20:00 ET sell cutoff, the price is recorded every minute, and a scorer grades it after the
ex-date. 15 graded so far. Prices are the last trade at the cutoff and at 04:00 ET;
"Hold minus step out" is per event, modeled costs, 70% of the dividend kept.

| Token | Ex-date | Decision committed | Decision ($1k) | Price, cutoff → 04:00 ET | Drop / dividend | Overnight trading | Hold minus step out, bps |
|---|---|---|---|---|---:|---|---:|
| rTOWN | 2026-09-25 | 20260924T2330Z | NO_SIGNAL | 36.4 → 36.4 | 0.00 | NONE | +98.8 |
| rBZ | 2026-09-28 | 20260925T2330Z | NO_SIGNAL | 14.09 → 13.54 | 1.08 | PRICED | -92.0 |
| rINDB | 2026-09-28 | 20260925T2330Z | NO_SIGNAL | 81.2 → 81.2 | 0.00 | NONE | +100.2 |
| rKDP | 2026-09-28 | 20260925T2330Z | HOLD | 31.97 → 31.82 | 0.65 | PRICED | +48.4 |
| rERIC | 2026-09-29 | 20260928T2330Z | NO_SIGNAL | 9.42 → 9.41 | 0.06 | THIN | +151.7 |
| rAGNC | 2026-09-30 | 20260929T2330Z | NO_SIGNAL | 9.45 → 9.37 | 0.67 | PRICED | +49.2 |
| rCVBF | 2026-09-30 | 20260929T2330Z | NO_SIGNAL | 21.94 → 21.94 | 0.00 | NONE | +108.8 |
| rDOX | 2026-09-30 | 20260929T2330Z | NO_SIGNAL | 57.59 → 57.6 | -0.02 | THIN | +115.9 |
| rHST | 2026-09-30 | 20260929T2330Z | NO_SIGNAL | 22.44 → 22.41 | 0.15 | THIN | +94.0 |
| rJOYY | 2026-09-30 | 20260929T2330Z | HOLD | 80.6 → 80.6 | 0.00 | NONE | +179.6 |
| rMDLZ | 2026-09-30 | 20260929T2330Z | HOLD | 59.41 → 58.86 | 1.06 | PRICED | +13.7 |
| rCPB | 2026-10-01 | 20260930T2330Z | NO_SIGNAL | 19.85 → 19.54 | 1.24 | PRICED | -23.0 |
| rFULT | 2026-10-01 | 20260930T2330Z | NO_SIGNAL | 22.57 → 22.42 | 0.79 | THIN | +37.5 |
| rVSNT | 2026-10-01 | 20260930T2330Z | NO_SIGNAL | 31.9 → 31.9 | 0.00 | NONE | +127.3 |
| rCMCSA | 2026-10-07 | 20261006T2330Z | NO_SIGNAL | 21.58 → 21.32 | 0.79 | PRICED | +31.6 |

Holding beat stepping out on 13 of 15 graded events; on the 6 nights where the price actually moved, 4 of 6. Score files: `data/results/forward_score_v3_*.json`; recordings:
`data/raw/recorder/v3_*/`.

## 3. Backtest

2026-06-24 to 2026-09-16: 85 days in total, 47 days out-of-sample, walk-forward.
Exnight minus always selling first, out-of-sample: Sharpe 11.96, Sortino 6.95, max drawdown -0.055%. Full record and limits: [`backtest.md`](backtest.md); code:
[`exnight/backtest_report.py`](../exnight/backtest_report.py), [`exnight/competition.py`](../exnight/competition.py),
[`scripts/run_backtest.py`](../scripts/run_backtest.py).

# Alpha Factory scorecard

This is the **walk-forward OOS performance of the Exnight selection procedure**. It is not V1 OOS. Strategy V1 was fitted on all 127 discovery events and has no historical OOS window.

Every historical execution figure below is **MODELED_EXECUTION**. The HOLD benchmark accrues dividend entitlement at T1; it does not assume cash was paid by T1.

## Sample

- Discovery: 185 corporate actions → 58 usable unresolved → 127 usable resolved.
- Ex-ante filter: **56 of 127** resolved/usable events retain pre-decision declaration evidence; 71 are excluded from the scorecard.
- OOS: **39 events across 47 calendar days; 0 EXIT trades.**
- The excluded 71 comprise 58 events whose current gross-basis proof is the later Bitget payment notice and 13 supported only by realised records.

## Fold diagnostics

| Fold | Training end | Test period | Rung | PDR ± SE | Training events | Test events | EXIT trades | Test Sharpe |
|---|---:|---|---|---:|---:|---:|---:|---:|
| OOS_2026_08 | 2026-07-31 | 2026-08-01..2026-08-31 | `premarket_0400` | 1.034 ± 0.871 | 17 | 25 | 0 | -4.35 |
| OOS_2026_09 | 2026-08-31 | 2026-09-01..2026-09-16 | `open_0930` | 0.919 ± 0.353 | 42 | 14 | 0 | 2.38 |

## Main scorecard

Primary reporting uses 0% withholding, the most holder-favourable and therefore hardest case for EXIT, plus 25 bps round-trip modeled slippage.

| Window / series | Total | Annualised | Sharpe / IR | Sortino | Max drawdown |
|---|---:|---:|---:|---:|---:|
| IS initial — policy | -0.004% | -0.034% | -0.11 | -0.07 | -0.109% |
| IS initial — benchmark | -0.004% | -0.034% | -0.11 | -0.07 | -0.109% |
| IS initial — active | 0.000% | 0.000% | — | — | 0.000% |
| OOS — policy | -0.096% | -0.739% | -2.57 | -1.59 | -0.169% |
| OOS — benchmark | -0.096% | -0.739% | -2.57 | -1.59 | -0.169% |
| OOS — active | 0.000% | 0.000% | — | — | 0.000% |

The arithmetic OOS/IS Sharpe quotient is 22.80, but it is **not economically meaningful** because IS Sharpe is negative (-0.11) and rests on 0 EXIT trades. It is not treated as evidence against the 0.5 decay flag.

The robust rule issued no EXIT trades. Policy therefore equals HOLD, active return is zero, turnover and modeled fee/slippage drag are zero, and every rolling 30-day Sharpe window is `INSUFFICIENT_EVENTS`.

## Cost and entitlement sensitivity

| Round trip slippage | Withholding | EXIT trades | Policy return | Policy Sharpe | Active return |
|---:|---:|---:|---:|---:|---:|
| 10 bps | 0% | 0 | -0.096% | -2.57 | 0.000% |
| 10 bps | 15% | 0 | -0.122% | -3.28 | 0.000% |
| 10 bps | 25% | 0 | -0.140% | -3.74 | 0.000% |
| 10 bps | 30% | 0 | -0.149% | -3.97 | 0.000% |
| 25 bps | 0% | 0 | -0.096% | -2.57 | 0.000% |
| 25 bps | 15% | 0 | -0.122% | -3.28 | 0.000% |
| 25 bps | 25% | 0 | -0.140% | -3.74 | 0.000% |
| 25 bps | 30% | 0 | -0.149% | -3.97 | 0.000% |
| 50 bps | 0% | 0 | -0.096% | -2.57 | 0.000% |
| 50 bps | 15% | 0 | -0.122% | -3.28 | 0.000% |
| 50 bps | 25% | 0 | -0.140% | -3.74 | 0.000% |
| 50 bps | 30% | 0 | -0.149% | -3.97 | 0.000% |
| 100 bps | 0% | 0 | -0.096% | -2.57 | 0.000% |
| 100 bps | 15% | 0 | -0.122% | -3.28 | 0.000% |
| 100 bps | 25% | 0 | -0.140% | -3.74 | 0.000% |
| 100 bps | 30% | 0 | -0.149% | -3.97 | 0.000% |

No point in the full grid produces an EXIT trade. The result therefore does not establish active alpha at the frozen confidence threshold.

## Forward evidence

- 21 September remains `INCOMPLETE` because of the disclosed 57-minute recording gap.
- 22 September recorder integrity passed: 1,348 rows per symbol, maximum gap 63 seconds, and timely T0/T1 samples. The combined strategy score is `INCOMPLETE` because rAPH and rSTM lacked resolved gross/net basis. rSATA produced frozen `HOLD` and realised PDR 0.0.
- Capacity: No recorded pair had a nonempty public book; $1k/$5k/$25k capacity is unproven.

The forward recorder result is evidence about frozen V1. It is separate from the walk-forward scorecard above.

## Reproduce

```bash
.venv/bin/python scripts/build_competition_submission.py
```

Frozen manifest SHA-256: `7ebb01057edc55b63f8023ae32c21f960950bfec46db9c06e1d603ead0cb9437`.

# Exnight — submission copy

Paste-ready text for the submission form. Every figure matches the committed results and is
checked by `tests/test_baseline.py` and `tests/test_competition_report.py`.

**Project:** Exnight
**Track:** Alpha Factory → rToken Factor Strategies. Secondary fit: Open Theme, execution-aware alpha.
**Repository:** https://github.com/Jennycruzy/exnight
**Dashboard (evidence snapshot):** https://jennycruzy.github.io/exnight/

## One line

Exnight tells a Bitget rToken holder whether stepping out before an ex-dividend date is worth it,
and it stands down when the edge does not clear costs.

## Thesis

Across 127 usable corporate actions, Bitget Reality-token prices fall by about the gross dividend
by 04:00 ET on the ex-date. The holder may keep less than the gross dividend, and how much less
varies by event. Stepping out before the ex-date is worth it only when the expected fall beats
what the holder keeps, plus fees and slippage. Exnight measures that edge for each event, using
only information available before the decision.

## Target user and product value

A Bitget Reality-token holder with $1,000–$25,000 positions in dividend-paying rTokens, deciding
around each ex-date whether to stay exposed. Exnight gives an `EXIT`, `HOLD` or `NO_SIGNAL`
decision per event and trade size, with the evidence behind it. The dashboard's Decisions page
looks up any evaluated token. BUY is suppressed because Bitget does not publish its
dividend-eligibility snapshot time.

## Validation

- **Discovery study.** 185 corporate actions → 127 usable events. The price fall is consistent
  with the gross dividend by 04:00 ET: slope 0.97 ± 0.18. This found the effect; it is not
  out-of-sample evidence.
- **Walk-forward test.** The selection procedure was refit on past data only and frozen, with
  a hashed manifest, before scoring. 56 of 127 events had dividend evidence published before the
  decision. Out-of-sample covers 39 events over 47 days.
  - Exnight issued **0 EXIT trades**. Its return equals holding: −0.096%, Sharpe −2.57, active
    return 0.000%.
  - Stepping out of every event instead would have lost **−32.5 bps per event** against holding
    and beaten it on only 13% of events. It loses at every tested cost from 10 to 100 bps and every
    withholding rate from 0% to 30%.
- **Forward evidence.** The rule was frozen on 17 September and recorded live on 21 and 22 September.
  A withholding-aware V3 was registered before any V3 result was computed. It is recording 16
  high-yield events from 25 September to 8 October.

Historical costs are modeled, and labelled `MODELED_EXECUTION` everywhere. Forward capacity is
reported separately: the recorded Reality pairs had empty public order books, so fills at
$1k/$5k/$25k are unproven; one $10 order filled in full at the quote.

## Progress and deliverables

- Source ledger, knowledge-time table and 127-event discovery study
- Runnable walk-forward strategy code with a frozen, hashed manifest, and tests that prevent lookahead and fold leakage
- Scorecard with policy, HOLD benchmark and active series, the full cost and withholding grid, and an always-EXIT comparison
- Minute recorder, health checks and offline forward scorers for V1 and V3
- Read-only dashboard with token lookup; guarded order preparation capped at $100 that needs explicit confirmation
- One command regenerates every competition artifact: `.venv/bin/python scripts/build_competition_submission.py`

## Limits

- The out-of-sample test has no EXIT trades, so there is no active-alpha claim.
- The ex-ante sample is small (56 events) and concentrated in rSATA.
- Historical order books do not exist, so historical costs are modeled.
- One real fill so far: $10 of rTOWN on 23 September, filled in full on a token with no public order
  book, at the quote, with a 10 bps fee. Larger sizes and the sell leg are untested.
- Bitget's dividend-eligibility snapshot time is unpublished.

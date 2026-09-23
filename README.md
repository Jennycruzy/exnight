# Exnight

**Exnight tells a Bitget rToken holder whether stepping out before an ex-dividend date is worth
it.** By 04:00 ET on the ex-date, the token has usually fallen by about the whole dividend, so
selling first and buying back afterwards looks attractive. Exnight tested that against holding,
with only information available before each decision:

| Out-of-sample, 39 events over 47 days | Exnight | Always step out | Hold |
|---|---:|---:|---:|
| Trades | 0 | 39 | 0 |
| Result against holding, per event | 0 bps | **−32.5 bps** | — |
| Events where stepping out beat holding | — | 13% | — |
| Total return | −0.096% | −0.600% | −0.096% |
| Sharpe | −2.57 | −22.93 | −2.57 |

Stepping out of every event would have lost 32.5 bps per event after fees and modeled
slippage. It loses at every tested cost from 10 to 100 bps and every withholding rate from 0% to 30%.
Exnight's rule stood down every time, so it lost nothing relative to holding. The holding
return itself is negative because of market moves on those nights, not anything Exnight did.
The dividend repricing effect is real; after costs it is not yet tradable, and Exnight says so
instead of trading it.

## Thesis

Across 127 dividend events, a Bitget Reality token's price has fallen by about the full
(gross) dividend by 04:00 ET on the ex-date. But a holder may keep less than the full
dividend after tax withholding, and how much less varies by event. Stepping out before the
ex-date only pays when the expected fall is bigger than what the holder would have kept, plus
fees and slippage. Exnight measures that for each event.

## Target user and product value

**Track:** Alpha Factory → rToken Factor Strategies. Secondary fit: Open Theme,
execution-aware alpha.

**Target user:** a Bitget Reality-token holder with **$1,000–$25,000** in dividend-paying
rTokens, deciding **before each ex-date** whether to stay in or step out for the night.

For each event and trade size, Exnight gives `EXIT`, `HOLD` or `NO_SIGNAL`, with the reason
and the evidence behind it. The dashboard's Upcoming page lists high-yield ex-dates with the
decision frozen before each sell cutoff, then the real outcome once the event is scored.
Its Decisions page looks up any evaluated token (`rAPH`, `RAPHUSDT` or `APH`). Exnight never
says BUY, because Bitget has not published when it takes the dividend-eligibility snapshot.

**Live dashboard:** [jennycruzy.github.io/exnight](https://jennycruzy.github.io/exnight/)
(a read-only evidence snapshot, not a trading terminal).

## Validation

Four separate pieces of evidence, never mixed:

1. **Discovery study.** 185 corporate actions give 127 usable dividend events once each
   dividend amount is checked against the issuer. On average the price fell by
   `0.97 ± 0.18` times the dividend by 04:00 ET. This is where the effect was found, so it
   is not out-of-sample evidence.
2. **Walk-forward test.** Only 56 of the 127 events had their dividend published before the
   moment of decision, so only those are used. The rule is refit on past data only and
   tested on later, untouched windows covering 47 calendar days and 39
   events. It made **0 EXIT trades** at every tested cost from 10 to 100 bps and every
   withholding rate from 0% to 30%. Exnight therefore matched holding: total
   return **−0.096%**, Sharpe **−2.57**, and **0.000%** better or worse than holding. That is
   **not** evidence of alpha. For comparison, stepping out of every event would have lost
   **−32.5 bps per event** against holding and beaten it on only 13% of events. That
   comparison was added after the results were known and changes nothing frozen. See
   [the complete scorecard](docs/competition_scorecard.md).
3. **Frozen rule, recorded live.** Strategy V1 was frozen on 17 September and then recorded
   minute by minute. The 21 September recording has a real 57-minute gap and stays
   `INCOMPLETE`. The 22 September recording passed its checks (1,348 rows per token, longest
   gap 63 seconds). Its overall score is `INCOMPLETE` because two of the three tokens had no
   verified dividend amount. On the third, rSATA, V1 said `HOLD`, and the price did not move.
4. **Strategy V3, the withholding gap.** V1 steps out only if that wins even when the holder
   keeps the whole dividend. V3 asks the narrower question: does the fall beat what the holder
   documentedly keeps after 30% withholding, plus costs? V3 was registered before any V3
   number was computed. On past data it makes 0 EXITs. Going forward, its cautious estimate
   of the fall (0.599 of the dividend) is below the 0.70 a holder keeps, so it currently holds
   on every event. Any EXIT would also need a dividend of roughly 70 bps or more. V3 is being
   recorded live on 16 high-yield ex-dates from 25 September to 8 October. See
   [docs/v3.md](docs/v3.md).

Historical trading costs are modeled, not observed, and labelled **MODELED_EXECUTION**
everywhere. Real execution capacity is reported separately: the recorded Reality tokens had
empty public order books. One $10 order filled in full at the quote
([live fill](docs/live_fill_20260923.md)); fills at $1k, $5k and $25k are unproven.

## Progress and deliverables

Delivered:

- the 185-action source ledger and the 127-event resolved discovery study;
- a knowledge-time table with T0, publication time, entitlement handling, fees, and exclusions;
- runnable expanding-window strategy code with a frozen, hashed manifest;
- policy, HOLD benchmark, and active-return scorecards with full cost/withholding sensitivity;
- a minute recorder, independent health checks, and offline forward scorer;
- a read-only consumer dashboard and guarded, human-confirmed order preparation; and
- one command that regenerates the competition artifacts from committed inputs.

```bash
.venv/bin/python scripts/build_competition_submission.py
```

The exact portfolio, T0/T1, fold, rung-selection, and execution conventions are in
[the competition methodology](docs/competition_methodology.md). The frozen machine-readable
manifest is `data/results/competition_backtest_manifest.json`.

## Quick start

Exnight requires Python 3.11 or newer.

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pytest -q
```

The public Bitget API checks are opt-in: run
`EXNIGHT_RUN_LIVE_TESTS=1 .venv/bin/python -m pytest -q tests/test_market_live.py`
when network access is available.

Public-market research does not require API credentials. Copy `.env.example` to `.env` only
if you need one of the optional authenticated features, and never commit that file.

To verify the saved evidence without making network requests:

```bash
.venv/bin/python scripts/verify_evidence.py
```

## Dashboard

Start the dashboard from the project root:

```bash
.venv/bin/python dashboard/server.py --host 127.0.0.1 --port 8787
```

Then open `http://127.0.0.1:8787/`. On a remote server, use an SSH port forward rather than
exposing the dashboard to the public internet.

The dashboard's Decisions page contains the token lookup. Users can enter forms such as `rAPH`,
`RAPHUSDT`, or `APH` and receive the nearest evaluated decision for each supported trade size.
It also shows recorder health, upcoming events, detailed strategy results, data sources, and
known limitations. If a token has not been evaluated, Exnight says so rather than guessing.

## Running the research pipeline

The main commands are shown below in the order they are normally used.

```bash
# Build or resume the Reality event calendar.
.venv/bin/python scripts/build_reality_ledger.py --start-date 2026-06-01

# Resolve event values and company evidence.
.venv/bin/python -m exnight.basis

# Measure price changes around each usable event.
.venv/bin/python -m exnight.eventstudy \
  --ledger data/ledger/reality_notice59_resolved.jsonl \
  --output data/results/event_results_resolved.json

# Record other news or market conditions that may explain a price move.
.venv/bin/python -m exnight.confounders \
  --results data/results/event_results_reality.json \
  --output data/results/confounders_reality.csv \
  --reality-ledger data/ledger/reality_notice59_resolved.jsonl

# Estimate trading costs from available market evidence.
.venv/bin/python -m exnight.costs \
  --results data/results/event_results_reality.json \
  --ledger data/ledger/reality_notice59.jsonl \
  --output data/results/event_costs_reality.csv

# Apply the saved version-one strategy.
.venv/bin/python -m exnight.strategy \
  --rule strategy/strategy_v1.json \
  --tag _v1
```

These commands keep unresolved events visible. A row is not silently dropped or assigned a
made-up value simply to produce a cleaner result.

The legacy-named `reality_notice59*.jsonl` files each contain 185 corporate actions. The
unresolved ledger yields 58 usable events; issuer and basis resolution expands the usable
sample to 127. Strategy V1 was frozen on the 127-event resolved study. The command above uses
that resolved ledger, so it reproduces the study and `premarket_0400` estimate on which V1 was
frozen (`pdr_hat = 0.9656110633409245`). The unresolved 58-event study remains available for
audit, but it is not V1's estimation sample.

## Scoring the completed September 22 observation

Run this only after the recording window closes:

```bash
.venv/bin/python scripts/score_forward.py \
  data/raw/recorder/20260922_rAPH_rSATA_rSTM/*.jsonl \
  --symbols RAPHUSDT RSATAUSDT RSTMUSDT \
  --event-date 2026-09-22 \
  --rule strategy/strategy_v1.json \
  --ledger data/ledger/reality_notice59_resolved.jsonl \
  --signals data/results/signals_v1.csv \
  --output data/results/forward_score_20260922.json
```

The scorer works only from the saved recording. It does not fetch a newer quote to repair a
late or missing sample, and it cannot place an order. A passing report therefore means the
required observations were genuinely present and on time.

## Trading safety

The normal workflow is research-only. Even when live trading is configured, Exnight refuses
an order unless it has:

- a funded Bitget account with the required permission;
- a fresh quote and a public two-sided order book;
- enough available balance;
- a quantity that meets the market's size and value rules;
- a final price and balance check immediately before submission; and
- an exact confirmation string supplied by the operator.

Real orders are capped at $100 by default. Withdrawals are not part of this project. The
optional Qwen analysis can add written context, but it cannot change the strategy result or
approve a trade.

## Project layout

- `exnight/` contains the market, calendar, analysis, cost, strategy, and trading code.
- `scripts/` contains the recorder, health check, evidence checker, and command-line jobs.
- `strategy/` contains the saved strategy rules. Version one is the frozen forward-test rule;
  version two contains later corrections and is kept separate.
- `dashboard/` contains the local read-only dashboard.
- `data/` contains source records and generated results. Large and live files are not all
  committed to Git.
- `tests/` contains the automated test suite.

## Known limits

- Bitget does not publish the exact dividend eligibility snapshot time, so Exnight suppresses
  a buy decision when that timing could change the answer.
- Historical order books are unavailable. A current order book cannot prove what could have
  filled on an earlier event date, so historical costs are modeled rather than observed.
- Only 56 of 127 resolved/usable events pass the ex-ante knowledge filter, and 45 of those are
  rSATA observations. The scorecard is therefore small and concentrated.
- The walk-forward produces no EXIT trades at the frozen confidence threshold. Rolling
  30-day Sharpe is `INSUFFICIENT_EVENTS`; there is no supported active-alpha claim.
- Seventy-one otherwise usable events lack pre-decision gross-basis evidence in the saved
  record. They remain excluded from the frozen scorecard; a separate
  [source audit](docs/dividend_provenance_audit.md) is checking dated issuer evidence.
- A ticker quote is not the same as executable liquidity. One $10 order on a token with an empty
  public book filled in full at the quote ([live fill](docs/live_fill_20260923.md)); capacity at
  $1k, $5k and $25k is still unproven.
- **No GetAgent Playbook is published, on purpose.** Checked against `@bitget-ai/getagent-skill`
  0.6.4 on 23 September: a normal trading Playbook can now trade spot rTokens such as
  `RAAPLUSDT`, and its dividend data carries ex-date, amount and declaration date. So the
  rule can be expressed. Two things stop a faithful version from being useful or honest.
  First, Exnight's rule has made no EXIT, so a faithful Playbook is a buy-and-hold rToken
  basket. Second, the Playbook backtest documentation describes no dividend crediting, so a
  bar-based backtest would count the ex-date price drop but not the dividend a holder
  receives. That makes stepping out look better than it is. Publishing either would
  misrepresent the result.
- Only one real fill exists: a $10 buy of rTOWN on 23 September, held through the ex-date as V3
  recommends. It filled at 36.28 against a 36.28/36.29 quote with a 10 bps fee. The sell leg and
  larger sizes are untested.

Deployment notes and the operational handoff are maintained in the private server workspace,
outside this repository.

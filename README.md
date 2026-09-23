# Exnight

## Thesis

Across 127 usable corporate-action observations, Bitget Reality-token ex-date repricing is
consistent with roughly the gross dividend by the 04:00 ET rung. But the amount a holder
actually retains can be lower and varies by event. Exnight measures whether stepping out
before that repricing beats remaining exposed, after documented or uncertain entitlement,
fees and execution costs.

## Target user and product value

**Track:** Alpha Factory → rToken Factor Strategies. Secondary fit: Open Theme,
execution-aware alpha.

**Target user:** a Bitget Reality-token holder with **$1,000–$25,000** positions in
dividend-paying rTokens, making a decision **around each ex-date** — whether to stay exposed
or step out temporarily when the expected repricing exceeds what they actually retain plus
execution costs.

Exnight turns the research into a reviewable `EXIT`, `HOLD`, or `NO_SIGNAL` decision. The
dashboard's Decisions page accepts forms such as `rAPH`, `RAPHUSDT`, or `APH`, shows the saved
result for each supported size, and explains when evidence is missing. BUY remains suppressed
because Bitget has not published its exact dividend-eligibility snapshot time.

**Live dashboard:** [jennycruzy.github.io/exnight](https://jennycruzy.github.io/exnight/)

The public dashboard is a sanitized evidence snapshot published from the `gh-pages` branch,
not a live trading terminal.
Recording and scoring continue on the private VPS workspace.

## Validation

The evidence is deliberately separated:

1. **Discovery study.** Both legacy-named `reality_notice59*.jsonl` ledgers contain 185
   corporate actions. The unresolved study yields 58 usable events; issuer and basis
   resolution yields 127. V1's 04:00 estimate is `0.965611 ± 0.183240`. This found the effect;
   it is not out-of-sample evidence.
2. **Walk-forward validation.** Only 56 of the 127 resolved/usable events have declaration
   evidence known before T0. The non-overlapping OOS folds cover 47 calendar days and 39
   events. The robust rule issued **0 EXIT trades** at every tested combination of 10–100 bps
   round-trip modeled cost and 0–30% withholding. Policy therefore equals HOLD: OOS total
   return **−0.096%**, Sharpe **−2.57**, and active return **0.000%**. This does **not** establish
   active alpha. See [the complete scorecard](docs/competition_scorecard.md).
3. **Frozen V1 and forward recorder.** V1 was frozen on 17 September and is not renamed as
   historical OOS. The 21 September run remains `INCOMPLETE` because of its genuine 57-minute
   gap. The 22 September recorder itself passed—1,348 rows per symbol and a 63-second maximum
   gap—but its combined score is `INCOMPLETE` because rAPH and rSTM lacked resolved dividend
   basis. rSATA produced the frozen `HOLD` decision and realised PDR 0.0.

Historical trading costs in the scorecard are always labelled **MODELED_EXECUTION**. Forward
capacity is separate: all three 22 September pairs returned empty public books, so executable
capacity at $1k, $5k, and $25k remains unproven.

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
- A ticker quote is not the same as executable liquidity. Exnight reports the distinction.
- GetAgent exposes dividend dates and amounts, but its selection-basket backtest cannot replay
  Exnight's event-by-event walk-forward test. A local prototype used today's quote and V1's
  fixed estimate, so it was removed rather than presented as the validated strategy. There is
  no comparable GetAgent backtest or published Playbook.
- The project has not yet demonstrated a real Reality-token fill.

Deployment notes and the operational handoff are maintained in the private server workspace,
outside this repository.

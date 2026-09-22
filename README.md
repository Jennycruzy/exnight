# Exnight

Exnight studies how Bitget Reality tokens react when a listed company reaches an important
calendar date, such as a dividend or stock split. It records prices around the event, checks
the quality of that recording, and produces a simple `BUY`, `EXIT`, `HOLD`, or `NO_SIGNAL`
result from a saved set of rules.

Exnight turns corporate-action and market evidence into clear Reality-token decisions. Enter
a supported token to see whether the saved strategy says `BUY`, `EXIT`, `HOLD`, or
`NO_SIGNAL`, together with the reason and the quality of the supporting data.

**Live dashboard:** [jennycruzy.github.io/exnight](https://jennycruzy.github.io/exnight/)

The public dashboard is a sanitized evidence snapshot published from the `gh-pages` branch.
Recording and scoring continue on the private VPS workspace.

## Why this project exists

A Reality token tracks a public company, but its market does not always behave exactly like
the underlying share. Corporate actions can create temporary price differences. Exnight is
designed to measure those differences without quietly replacing missing data or presenting a
theoretical price as a real fill.

The project can:

- collect Bitget ticker and order-book data at one-minute intervals;
- build a calendar of dividends, splits, and other company events;
- compare the token price before and after an event;
- estimate fees and trading costs when enough market data exists;
- apply a fixed, reviewable strategy rule;
- show the saved evidence in a local, read-only dashboard; and
- prepare a small order only after explicit human confirmation.

## Current state

The application and dashboard are complete and the full test suite passes: **95 tests**.

A new forward observation is currently running for the September 22 events:

- `RAPHUSDT`
- `RSATAUSDT`
- `RSTMUSDT`

The recorder runs once a minute and an independent health check runs every five minutes. At
the latest check, all three symbols were current, correctly ordered, and free of missing
intervals. The run ends at **2026-09-22 14:30 UTC**. Its final result must not be declared
until that time has passed and the saved recording has been scored.

The earlier September 21 observation remains marked `INCOMPLETE` because it contains a real
57-minute recording gap. That result is kept as part of the project history; the missing
period has not been filled with invented rows.

Bitget currently returns ticker quotes but empty public order books for some Reality pairs.
This does not stop price recording, but it means Exnight cannot claim that a proposed order
could have filled at those prices.

## Quick start

Exnight requires Python 3.11 or newer.

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pytest -q
```

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

The dashboard opens with a token decision lookup. Users can enter forms such as `rAPH`,
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
  --ledger data/ledger/reality_notice59.jsonl \
  --output data/results/event_results_reality.json

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

## Scoring the live September 22 observation

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
  filled on an earlier event date.
- Some company and tax records cannot be resolved from the available sources. They remain
  clearly marked instead of being guessed.
- A ticker quote is not the same as executable liquidity. Exnight reports the distinction.
- The project has not yet demonstrated a real Reality-token fill.

Deployment notes and the operational handoff are maintained in the private server workspace,
outside this repository.

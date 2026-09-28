# Exnight

**Should you sell your Bitget rToken before the dividend and buy it back afterwards?
Usually not. Exnight works out the answer for each event, and proves it.**

- **Live site:** [jennycruzy.github.io/exnight](https://jennycruzy.github.io/exnight/). Start
  here: a one-page explanation with a calculator you can play with.
- **App:** [jennycruzy.github.io/exnight/app](https://jennycruzy.github.io/exnight/app/). Live
  results, a token lookup, the backtest and every evidence file.
- **Track:** Alpha Factory → rToken Factor Strategies. Secondary fit: Open Theme,
  execution-aware alpha.

## The 60-second version

1. **The effect is real.** When a US stock pays a dividend, its Bitget rToken drops overnight by
   about the full dividend: 0.97× on average across 127 past events.
2. **Trading it doesn't pay.** Selling first avoids that drop, but you give up the dividend you
   would have kept (70% after US tax) and you pay for two trades. On data the rule had never
   seen, always selling first lost **32.5 bps per event**. Exnight never sold, so it lost nothing.
3. **It's tested live, and it can't cheat.** Each decision is committed to Git *before* the
   20:00 ET sell cutoff. A recorder saves prices every minute, and a scorer grades the decision
   after the ex-date. First graded event: rTOWN on 25 September. Holding was right; selling
   first would have lost $0.36 a share.
4. **A real order backs it.** A $10 rTOWN buy filled in full at the quoted price, on a token
   with no public order book, for a 10 bps fee.
5. **The edge is avoided loss, measured.** Against the alternative of selling first, Exnight is
   +32.5 bps per event on unseen data. EXIT fires only on rare high-yield events, which the
   live test is now covering. Trades of $1,000 or more use modelled costs.

## Who it's for

A Bitget rToken holder with **$1,000–$25,000** in dividend-paying tokens who wonders, before each
ex-date, whether to hold overnight or sell and buy back. For every event and trade size, Exnight
answers with one of three words, plus the reason and the evidence:

| Answer | Meaning |
|---|---|
| **HOLD** | Keep the token. Selling first would cost more than it saves. |
| **EXIT** | Sell before the 20:00 ET cutoff and buy back after. Only when that clearly wins after tax and costs. |
| **NO_SIGNAL** | Not enough evidence to decide, for example a trade bigger than the visible quotes. Exnight won't guess. |

Exnight never says BUY. Buying before the ex-date just to collect the dividend lost money in
every scenario tested, because the price falls by about the whole dividend.

## How it decides

Three numbers, all measured from Bitget data:

1. **The drop.** How far the price falls, as a multiple of the dividend (the *price-drop ratio*).
   Exnight uses a cautious estimate, not the average, so it never acts on a lucky guess.
2. **What you keep.** The part of the dividend you'd receive after tax is withheld (up to 30%).
3. **The cost.** Two trading fees plus slippage.

Selling first pays only if *the drop* is bigger than *what you keep* plus *the cost*. Today,
Exnight's cautious drop estimate is 0.60× the dividend, below the 0.70× a holder keeps, so the
answer is HOLD on every event until the evidence gets stronger. You can try the arithmetic
on the landing page's calculator.

## Results

### 1. Backtest on unseen data

The rule was fitted on past events only, frozen, and then tested on later events it had never
seen, using only dividend information published before each decision:

| Out-of-sample, 39 events over 47 days | Exnight | Always step out | Hold |
|---|---:|---:|---:|
| Trades | 0 | 39 | 0 |
| Result against holding, per event | 0 bps | **−32.5 bps** | — |
| Events where stepping out beat holding | — | 13% | — |
| Total return | −0.096% | −0.600% | −0.096% |
| Sharpe | −2.57 | −22.93 | −2.57 |

"Step out" means sell before the ex-date and buy back after. Doing that every time lost 32.5 bps
per event after fees and slippage, and it lost at every cost tested (10 to 100 bps) and every
tax rate (0% to 30%). Exnight made no trades, so it matched holding exactly. Holding's small
negative return comes from ordinary market moves on those nights, not from anything Exnight did.
The always-step-out comparison was added after the results were known and changes nothing that
was frozen.

### 2. Live test (running now)

Strategy V3 is recording 16 high-dividend events from 25 September to 8 October. Each decision
is locked before the sell cutoff and graded after the ex-date:

| Token | Ex-date | Dividend | Locked decision | Price drop ÷ dividend | Selling first vs holding | Recording |
|---|---|---:|---|---:|---:|---|
| rTOWN | 25 Sep 2026 | $0.28 (77 bps) | NO_SIGNAL (quotes too thin for $1k) | 0.00× | **−$0.36/share**: holding was right | PASS: 1,110 samples, longest gap 62 s |

Scores are saved as [`data/results/forward_score_v3_*.json`](data/results/) and appear in the
app as soon as each event is graded. Trading costs here are modeled because these tokens have
no public order book.

### 3. A real order

On 23 September, 0.2783 rTOWN (about $10) was bought at 36.28 against a 36.28/36.29 quote. It
filled in full in 0.4 seconds with a 10 bps fee and no slippage, even though the public order
book was empty. The position is being held through the ex-date to measure the tax actually
withheld. Details: [live fill](docs/live_fill_20260923.md).

### 4. How the rule was found and checked

1. **Discovery study.** 185 corporate actions give 127 usable dividend events once each dividend
   amount is checked against the issuer. On average the price fell by `0.97 ± 0.18` times the
   dividend by 04:00 ET. This is where the effect was found, so it doesn't count as a test.
2. **Walk-forward test.** Only 56 of the 127 events had their dividend published before the
   moment of decision, so only those are used. The rule is refit on past data only and tested
   on later, untouched windows covering 47 calendar days and 39
   events. It made **0 EXIT trades** at every cost and tax rate tested. Exnight therefore
   matched holding: total return **−0.096%**, Sharpe **−2.57**, and **0.000%** better or worse
   than holding. That is **not** evidence of a trading edge. Full detail:
   [the scorecard](docs/competition_scorecard.md).
3. **First live recordings (Strategy V1).** V1 was frozen on 17 September and recorded minute by
   minute. The 21 September recording has a real 57-minute gap and stays `INCOMPLETE`. The
   22 September recording passed its checks (1,348 samples per token, longest gap 63 seconds),
   but two of its three tokens had no verified dividend amount. On the third, rSATA, V1 said
   `HOLD` and the price didn't move.
4. **Strategy V3.** V1 sells only if that wins even when the holder keeps the whole dividend. V3
   asks the sharper question: does the drop beat what the holder keeps after 30% tax, plus
   costs? V3 was registered before any V3 number was computed. On past data it makes 0 EXITs.
   Any EXIT would need a dividend of roughly 70 bps or more. See [docs/v3.md](docs/v3.md).

## How it stays honest

- **Decisions are locked in advance.** Every forward decision is committed to Git before the
  sell cutoff, with a run manifest. Git history shows it couldn't be changed afterwards.
- **No hindsight.** The backtest only uses dividends that were published before each decision.
- **Grades come only from the saved recording.** The scorer can't fetch newer prices to repair a
  gap. A PASS means every minute was genuinely there.
- **Modeled is labelled as modeled.** Historical trading costs can't be observed (old order
  books don't exist), so they're marked `MODELED_EXECUTION` everywhere.
- **Unresolved events stay visible.** Nothing is dropped or filled in with a made-up value to
  make a result look cleaner.

## Findings

- **The dividend trade doesn't pay on rTokens, in either direction.** Buying before the
  ex-date to collect the dividend lost money in every scenario tested on 127 events. Even the
  most favourable case (counted as a holder, no tax withheld, 10 bps slippage) lost −17.7 bps per
  event, and not being counted makes it −57.5 bps or worse
  (`data/results/buy_capture_evidence.json`). Selling first lost 32.5 bps per event on unseen
  data. Exnight said HOLD, so it finished **32.5 bps per event ahead of selling first**.
- **Bitget's Playbook backtester would get this wrong.** Checked against
  `@bitget-ai/getagent-skill` 0.6.4 on 23 September: a Playbook can trade spot rTokens and read
  dividend dates, but its backtest doesn't credit dividends. It counts the price drop and not
  the dividend paid, so selling first looks better than it is. Exnight documents this gap
  instead of publishing a misleading Playbook.

## Scope and limits

- **EXIT is rare by design.** It fires only when the yield is about 70 bp or more and the
  uncertainty in the drop estimate is under 0.133. No past event met both conditions, so the
  backtest made no EXIT trades and the rolling 30-day Sharpe is `INSUFFICIENT_EVENTS`. The
  high-yield events being scored live (25 Sep – 8 Oct) are the first real test.
- **The sample is concentrated.** 56 events pass the knowable-in-advance filter, and 45 of
  those are rSATA. Another 71 are waiting on dated issuer evidence; a
  [source audit](docs/dividend_provenance_audit.md) is checking them.
- **Larger trades are modelled, not yet filled.** A $10 order filled at the quote. Fills at
  $1k, $5k and $25k, and on the sell side, use modelled costs.

## Using the app

The [app](https://jennycruzy.github.io/exnight/app/) has six pages:

| Page | What it shows |
|---|---|
| Overview | The answer in one line, the latest live results and the backtest table. |
| Live test | All 16 scheduled events, each locked decision, and the graded outcome. |
| Check a token | Type `rAPH`, `RAPHUSDT` or `APH` to see the decision at $1k, $5k and $25k. |
| Backtest | How the rule was fitted and tested, fold by fold. |
| Recorder | The minute-by-minute price recording and its health checks. |
| Evidence | Downloadable scores and manifests, and the known limits. |

It is read-only: there are no trading controls. If a token hasn't been evaluated, it says so
rather than guessing.

## Run it yourself

Exnight needs Python 3.11 or newer.

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pytest -q
```

Check the saved evidence without any network requests:

```bash
.venv/bin/python scripts/verify_evidence.py
```

Regenerate every competition result from committed inputs:

```bash
.venv/bin/python scripts/build_competition_submission.py
```

The exact conventions (decision times, folds, cost model) are in
[the competition methodology](docs/competition_methodology.md), and the frozen manifest is
`data/results/competition_backtest_manifest.json`.

Public-market research needs no API keys. Copy `.env.example` to `.env` only for the optional
authenticated features, and never commit that file. Live Bitget API tests are opt-in:
`EXNIGHT_RUN_LIVE_TESTS=1 .venv/bin/python -m pytest -q tests/test_market_live.py`.

### Local dashboard

```bash
.venv/bin/python dashboard/server.py --host 127.0.0.1 --port 8787
```

Open `http://127.0.0.1:8787/` for the landing page or `http://127.0.0.1:8787/app/` for the app.
On a remote server, use an SSH port forward rather than exposing it to the internet.

### The research pipeline

In the order they're normally run:

```bash
# Build or resume the Reality event calendar.
.venv/bin/python scripts/build_reality_ledger.py --start-date 2026-06-01

# Resolve dividend amounts and company evidence.
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

The `reality_notice59*.jsonl` files (named after the first notice) each hold 185 corporate
actions. The unresolved ledger gives 58 usable events; checking dividend amounts against issuers
expands that to 127. V1 was frozen on the 127-event study, and the command above reproduces its
`premarket_0400` estimate (`pdr_hat = 0.9656110633409245`).

### Grading a recording

Live V3 windows are graded automatically each hour by `scripts/score_due_v3.py`. To grade the
22 September V1 recording by hand, after its window has closed:

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

## Trading safety

Normal use is research only. Even with live trading configured, Exnight refuses an order unless
it has a funded account with the right permission, a fresh quote, enough balance, a size that
meets the market's rules, a final price and balance check just before sending, and an exact
confirmation string typed by the operator. Real orders are capped at $100 by default, and
withdrawals aren't supported. The optional Qwen analysis can add written context, but it can't
change a decision or approve a trade.

## Project layout

- `exnight/`: market data, event calendar, analysis, costs, strategy and trading code.
- `scripts/`: the recorder, health checks, scorers, evidence checker and site builder.
- `strategy/`: the saved strategy rules. V1 is the frozen forward-test rule; V2 holds later
  corrections; V3 is the withholding-aware rule being tested live.
- `dashboard/`: the landing page (`index.html`) and the app (`app/`).
- `data/`: source records and generated results. Large live recordings aren't all committed.
- `tests/`: the automated test suite.

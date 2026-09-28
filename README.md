# Exnight

Every time a US stock pays a dividend, its Bitget rToken drops overnight. So here's the obvious
idea: sell the night before, skip the drop, buy back in the morning.

I tested it. It doesn't work, and Exnight is the tool that tells you when it would.

- Live site: [jennycruzy.github.io/exnight](https://jennycruzy.github.io/exnight/) (start here,
  there's a calculator you can play with)
- App: [jennycruzy.github.io/exnight/app](https://jennycruzy.github.io/exnight/app/) (live
  results, token lookup, backtest, all the evidence)
- Track: Alpha Factory, rToken Factor Strategies

## The short version

The drop is real. Across 127 past dividends, the rToken fell by 0.97x the dividend on
average by 04:00 ET. Almost the whole thing.

But selling first means you don't get the dividend either. After 30% US tax you'd have kept 70%
of it, and you pay two trading fees plus slippage to get out and back in. Put those together
and the trade loses.

How badly? I froze the rule and ran it on 39 events it had never seen. Selling first every time
lost 32.5 bps per event. It only beat holding 13% of the time. Exnight said hold on all 39, so
it came out 32.5 bps per event ahead of the obvious strategy.

The flip side loses too. Buying right before the ex-date to grab the dividend lost money in
every setup I tried, even the kindest one (-17.7 bps per event).

## Why you can trust the numbers

It's being tested live right now, on 16 high-dividend events between 25 September and
8 October. For each one, the decision gets committed to Git before the 20:00 ET sell cutoff,
a recorder saves the price every minute, and a scorer grades it after the ex-date. Git history
shows none of it was edited afterwards.

Four graded so far. Holding was right on rTOWN, rINDB and rKDP. The fourth, rBZ, is the
interesting one: a big dividend and a full-size drop, so selling first would have won by
$0.13 a share if 30% tax is withheld, and lost by $0.02 if it isn't. That's exactly the kind of
event where EXIT starts to become possible.

I also placed a real order. On 23 September I bought about $10 of rTOWN at 36.28. It filled in
full in under half a second at the quoted price, even though the public order book was empty.
I'm holding it through the ex-date to see how much tax actually gets taken.

## Who it's for

If you hold somewhere between $1,000 and $25,000 of dividend-paying rTokens and you've
wondered whether to sit through the ex-date or step out, this is for you. For each event and
trade size you get one of three answers:

| Answer | What it means |
|---|---|
| **HOLD** | Keep it. Selling first costs more than it saves. |
| **EXIT** | Sell before 20:00 ET, buy back after. Only when that clearly wins after tax and costs. |
| **NO_SIGNAL** | Not enough evidence, e.g. your trade is bigger than the visible quotes. It won't guess. |

There's no BUY. Buying for the dividend lost money every time, so recommending it would be
dishonest.

## How it decides

It's three numbers:

1. **How far the price drops**, as a multiple of the dividend. Exnight uses a cautious
   estimate instead of the average, so a lucky run of data can't push it into a trade.
2. **How much of the dividend you'd keep** after tax (up to 30% withheld).
3. **What the round trip costs**: two fees plus slippage.

Selling first only pays if the drop is bigger than what you keep plus the cost. Right now the
cautious drop estimate is 0.60x the dividend and a holder keeps 0.70x, so the answer is HOLD.
The calculator on the site lets you move the numbers and watch it flip.

## Results

### Backtest on unseen data

The rule was fitted on past events, frozen, then run on later events it hadn't seen, using only
dividend info that was public at decision time:

| 39 unseen events over 47 days | Exnight | Always sell first | Just hold |
|---|---:|---:|---:|
| Trades | 0 | 39 | 0 |
| Per event, vs holding | 0 bps | **-32.5 bps** | — |
| Times selling first won | — | 13% | — |
| Total return | -0.096% | -0.600% | -0.096% |
| Sharpe | -2.57 | -22.93 | -2.57 |

Always selling first lost at every cost I tested (10 to 100 bps) and every tax rate (0% to
30%). The small negative return for holding is just normal market movement on those nights.
I added the always-sell-first column after seeing the results; it doesn't change anything that
was frozen.

### Live test (running now)

| Token | Ex-date | Dividend | Locked decision | Drop ÷ dividend | Selling first vs holding | Recording |
|---|---|---:|---|---:|---:|---|
| rTOWN | 25 Sep 2026 | $0.28 (77 bps) | NO_SIGNAL (quotes too thin for $1k) | 0.00x | **-$0.36/share**, holding was right | PASS: 1,110 samples, longest gap 62 s |
| rBZ | 28 Sep 2026 | $0.51 (362 bps) | NO_SIGNAL (quotes too thin for $1k) | 1.08x | +$0.13/share if 30% tax is withheld, -$0.02 if you keep it all: too close to call | PASS: 3,990 samples, longest gap 62 s |
| rINDB | 28 Sep 2026 | $0.64 (79 bps) | NO_SIGNAL (quotes too thin for $1k) | 0.00x | **-$0.81/share**, holding was right | PASS: 3,990 samples, longest gap 62 s |
| rKDP | 28 Sep 2026 | $0.23 (72 bps) | HOLD at $1k and $5k | 0.65x | **-$0.16/share**, holding was right | PASS: 3,990 samples, longest gap 62 s |

Scores land in [`data/results/forward_score_v3_*.json`](data/results/) and show up in the app
as each event is graded. Costs here are modelled because these tokens have no public order
book. Details of the real fill: [live fill](docs/live_fill_20260923.md).

### How I got here

1. **Finding the effect.** 185 corporate actions, 127 usable once each dividend was checked
   against the issuer. Average drop by 04:00 ET: 0.97 ± 0.18x the dividend. This is where I
   found it, so I don't count it as a test.
2. **Walk-forward test.** Only 56 of the 127 had their dividend published before decision
   time, so only those are used. Refit on the past, test on the next window, 39 test events in
   total. Zero EXIT trades at any cost or tax rate, so Exnight matched holding exactly. That
   isn't a trading edge on its own. Full detail: [scorecard](docs/competition_scorecard.md).
3. **First live runs (V1).** Frozen 17 September. The 21 September recording has a real
   57-minute gap, so it's marked INCOMPLETE rather than patched. 22 September passed its
   checks; on rSATA, V1 said HOLD and the price didn't move.
4. **V3, the current rule.** V1 only sold if it would win even if you kept the whole dividend.
   V3 asks the better question: does the drop beat what you actually keep after 30% tax, plus
   costs? I registered V3 before computing any V3 numbers. See [docs/v3.md](docs/v3.md).

## Something I found along the way

Bitget's GetAgent Playbooks (checked on `@bitget-ai/getagent-skill` 0.6.4, 23 September) can
trade spot rTokens and read dividend dates. But the Playbook backtest doesn't credit dividends.
It sees the price drop and not the payout, so selling first looks better than it really is.
I didn't publish a Playbook for Exnight, because it would've shown a misleading result.

## How it stays honest

- Decisions are committed before the cutoff. You can check the Git history.
- The backtest only uses dividends that were public at decision time.
- The scorer only reads the saved recording. It can't go fetch newer prices to fill a gap.
- Anything modelled is labelled `MODELED_EXECUTION`, because old order books don't exist.
- Nothing gets dropped to make the results look cleaner.

## What's still open

- **EXIT hasn't fired yet.** It needs a dividend of roughly 70 bps or more *and* a tight drop
  estimate (uncertainty under 0.133). Nothing in the past met both, which is why the 30-day
  Sharpe says `INSUFFICIENT_EVENTS`. The high-dividend events running live now are the first
  real chance.
- **The sample leans on one token.** 56 events are usable without hindsight and 45 of them are
  rSATA. Another 71 are waiting on dated issuer evidence
  ([source audit](docs/dividend_provenance_audit.md)).
- **Big trades are modelled.** The $10 order is real. $1k, $5k and $25k fills, and the sell
  side, use modelled costs for now.

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

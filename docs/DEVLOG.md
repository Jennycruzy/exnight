# Developer log: errors found and limits hit

Every mistake I caught in my own work, and every Bitget platform limit I ran into, with the date
and what happened next. Nothing here was hidden or quietly patched; each fix is in the Git history.

## Errors I made and fixed

| Date | What was wrong | What I did |
|---|---|---|
| 16 Sep | The first event study used the wrong holiday calendar and candle window, and it paged history incorrectly. | Rebuilt the measurement with Bitget's own calendar, the correct window and deduplicated paging, then reran it (`9125d30`). |
| 16 Sep | Reality dividend dates were read as UTC dates, which put some ex-dates a day off. | Dates now follow Bitget's UTC+8 calendar, checked against its notices (`a1661be`). |
| 17 Sep | An early headline said the rToken drops only **0.66×** the dividend. It came from mixing before-tax and after-tax dividend amounts. | Withdrew it publicly and rebuilt with strict before-tax matching. The real drop is the full dividend (`1250267`). |
| 18 Sep | Forward scoring could pass with an event missing. | It now fails if any scheduled event is missing (`0440d28`). |
| 23 Sep | An earlier drop estimate of 1.73× came from letting the data pick the read time (09:30, when the market opens and other news dominates). | Fixed the read time at 04:00 ET before any new number was computed. The estimate became 0.94 ± 0.35 (`83e7ab0`). |
| 23 Sep | Bitget's 89-stock dividend notice shows the date 24 July, but it lists August payments, so it can't have been published then. | Stopped treating a page's displayed date as its publication date. The time we fetched it is used instead. |
| 23 Sep | A slow API call could make the next minute's price rows land out of order and fail validation. | Recorder runs are now locked one at a time, and a failed sample is retried within the same minute (`19e7ffc`). |
| 1 Oct | The site called some events "holding was right" when no one traded overnight, so there was no price to judge by. | Each event now carries a trading label (none / thin / priced), and only priced events are judged. |
| 1 Oct | The scorer sometimes failed to publish the site after grading. | The publish step now has the credentials it needs and checks the connection first. |

## Bitget platform limits I hit

| Date | Limit | How Exnight handles it |
|---|---|---|
| 16 Sep | The candle API rejects `limit` above 1000 (above 100 for history) and rejects the 3-minute interval its docs list. | The client uses only limits and intervals proven to work, and pages around the caps. |
| 16 Sep | Daily candles before a token's listing are back-filled reference data, not rToken trading. | Bars before listing are dropped and never used to measure the market. |
| 16 Sep | Bitget re-lists a token around a split, and its earlier intraday history disappears (rAPH, rSOXS, rTZA). | Treated as a break in the series, never as a zero return. |
| 16 Sep | Candle volume follows the US stock tape, not rToken fills. | Liquidity is never inferred from volume. |
| 16 Sep | The demo (paper) venue rejects Reality spot orders. | The real-order test used a small live order instead (23 Sep, $10 of rTOWN). |
| 16 Sep | Most rToken order books are empty overnight, though a price quote still shows. 43 of 59 were empty in the first sample. | A real order proved that orders fill at the quoted price. A trade bigger than the quoted size gets "not enough data" instead of a guess. |
| 16 Sep | Bitget doesn't publish when it checks who is entitled to a dividend. | Exnight never recommends buying just to collect one. |
| 17 Sep | Old rToken order books aren't archived anywhere: Bitget doesn't keep them, and a third-party archive has prices but no overnight book. | Past trading costs are modeled and labelled ESTIMATED. |
| 17 Sep | Some dividend notices print the after-tax amount (rNXPI, rMDT), and tax rates differ by the company's home country. | Those amounts are excluded unless the before-tax figure is confirmed. |
| 16 Sep | The 24-hour turnover field leaves out flow routed to the US market, so it understates trading. | Never used to call a token untradeable. |
| 23 Sep | Bitget doesn't publish how much dividend tax an rToken holder keeps. | Exnight uses the full 0–30% range unless a Bitget notice confirms the rate. |
| 28 Sep | Bitget's Playbook backtester doesn't credit dividends, so selling first looks better there than it really is. | Exnight's own backtest counts every dividend. |
| 11 Oct | The rTOWN dividend was due 8 Oct 16:00 UTC by Bitget's own record and hasn't been credited yet. Bitget publishes no list of rToken payouts. | A read-only check runs every 15 minutes until 20 Oct and commits the credit when it lands. |

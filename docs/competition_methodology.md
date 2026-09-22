# Competition methodology

This document defines the Alpha Factory scorecard before any out-of-sample return is
computed. The machine-readable copy is `data/results/competition_backtest_manifest.json`.
The manifest's SHA-256 file must match or the scorer refuses to run.

## Evidence boundaries

The 127-event resolved study is discovery evidence. Strategy V1 was fitted on all 127 usable
events, so it has no historical out-of-sample window. The competition scorecard is instead
the **walk-forward OOS performance of the Exnight selection procedure**. Frozen V1 and its
forward recorder are reported separately.

## T0 / decision timestamp

For every event, **T0 is the final valid Bitget market observation at or before the strategy's
pre-event cutoff for that event, using the same session/calendar rules as Strategy V1.** For
normal ex-dates this corresponds to the pre-event decision point before the 20:00 ET
transition. Weekend, Monday, and market-holiday cases follow the existing Exnight calendar
logic rather than inventing a new timestamp.

`decision_ts` is T0. Every dividend fact, entitlement assumption, fee schedule, strategy
parameter, and other input used to produce the EXIT/HOLD/NO_SIGNAL decision must have been
publicly knowable by `decision_ts`.

T1 is the first valid observation at or after the selected post-event rung, initially drawn
from the five rungs already studied: 20:00, 04:00, 09:30, 10:00, and 16:00 ET.

Automated tests verify that no historical decision uses information published after its
`decision_ts`, and that every fold's training outcomes predate its test decisions.

## Walk-forward rule

The initial development window ends 31 July 2026. The two non-overlapping OOS folds are
August and 1–16 September, giving 47 OOS calendar days. Each fold uses only events whose
outcomes were observable before its first decision and requires at least 15 eligible training
events.

The rung rule mechanizes the reasoning recorded before V1 was frozen in `docs/m2.md` and
commit `c7463451532fd346c27526029a39f6625640c0f9`. Within each training-only calendar
subperiod containing at least three eligible events, a rung is stable when its PDR point
estimate remains above the documented 0.70 retained-dividend alternative and gross PDR = 1
lies within two standard errors. The earliest stable rung is selected. If none qualifies,
`premarket_0400` is the documented robust fallback. This mechanical rule was written after
V1 froze; it was derived from the pre-freeze record and was not selected by viewing OOS
returns.

IS means the initial development window only. Expanding training windows are never joined
into an artificial return series. OOS means the concatenated, non-overlapping test folds.

## Portfolio and execution

Each event receives $1,000 on a fixed $25,000 capital base. When more than 25 events overlap,
capacity goes to the highest ex-ante lower-bound edge, then earliest `decision_ts`, then event
ID. Non-event days carry zero return.

The HOLD benchmark remains exposed from T0 to T1 and accrues the retained-dividend entitlement
at T1. This is a receivable, not a claim that Bitget paid cash by T1. EXIT holds USDT between
T0 and T1 and pays both taker fees plus modeled round-trip slippage. Policy return, HOLD
benchmark return, and active return are reported separately.

Historical execution is always labelled `MODELED_EXECUTION`. The base slippage assumption is
25 bps round trip, set a priori, with 10, 25, 50, and 100 bps reported. Current visible-book
capacity is separate forward evidence and never supplies a historical cost.

When event-specific withholding was not published before T0, decisions carry the range 0%,
15%, 25%, and 30%. EXIT must remain better when withholding is 0%; HOLD must remain better
when withholding is 30%; otherwise the result is `NO_SIGNAL / ENTITLEMENT_UNCERTAIN`. Full
scorecards are also reported at each point of the range.

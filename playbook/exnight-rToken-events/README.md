# Exnight rToken Event Decisions

This Playbook turns Exnight's corporate-action research into a current,
non-trading watchlist for Bitget Reality-token holders. It checks whether a
declared dividend was knowable at the run date, compares staying exposed with
temporarily exiting, and shows the assumptions behind the result.

## 策略 / Strategy

The package checks five exchange-verified rToken markets, pairs each token with
its underlying US security, reads declared cash-dividend events and the current
Bitget spot ticker, then applies the frozen Exnight V1 price-drop estimate. It
emits a structured basket; it never places or approves an order.

## 开仓 / Entry

There is no automatic entry. An event is evaluated only when its dividend is
positive, its ex-date is inside the configured horizon, and its declaration
date is no later than the run date. `decision_ts` is the current snapshot time.

## 平仓 / Exit

An item says EXIT only when exiting beats holding under the most
holder-favourable entitlement case: zero withholding. It says HOLD when exit
still loses at 30% withholding. A result that flips inside the 0–30% range is
shown as `ENTITLEMENT_UNCERTAIN`. Two taker fees and 25 bps modeled round-trip
slippage are included.

## 风险 / Risk

Bitget's exact dividend eligibility snapshot time remains unpublished, so the
package does not produce BUY decisions. Some Reality-token public books can be
empty, withholding varies by event, and this live basket is not the historical
walk-forward scorecard. Every order remains a separate human decision.

## Local validation

From the official GetAgent skill package:

```bash
python3 scripts/validate.py /path/to/exnight/playbook/exnight-rToken-events
```

Cloud upload and the first paper run require a Bitget OpenAPI `ACCESS-KEY`.
The package must remain temporary until its data output has been reviewed.

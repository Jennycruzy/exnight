# Dividend source audit — 23 September 2026

This is a data-quality investigation, **not a replacement backtest**. The frozen
competition manifest, knowledge-time table, decisions and scorecard are unchanged.

Bitget's [public dividend-history endpoint](https://www.bitget.com/docs/catalog/reality/basic-info)
returned an exact ex-date and gross-amount match for each of the 71 otherwise usable
events excluded for missing pre-decision gross-dividend evidence. Of those, 36 have an
API announcement date before T0; 35 have a date on T0, where a date without a publication
time cannot establish that the information was available before the decision. The API
was fetched on 23 September, so its historical announcement date alone is not proof of
past public availability.

The [candidate table](../data/results/dividend_provenance_candidates_20260923.csv)
records every event, the Bitget match, the decision time, and the primary-source review.
The [review file](../data/sources/dividend_primary_review_20260923.csv) links dated
issuer evidence. So far, 16 events match a pre-decision issuer amount and date; one
reviewed event, rBABA, does not. Alibaba's dated [issuer release](https://www.alibabagroup.com/en-US/document-1991364841188622336)
says $1.05 per ADS, while the saved Reality gross amount is $1.03. It stays excluded.
The other 54 events have not been cleared by this review.

The [training-only diagnostic](../data/results/dividend_provenance_training_impact_20260923.json)
shows what the 16 verified additions do to *past-data fits only*:

| Training window | Frozen inputs | With verified additions | Conservative repricing lower bound |
|---|---:|---:|---:|
| Initial / before August | 17 | 33 | −0.708 → 0.311 × gross dividend |
| Before September | 42 | 58 | 0.214 → 0.871 × gross dividend |

An EXIT under unknown withholding must clear the full gross dividend **plus costs**.
Neither updated lower bound does. The later estimate is also fragile: leaving out one
verified addition at a time changes its lower bound to between 0.282 and 0.973, and
sometimes changes the selected rung. These are diagnostics, not OOS performance.

Rebuild the audit from the saved public response without another network call:

```bash
.venv/bin/python scripts/audit_dividend_provenance.py \
  --raw data/sources/bitget_dividends_audit_20260923.json \
  --output data/results/dividend_provenance_candidates_20260923.csv \
  --training-impact-output data/results/dividend_provenance_training_impact_20260923.json
```

Next, review the remaining 19 earlier-date candidates against dated issuer releases,
then investigate the 35 same-day candidates only where a timestamped pre-T0 source
exists. Complete the source audit before producing any separately versioned amended
scorecard; do not promote selected events just because they improve a fit.

# 2015 haze feature ablation: results

Protocol: `docs/haze-2015-ablation-protocol.md`, committed before any fit. This is an exploratory retrospective comparison. It is not a forecast, not a source attribution and not independent of S3, which studied the same window.

**Result: no feature group showed a gain.** Ridge on PM2.5 lags did not beat persistence. Adding ERA5 wind and rain made the error larger, and adding FIRMS fire counts made it larger again. In both cases the interval of the paired skill is entirely below zero.

This is version 2, after an independent review. Version 1 is in the Git history. See "Corrections after review".

This is a deterministic study. No Meta model took part.

## Scores

- 5,195 scored region-hours over 44 days, from 18 September to 31 October 2015.
- 2,710 of those hours were above 55 µg/m³.
- The target is PM2.5 six hours ahead.

| Model | Features | MAE, all hours (µg/m³) | MAE above 55 µg/m³ |
|---|---|---|---|
| B0 | Persistence | 30.76 | 39.39 |
| B1 | 24 PM2.5 lags | 32.10 | 39.07 |
| B2 | B1 + 30 ERA5 wind and rain features | 36.73 | 44.29 |
| B3 | B2 + 9 FIRMS features | 41.75 | 49.20 |

## Paired comparisons

The 95% intervals come from 2,000 resamples of whole days, with seed 7.

| Comparison | All hours: skill (interval) | Above 55 µg/m³: skill (interval) | Rule |
|---|---|---|---|
| B1 vs B0 | -0.043 (-0.211 to 0.085) | 0.008 (-0.198 to 0.167) | no gain |
| B2 vs B1 | -0.144 (-0.231 to -0.067) | -0.134 (-0.251 to -0.026) | no gain; worse |
| B3 vs B2 | -0.137 (-0.209 to -0.070) | -0.111 (-0.195 to -0.028) | no gain; worse |

## Corrections after review

| Change | Before | After | Effect |
|---|---|---|---|
| Penalty search scaling | The inner holdout (last 20% of train rows) was part of the scaler's fit | The scaler for the search uses inner-train rows only; the final fit is scaled again on all train rows | None: every fold chose the same penalty, so B1, B2 and B3 did not change |
| FIRMS windows | Passes in (T-24h, T-3h]: 21 h and 69 h of passes | Passes in (T-27h, T-3h] and (T-75h, T-3h]: 24 h and 72 h of passes visible at T | B3 MAE 46.91 to 41.75; B3 vs B2 skill -0.277 to -0.137 |

Both changes are tested. The decision for every comparison stays "no gain".

## Time rules and their tests

`tests/test_haze_ablation.py` checks:

- no train target reaches the scored block;
- PM2.5 lags end at T-2 h;
- ERA5 features do not change when values at or after the issue hour change;
- each FIRMS window holds exactly its hours of passes visible at T, at both ends;
- the inner holdout does not change the inner-train scaling.

ERA5 is a reanalysis, made later with hindsight. Its indexing stops at T-1 h, but those values did not exist at T. So B2 and B3 measure association, not what a forecaster could know.

ERA5 rain is hourly, not a running total: peaks are 1.2 to 2.6 mm/h, and `check_precip` passes.

## Likely reasons, not tested here

- **Little training data:** fold 1 trains on 341 hours and scores the next 347. B2 has 54 features and B3 has 63.
- **Changing regime:** September and October 2015 differ in fire activity and wind. A model fitted on early weeks meets a different regime later.
- **Shared context:** box-mean winds and regional fire counts are one value for all five regions. They do not say which region the plume reaches.

## What this means

On this window, under this design, the extra products did not help. That does not show that wind or fire carry no information about haze. It shows that this short, two-month record cannot support a model that uses them. A test of that question needs several haze seasons and a predeclared design, and the sealed period stays closed.

## Reproduce

```bash
uv run python scripts/run_haze_ablation.py <haze-2015 run folder>
```

The record, with the SHA-256 of every input, is `docs/evidence/haze-2015-ablation.json`.

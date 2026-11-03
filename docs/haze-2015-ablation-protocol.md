# 2015 haze feature ablation: protocol

Status: frozen before any model is fitted. This is an exploratory retrospective comparison. It is not a forecast and not a source attribution. S3 already examined this window, so no result here is independent.

## Question

Over 1 September to 31 October 2015, do ERA5 wind and rain, and then FIRMS fire detections, lower the error of regional PM2.5 six hours ahead beyond what PM2.5 history alone gives?

## Data, all local and hash-pinned

| Input | Meaning | Spatial support | Time rule at issue time T |
|---|---|---|---|
| NEA hourly PM2.5, five regions | Target and lags | Each region | Newest usable value is T-2 h, as in E1 |
| ERA5 10 m and 850 hPa u and v, box means for boxes A, B, C | Reanalysis wind | One shared value for all five regions | Hours up to T-1 h UTC. ERA5 is hindsight data, so this measures association only. |
| ERA5 10 m precipitation, box means | Hourly amount, mm | Shared | Same as wind |
| FIRMS MODIS standard product, boxes A, B, C | Fire detections with UTC pass time | Shared | A detection counts if its pass time plus 3 h is at or before T |
| MCD64A1 | Monthly burned area | n/a | Not used: the map for a month is not available during that month |

No station value is joined to a region.

## Models

| Model | Features |
|---|---|
| B0 | Persistence: the newest usable PM2.5 value |
| B1 | Ridge per region on its own PM2.5 at T-2 h back to T-25 h (24 lags) |
| B2 | B1 plus, for each box and level, u and v at T-1 h and their 6 h means, and 10 m rain at T-1 h and its 6 h sum |
| B3 | B2 plus, for each box, the detection count in the last 24 h and 72 h, and the FRP sum in the last 24 h |

No neural model: 1,464 hours over five regions is too few for one.

## Validation

- **Samples:** issue times from 2015-09-04 00:00 to 2015-10-31 17:00 SGT, with targets that are present.
- **Blocks:** four equal, contiguous blocks. Fold k (k = 1, 2, 3) trains on blocks before k and scores block k.
- **Gap:** train issues whose target is at or after the start of the scored block are left out.
- **Scaling:** feature scaling is fitted on each fold's train rows.
- **Penalty:** the ridge penalty is chosen from 0.1, 1, 10, 100 and 1000 on the last 20 percent of each fold's train rows, by time.
- **Scores:** MAE over all scored hours, and MAE for hours with target above 55 µg/m³.

## Decision rule

Each model is compared only with the one before it: B1 with B0, B2 with B1, B3 with B2.

- **Paired skill:** 1 minus the ratio of the two models' MAE on the same rows.
- **Uncertainty:** the 95% interval comes from 2,000 resamples of whole days, with seed 7.
- **Gain:** an added feature group gives a gain only if the lower limit is above zero.
- **Elevated hours:** these are reported but have no decision rule.

## Limits, stated before the result

- **Few blocks:** two haze-heavy months make three scored blocks, so intervals will be wide.
- **Hindsight data:** ERA5 is reanalysis, so a gain from B2 is not a forecast gain.
- **FIRMS delay:** the 3 h delay is an assumption. The standard product was not published in real time.
- **Window already studied:** S3 used the same window.

## Amendment 1, after the first results and an independent review

The text above is unchanged. These points correct it:

- **FIRMS windows:** "the last 24 h" means passes in (T-27h, T-3h]: 24 h of passes that are visible at T. The same rule gives (T-75h, T-3h] for 72 h. The first code used (T-24h, T-3h], which is 21 h.
- **Penalty search:** the scaler for the inner holdout is fitted on inner-train rows only.
- **ERA5:** the T-1 h limit is an index rule. ERA5 values were not available at T.

The amendment came after the first results were known. Version 1 of the results stays in the Git history.

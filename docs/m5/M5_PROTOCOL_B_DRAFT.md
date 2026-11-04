# M5-B protocol draft: regional transport consistency (not frozen)

Status: DRAFT for review. No code has run. Freeze it (hash in a new `protocol-b.freeze.json`) only after review.
It is separate from `m5-protocol-1`, which is not edited.

## Question (verbatim, M5-B)

Which upwind fire regions show atmospheric transport conditions and temporal associations consistent with subsequent PM2.5 increases in Singapore? Can we distinguish suggestive evidence from unsupported source attribution?

## Design

- **Unit:** one UTC day. Outcome: change in Singapore daily mean PM2.5 from day d to day d+1 (regional mean of five NEA regions). Sealed NEA data (from 2024-01-01) is not read.
- **Regions:** source boxes A, B, C of the H1 design. Hindsight data is allowed (ERA5 850 hPa wind, FIRMS). This is retrospective evidence, never a forecast.
- **Exposure per box and day:** FIRMS detection count in the box on day d, times a transport score: the share of hours of day d with the 850 hPa wind at the box corridor blowing toward Singapore (within 45 degrees of the box-to-Singapore bearing).
- **Seasons:** 2015 and 2016 (ERA5 and FIRMS in hand). 2017 to 2019 need ERA5 (about 130 MB per season, one CDS request each). That download is not started until reviewed.

## Pre-registered tests (6 total, Holm over all 6)

1. For each box (3): rank correlation of exposure(d) with the PM2.5 change d to d+1, pooled over seasons.
2. For each box (3): the same exposure at lead -1 (day d+1 exposure against the change d to d+1) as a placebo. A placebo that matches the real test means the pattern is not specific to upwind transport.
- **Null:** circular shift of the outcome with at least 14 days of shift and at least 999 shifts, so that the smallest p can reach the Holm threshold. This corrects the flaw in Amendment 1.
- **Interval:** 7-day block bootstrap.

## Labels (the only allowed words)

- `consistent_with_transport`: real test passes Holm at 0.05, the placebo does not, and the sign is positive.
- `not_distinguishable`: anything else with a positive sign.
- `unsupported_attribution`: the placebo passes, or the sign is negative.
- No label uses the words "caused by" or "source of". Fire counts are thermal anomalies, not emissions.

## Limits to state in any report

Five regions are not stations. 850 hPa is not the plume height. Cloud and smoke hide fires. Two seasons hold few independent episodes. Box means ignore trajectory curvature. Rank correlation with day-level data is not a source apportionment.

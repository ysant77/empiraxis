# M5-B protocol v1: regional transport consistency (frozen after review)

Protocol id: `m5-protocol-b-1`. Separate from `m5-protocol-1`. Frozen before any run. Edits go in an amendment file.
Revised after the main-session review of the draft in commit `feeeef9`.

## Question (verbatim, M5-B)

Which upwind fire regions show atmospheric transport conditions and temporal associations consistent with subsequent PM2.5 increases in Singapore? Can we distinguish suggestive evidence from unsupported source attribution?

## Data and unit

- **Seasons:** 2015 to 2019, 1 September to 31 October (ERA5 and FIRMS). ERA5 for 2017 to 2019 is a free open download (about 390 MB).
- **Unit:** one UTC day d. **Outcome:** Singapore regional-mean PM2.5 on day d+1 minus day d. Sealed NEA data (from 2024-01-01) is not read.
- **Hindsight data is allowed.** This is retrospective evidence. It is not a forecast.
- **Exposure per box and day:** FIRMS detections in the box on day d, times a transport score. The score is the share of hours of day d with the 850 hPa corridor wind within 45 degrees of the box-to-Singapore direction.

## Tests (primary: 3; Holm over these 3, thresholds 0.0167, 0.025, 0.05)

For each box: pooled rank correlation of exposure(d) with the outcome, over all five seasons.

- **Null:** shift the outcome circularly inside each season, with an independent shift per season (each of at least 14 days from zero). Draw 9,999 random shift tuples. A season of 58 scored days has 31 valid shifts, so five seasons give 31^5 tuples. The smallest reachable p is 1/10,000 = 0.0001, below the first Holm threshold. A season-by-season test with 31 shifts could not pass (Amendment 1). This design can.
- **Interval:** block bootstrap by 7-day block inside each season.

## Controls (secondary; they decide the label)

1. **Lead control.** Compute the lag-k autocorrelation of the exposure series, using exposure only. Pick the smallest k of 2 or more days where it is below 0.2. Correlate exposure(d+k) with the outcome. The k and the autocorrelations are reported.
2. **Negative-control corridor.** Same fire counts, but the transport score uses the direction away from Singapore. Fire is the same and the wind carries it elsewhere.
3. **Contrast.** The label needs the real correlation to exceed each control: the bootstrap interval of (real minus control) must lie above 0. A control that is merely not significant is not evidence.
4. **Rain.** Washout is a confounder of the day-to-day change. The primary test is unstratified. A secondary run uses only days with ERA5 box-mean rain below the season median. Both are reported.

## Labels (the only allowed words)

- `consistent_with_transport`: primary test passes Holm, the sign is positive, and both contrasts (items 1 and 2) have intervals above 0.
- `not_distinguishable`: positive sign, but any condition above fails.
- `unsupported_attribution`: sign negative, or a control correlates as strongly as the real test (contrast interval includes 0 or is below 0 while the control is positive and significant).
- Never write "caused by", "source of" or "responsible". Fire counts are thermal anomalies, not emissions.

## Limits

Five NEA regions are not stations. 850 hPa is not the plume height. Cloud and smoke hide fires. Fire counts are autocorrelated. Five seasons hold few independent episodes. Rank correlation on days is not source apportionment. 2018 has little haze.

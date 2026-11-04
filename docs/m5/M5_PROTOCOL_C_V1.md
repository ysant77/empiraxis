# M5-C protocol v1: severe-episode prediction 12 to 24 h ahead (frozen after review)

Protocol id: `m5-protocol-c-1`. Separate from `m5-protocol-1`. Frozen before any fit. Edits go in an amendment file.
Revised after the main-session review of the draft in commit `feeeef9`.

## Question (verbatim, M5-C)

Can severe haze episodes be predicted 12-24 hours ahead using only information legitimately available at forecast time, with calibrated uncertainty and appropriate abstention?

## Event and counts (from `scripts/m5_event_rates.py`, `docs/m5/results/m5_event_rates.json`; counted before any fit)

Event at issue time T: any of the five regions has an hourly PM2.5 above **55 ug/m3** in (T+12 h, T+24 h]. The threshold is `elevated_threshold_ugm3` of `m5-protocol-1`.

| Season | Issues | Events | Base rate | Event days | Episodes |
|---|---|---|---|---|---|
| 2015 | 1386 | 1173 | 0.846 | 55 | 3 |
| 2016 | 1386 | 130 | 0.094 | 11 | 7 |
| 2017 | 1386 | 104 | 0.075 | 10 | 4 |
| 2018 | 1386 | 0 | 0.000 | 0 | 0 |
| 2019 | 1386 | 349 | 0.252 | 22 | 1 |

An episode is a run of event days with a gap of at most 1 day. Consequences, stated before the run: 2018 has no events, so it cannot calibrate anything.
The 2019 test season holds one episode. The result is therefore expected to be `no_supported_signal`. That is a valid finding.

## Inputs

Issue-time-valid only, checked by `availability.assert_issue_time_valid`: NEA lags (newest T-2 h) and FIRMS features (pass + 3 h, as in `m5-protocol-1`).
**No rain input.** IMERG Early exists for 2015 only, so rain would differ between training and scoring. ERA5, MCD64A1, HLS and MAIAC are hindsight only and excluded.

## Scheme

- **Fit** on 2015, 2016 and 2017 (2018 has no events and is left out of the fit). **Score** on 2019 only.
- **Calibration:** Platt scaling (a two-parameter logistic map) fitted on out-of-fold predictions from blocked inner folds over the three training seasons, with whole-week blocks. Isotonic is not used: too few episodes.
- **Rungs:** C0 climatology (the training base rate, one number). C1 persistence indicator: 1 if any region is above 55 at the newest observed hour (T-2 h), else 0. C1 gives only 0 or 1, so its Brier score is defined but a reliability table has two points and calibration is not assessed for it. C2 logistic regression on lags. C3 C2 plus FIRMS. C4 trees on C3 inputs, run only if C3 beats C0.

## Metrics, fixed before the run

- Brier score and Brier skill against C0. Reliability table in 10 bins for C2 to C4. ROC area.
- **Abstention:** abstain when the calibrated probability lies between 0.2 and 0.8. Report coverage and the error rate on the covered part. Compare with random abstention at equal coverage. Owner may change the band by amendment before the run.
- **Bootstrap:** by ISO week (weeks are the resampling unit because hourly issues overlap), 2,000 resamples, seed 7. The number of independent episodes in the scored data is printed beside every score.

## Labels

`useful_signal`: Brier skill above 0 with an interval that excludes 0, and calibration error under 0.1 in the covered bins. Anything else is `no_supported_signal`.

## Limits

One scored episode. The event is a region-hour level, not a warning or health level. Nominal latencies. No operational forecast and no advice.

# M5-C protocol draft: severe-episode prediction 12 to 24 h ahead (not frozen)

Status: DRAFT for review. No code has run. Freeze it only after review. It is separate from `m5-protocol-1`.

## Question (verbatim, M5-C)

Can severe haze episodes be predicted 12-24 hours ahead using only information legitimately available at forecast time, with calibrated uncertainty and appropriate abstention?

## Design

- **Event:** at issue time T, the event is "any region-hour in (T+12 h, T+24 h] has PM2.5 above the elevated threshold" (the same threshold as the Stage P elevated band). Sealed data (from 2024-01-01) is not read.
- **Inputs (issue-time-valid only, enforced by `availability.assert_issue_time_valid`):** NEA lags (newest T-2 h), FIRMS features (pass + 3 h), IMERG Early rain where the data exists (2015 only). ERA5, MCD64A1, HLS and MAIAC are hindsight only and are excluded.
- **Scheme:** Stage T. Train 2015 to 2018, score the held-out 2019 haze season. Stage P blocked folds are used inside 2015 for a second view, with no skill claim.
- **Rungs:** C0 climatology (base rate by month). C1 persistence of the current level. C2 logistic regression on lags. C3 C2 plus FIRMS. C4 trees on C3 inputs, if C3 shows any signal.

## Metrics, fixed before the run

- Brier score and its skill against C0. Reliability table in 10 bins. Area under the ROC curve.
- Calibration by isotonic or Platt fit on the training years only. The calibrated probability is scored on 2019.
- **Abstention:** the system abstains when the calibrated probability lies between 0.2 and 0.8. Report coverage (the share not abstained on) and the error rate on the covered part. Compare with abstention on a random subset of equal coverage.
- Whole-day bootstrap, 2,000 resamples, seed 7. Episodes are the unit of independence: report the number of independent episodes beside every score.

## Labels

`useful_signal` needs Brier skill above 0 with an interval that excludes 0 and calibration within 0.1 in the covered bins. Anything else is `no_supported_signal`. With few episodes (2019 has 17 elevated days), `no_supported_signal` is the expected result. It is a valid finding.

## Limits

The event is region-hour, not a health or warning level. Few independent episodes. Nominal latencies, not measured. No operational forecast and no advice.

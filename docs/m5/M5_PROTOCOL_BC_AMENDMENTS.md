# Amendments to the M5-B and M5-C protocols

The frozen files `M5_PROTOCOL_B_V1.md` and `M5_PROTOCOL_C_V1.md` are not edited. Changes go here, written before the run they affect.

## Amendment C1 (2026-11-04): latency sensitivity and season-flag checks for M5-C

Written after the main-session science review and before any M5-C run.

- **Latency measurement.** IMERG latency was sampled on today's service (`m5_latency_sample.json`): Early 4.1 to 4.6 h produced. The 2015 archive cannot be measured this way.
  FIRMS MODIS_SP is standard processing. The `pass + 3 h` rule is an NRT assumption and is not measured.
- **Sensitivity.** C3 (lags and FIRMS) runs twice: with the FIRMS delay at 3 h and at 24 h. If the Brier skill of C3 depends on the delay, the report says so.
- **Season-flag check.** Fire counts near zero outside haze can act as a season flag. C3 is also run with FIRMS features replaced by their within-season rank (so that the level differences between seasons are removed). A skill that appears only with raw counts is reported as a possible season flag.
- **Training control.** C2 (lags only) is also fitted without 2015 (2016 and 2017 only), to separate the effect of the 2015 haze from the effect of FIRMS.
- No label rule or threshold changes.

## Amendment C2 (2026-11-04): model details for M5-C, written before the run

The frozen text leaves hyperparameters open. They are fixed here, with no tuning on the scored season.

- **Features.** For each lag k of 0 to 23 hours (newest at T-2 h): the maximum and the mean over the five regions (48 columns). C3 adds the nine FIRMS columns of `m5-protocol-1`.
- **Preprocessing.** Training mean fills a missing value. Standardisation uses training statistics.
- **C2 and C3.** L2 logistic regression, C = 1.0, fixed. **C4.** Gradient-boosted trees with the tree settings of `config/m5/protocol-v1.yaml`, run only if C3 beats C0.
- **Inner folds.** Training issues are grouped by (season, ISO week). Weeks are dealt to 5 folds in order. Out-of-fold probabilities fit the Platt map (logistic regression on the logit).
- **C0.** The training base rate (2015 to 2017 pooled).
- **Calibration error.** Mean absolute gap between mean predicted probability and observed frequency over 10 bins, weighted by count, over the covered issues only.
- **Random abstention.** 200 random subsets with the same coverage; the mean error rate is reported.
- **Scored issues.** An issue is scored when at least one hour of its event window is observed.
- **Season-rank diagnostic (Amendment C1).** Within-season ranks use the whole season, so they use later values. This run is a diagnostic only. It is never an issue-time result.

## Amendment C3 (2026-11-04): exploratory abstention bands, written AFTER the first M5-C run

The first M5-C run (`m5_c_v1.json`) used the frozen band 0.2 to 0.8 only. It ran on the owner's direct instruction to go ahead,
before the main-session advice to add other bands reached this session. This amendment is therefore post hoc.

- The primary rule stays the frozen band 0.2 to 0.8. No label uses another band.
- Two secondary rows are added and labelled **exploratory, post hoc**: 0.1 to 0.9 and 0.3 to 0.7. Each gives coverage, error rate, random-abstention error and calibration gap.
- The run is repeated once with these rows. Model, features, folds and seeds are unchanged, so every other number stays the same. The check is that they do.
- The owner decided (relayed by the main session, 2026-11-04): keep 0.2 to 0.8 as the frozen primary rule and add 0.1 to 0.9 and 0.3 to 0.7 as exploratory secondary rows. The two rows carry no label decision.
- The decision reached this session after the first run. The order the owner asked for (amendment before any run) was not kept. The rerun shows that all primary numbers are identical.
- The owner may still change the primary band. That would need a new amendment and a new run.

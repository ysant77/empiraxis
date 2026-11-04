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

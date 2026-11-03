# M5 protocol v1: amendments

The frozen files `config/m5/protocol-v1.yaml` and `docs/m5/M5_PROTOCOL_V1.md` do not change.
This file records what was found after the freeze. Each entry has a date and the reason.

## Amendment 1 (2026-11-03): Experiment A cannot reach `supported_association`

The protocol uses a circular-shift null with a minimum shift of 14 days. A season has 58 scored
days, so the null has 31 shifts. The smallest possible p value is 1 / 32 = 0.031. The Holm
correction over 32 tests (8 exposures, 4 lags) multiplies the smallest p value by 32. The adjusted
value is then 1.0 or close to it. No test can pass the Holm rule at 0.05.

- **Effect:** every Experiment A test is labelled `descriptive_only` by construction. This is a design
  fault of the protocol, not a finding about the data.
- **What is reported:** the frozen labels, and also the raw rank correlations, their block-bootstrap
  intervals and the unadjusted shift-null p values. The report calls any pair that stands out
  "a temporal association, exploratory". It does not call it supported.
- **Fix for a later protocol:** a longer null (stationary bootstrap or phase randomisation), fewer
  pre-declared tests, or several seasons pooled.

## Amendment 2 (2026-11-03): exploratory error breakdown by target band

After the first Stage T results, the summary gained an error breakdown by target band (below 25,
25 to 55, above 55 µg/m³) and a count of elevated days. The main metrics, decision rule and labels
are unchanged. The breakdown is exploratory. Any statement drawn from it needs a new protocol.

# M5 protocol v1: multisource environment study

Status: frozen before any new model is fitted. Constants live in `config/m5/protocol-v1.yaml`.
The freeze record is `docs/m5/protocol-v1.freeze.json`. A test fails if either file changes.

## Question

Can wind, rain, fire, burned-area, aerosol and soil-moisture data improve understanding of the
Singapore haze, and six-hour-ahead regional PM2.5 predictions, beyond PM2.5 history alone?
Improvement is a hypothesis. Equal or worse results are valid findings.

## What was done before the freeze

- The published 2015 ablation was reproduced: 30.76, 32.10, 36.73 and 41.75 µg/m³ (MAE). It is a
  reproduction of an existing record, not a new fit.
- The data pilots for SMAP and HLS were read once, for feasibility. The gate values in this protocol
  were set after that look. They are therefore not independent of it. The reports say so.
- FIRMS files for 2016 to 2019 were downloaded. No PM2.5 statistic of 2016 to 2019 was computed.
- Seasons were chosen from public knowledge: 2015 and 2019 are the major haze years in the period.

## Claims that are never made

- No causal source attribution. Allowed words: "temporal association", "consistent with".
- No forecast claim from hindsight data (ERA5, MCD64A1, archive HLS, MAIAC 061).
- No medical, health, political or war content.
- A fire detection is not a burned area, an emission or proof that smoke reached Singapore.
- AOD is a column quantity. It is not surface PM2.5.

## Data classes

| Source | Class | Time rule at issue time T |
|---|---|---|
| NEA regional PM2.5 | target and lags | newest usable value is T-2 h |
| FIRMS MODIS_SP | issue-time valid by assumption | pass time + 3 h at or before T |
| IMERG Early | issue-time valid by nominal latency | observation end + 4 h at or before T |
| IMERG Late, Final | hindsight for 6 h horizon | not used in Experiment B |
| ERA5 | hindsight | never an issue-time input |
| MCD64A1, archive HLS, MAIAC 061 | hindsight | Experiment A only |
| SMAP L3 | latency about 50 h | not a 6 h input |

Latency values are nominal documentation values, not measured per file. They are in
`src/earthlab/m5/availability.py`.

## Experiment A: retrospective physical association (hindsight allowed)

- **Seasons:** 2015 (haze) and 2016 (comparison). Window: 4 September to 31 October.
- **Outcome:** Singapore daily mean PM2.5 over the five regions. A day needs 80% of its 120
  regional-hour values; otherwise it is missing.
- **Exposures, lags 0 to 3 days:** log(1 + FIRMS detections) in boxes A, B, C and their sum.
  ERA5 850 hPa wind component toward Singapore along the box-to-Singapore bearing. ERA5 daily rain.
- **Statistic:** Spearman rank correlation. The interval comes from 7-day block bootstrap
  (2,000 resamples, seed 7).
- **Null:** circular shift of the exposure series by at least 14 days. P values use Holm
  correction over all exposure and lag pairs.
- **Label `supported_association`:** the 2015 interval excludes 0, the correlation has the expected
  sign, and it is beyond the shift-null 95% range. Otherwise `descriptive_only` or
  `no_incremental_gain`.
- **Out of scope:** these correlations do not name a source. They describe time patterns.

### Data-suitability gates (descriptive layers)

| Layer | Gate | Fail label |
|---|---|---|
| MCD64A1 | valid land share at least 0.80 per month | `insufficient_data` for that month |
| HLS L30 | clear land share at least 0.20 of the box on both dates of a same-path pair, and high-aerosol share at most 0.50 | `HLS_not_eligible` |
| SMAP L3 | at least 50% of retrieved cells have recommended quality, on at least 5 days per window | `SMAP_unsuitable` |
| IMERG | needs owner approval of the GES DISC app | `BLOCKED` |
| MAIAC | reader for HDF4 not built; metadata only | `not_assessed` |

## Experiment B: issue-time-valid T+6 prediction

- **Target:** regional hourly PM2.5, six hours after T, for each of five NEA regions.
- **Issue times:** every hour from 4 September 00:00 to 31 October 17:00 Singapore time, per season.
- **Rungs (each compared only with the one before):**

| Rung | Model | Inputs |
|---|---|---|
| R0 | persistence | newest usable PM2.5 |
| R1 | ridge per region | 24 PM2.5 lags |
| R2 | ridge per region | R1 + 9 FIRMS features (24 h, 72 h counts, 24 h FRP; boxes A, B, C) |
| R3a | tree, pooled with region one-hot | R1 inputs |
| R3 | tree, pooled with region one-hot | R2 inputs |
| H1 | ridge per region (hindsight diagnostic) | R2 + ERA5 features of the 2015 ablation |
| I1 | ridge per region | R2 + IMERG Early rain; runs only if IMERG is unblocked |
| R4 | compact neural model | not run; the gate is in the YAML |

- **Stage P (pilot, per season):** 2015 and 2016 each use four contiguous blocks, expanding origin,
  like the published ablation. Stage P gives no skill claim.
- **Stage T (transfer):** train on 2015 to 2018 seasons. Test on the held-out season 2019.
  The ridge penalty is chosen on the 2018 season using a model trained on 2015 to 2017. The final
  fit uses all four seasons. Scalers use training rows only. Trees use fixed settings, no tuning.
- **Metrics:** MAE on all hours, MAE on hours above 55 µg/m³, bias. Paired skill is
  1 − MAE(new) / MAE(old) on the same rows. The interval is a whole-day bootstrap, 2,000 resamples,
  seed 7. Missing rows, training seconds and inference seconds are reported.
- **Decision (Stage T):** `supported_gain` needs a lower 95% limit above 0 on all hours and a
  non-negative point estimate on elevated hours. A positive all-hours gain with a negative elevated
  estimate is `mixed`. A lower limit below 0 is `no_incremental_gain`. An upper limit below 0 is
  `worse`. Fewer than 200 scored rows is `insufficient_data`.

## Sealed period

NEA labels from 2024-01-01 are sealed by the repository split. The M5 loader sets them to missing
immediately after reading, and a test checks it. No statistic uses them. Opening them needs a new
signed protocol.

## Known limits, stated before the result

- The 2019 season is validation data in the repository split, so earlier M3 work used it.
  No M5 model was fitted on it before this freeze.
- FIRMS standard processing was not real time. The 3 h delay is an assumption.
- The 2015 and 2019 seasons are two haze events. Intervals will be wide.
- NEA does not state whether a label marks the start or the end of the hour.

## Deviations

Any change after the freeze goes into an amendment section with a date. The original text stays.

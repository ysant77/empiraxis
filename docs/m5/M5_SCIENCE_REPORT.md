# M5 science report: multisource environment pilot

Date: 2026-11-03. Protocol: `docs/m5/M5_PROTOCOL_V1.md` (frozen before the first new fit).
Branch: `experiment/m5-multisource-environment`. No Meta model took part. All runs are deterministic code on CPU.

## Summary

- **The published 2015 negative ablation reproduces exactly.** Persistence 30.76, ridge 32.10, ERA5 36.73,
  ERA5 + FIRMS 41.75 µg/m³ (MAE).
- **No issue-time-valid addition gave a supported gain.** FIRMS features did not beat PM2.5 history on all
  hours in any scored season. Trees did not beat ridge.
- **One exploratory signal.** On the 2019 held-out haze season, FIRMS features lowered the error on
  elevated hours (above 55 µg/m³) by about 39%, while they raised the all-hours error by about 13%.
  This is not a supported gain under the frozen rule. It needs its own protocol.
- **Three of the new data layers are not fit for the model.** SMAP has no recommended-quality retrieval over
  the Kalimantan box. HLS has 2.7% clear land on both dates, with high aerosol on more than 96% of pixels.
  IMERG was blocked by an account permission until the owner fixed it; the pilot now ran on four days.
- **Real data now flows through typed contracts.** Receipts carry SHA-256, caps and authority. Tests cover
  issue-time rules, units, masks, wind vectors, and the sealed period.

## Status of the work

| Item | State |
|---|---|
| Phase 0 audit and status matrix | done |
| Coverage inventory 2015 to 2026 | done (catalogue counts; NEA open years) |
| Protocol v1 frozen, hash-checked | done |
| 2015 baseline reproduction | done |
| Experiment B, Stage P (2015, 2016) and Stage T (train 2015 to 2018, score 2019) | done for R0 to R3 |
| M5-C, held-out 2019 | done (section 2c); one episode; label fragile |
| Experiment B, rung H1 (ERA5, hindsight), Stage P 2015 and 2016 | done (Amendment 5); no gain (section 2b) |
| Experiment B, rung I1 (IMERG Early), Stage P 2015 | done; no gain (see section 2a) |
| Experiment B, rung R4 (neural) | not run; the gate in the protocol was not met |
| Experiment A, FIRMS and ERA5 exposures 2015 and 2016 | done |
| SMAP, HLS pilots | done as feasibility and QA |
| IMERG pilot and Early season | pilot on four days of Final and one of Early; then 2,976 Early granules (31 Aug to 31 Oct 2015, 22.8 GB, owner approved) reduced to corridor means; raw files deleted; receipts in `docs/m5/receipts/` |
| Evidence package for the M4 council | done: `docs/m5/evidence/scientific_evidence_package_v1.json` (hash-checked; see section 9) |
| MAIAC | not assessed (no HDF4 reader) |
| Layer catalogue and readers (Phase 5, data side) | done; no viewer was built |

## 1. Reproduction of the 2015 ablation

The ablation code, run on the local `runs/haze-2015` folder, gave MAE, elevated MAE, paired skills,
row counts and penalties equal to `docs/evidence/haze-2015-ablation.json` (exact float equality).
The new ladder code also gives R0 = 30.76 and R1 = 32.10 on the same season, so the new code path matches.

## 2. Experiment B: issue-time-valid T+6 prediction

Inputs allowed at issue time: NEA lags (newest T-2 h) and FIRMS (pass + 3 h). ERA5 is excluded
because it is hindsight data. Rungs: R0 persistence; R1 ridge on 24 lags; R2 R1 + 9 FIRMS features;
R3a trees on R1 inputs; R3 trees on R2 inputs. Settings are in `config/m5/protocol-v1.yaml`.

### Stage P: blocked scheme inside one season (no skill claim)

| Season | Rows | Elevated rows | R0 | R1 | R2 | R3a | R3 |
|---|---|---|---|---|---|---|---|
| 2015 (haze) | 5,195 | 2,710 | 30.76 | 32.10 | 34.11 | 35.49 | 38.21 |
| 2016 (clean) | 5,195 | 14 | 8.62 | 7.10 | 7.39 | 7.21 | 7.88 |

MAE in µg/m³. Paired skill (95% interval, whole-day bootstrap):

| Comparison | 2015 | 2016 |
|---|---|---|
| R1 vs R0 | −0.043 (−0.211, 0.085) | +0.177 (0.123, 0.227) |
| R2 vs R1 | −0.063 (−0.103, −0.027) | −0.041 (−0.071, −0.017) |
| R3a vs R1 | −0.106 (−0.188, −0.025) | −0.016 (−0.042, 0.012) |
| R3 vs R2 | −0.120 (−0.215, −0.022) | −0.067 (−0.118, −0.018) |

In the clean season, ridge beats persistence. In the haze season, it does not. FIRMS features make both worse.
The 2016 season has 14 elevated hours (7 days). Its elevated results carry no weight.

### Stage T: train 2015 to 2018, score the held-out 2019 haze season

6,930 scored region-hours, 58 days, 588 elevated hours on 17 days.

| Rung | MAE all | Bias | MAE elevated | Fit seconds |
|---|---|---|---|---|
| R0 persistence | 11.33 | −0.09 | 27.63 | – |
| R1 ridge, lags | 9.87 | +0.38 | 28.16 | 0.12 |
| R2 ridge, lags + FIRMS | 11.21 | +6.11 | 17.27 | 0.24 |
| R3a trees, lags | 10.21 | +0.91 | 23.76 | 1.03 |
| R3 trees, lags + FIRMS | 15.04 | +9.35 | 19.97 | 0.91 |

| Comparison | All hours: skill (interval) | Elevated: skill (interval) | Frozen label |
|---|---|---|---|
| R1 vs R0 | +0.128 (0.088, 0.168) | −0.019 (−0.072, 0.055) | mixed |
| R2 vs R1 | −0.135 (−0.255, −0.039) | +0.387 (0.317, 0.488) | worse |
| R3a vs R1 | −0.034 (−0.094, 0.024) | +0.157 (0.075, 0.235) | no_incremental_gain |
| R3 vs R2 | −0.342 (−0.523, −0.185) | −0.156 (−0.454, 0.005) | worse |
| R3 vs R3a | −0.473 (−0.766, −0.257) | +0.159 (−0.066, 0.363) | worse |

**Reading.**

- Ridge on PM2.5 lags beat persistence on all hours (about 13%) in the held-out season. It did not beat it on elevated hours.
  The label is `mixed` by the frozen rule.
- FIRMS features raised the bias by 6 µg/m³ and hurt the normal hours. They cut the elevated-hour error from 28.2 to 17.3.
  The rule gives `worse`, because the all-hours interval is below zero.
- Trees on lags only also lowered the elevated-hour error (28.2 to 23.8). So part of the elevated-hour gain may come from
  training on the 2015 haze season, not from the FIRMS data. This test cannot separate the two causes.
- Exploratory error by target band (not in the protocol, Amendment 2): for R2, the error rose from 7.2 to 9.7 below 25 µg/m³
  and from 9.7 to 12.1 between 25 and 55. It fell from 28.2 to 17.3 above 55.
- The elevated result rests on 17 days of one season. A new protocol with more haze seasons is needed before any claim.

### 2a. Rung I1: IMERG Early rain, 2015, Stage P (Amendment 4)

IMERG Early rain (6 h and 24 h sums per corridor, issue-time latency 4 h) was added to the ridge model.
Result file: `docs/m5/results/m5_i1_stage_p_2015.json`. 5,195 scored rows.

| Rung | MAE (ug/m3) |
|---|---|
| R0 persistence | 30.76 |
| R1 ridge, lags | 32.10 |
| R2 ridge + FIRMS | 34.11 |
| I1 ridge + FIRMS + IMERG Early | 36.11 |

Paired skill, whole-day bootstrap (2,000 resamples). Negative means the first rung is worse.

| Pair | Skill | 95% interval |
|---|---|---|
| R1 vs R0 | -0.043 | -0.211 to 0.085 |
| R2 vs R1 | -0.063 | -0.103 to -0.027 |
| I1 vs R2 | -0.059 | -0.131 to -0.005 |
| I1 vs R1 | -0.125 | -0.220 to -0.051 |

Finding: in this scheme IMERG Early rain did not improve T+6 prediction. It made the ridge model worse, and the interval excludes zero.
Stage P makes no skill claim, and this is one season and one model class. Do not read it as "rain does not matter".
It says only that these rain sums, added to a 24-lag ridge, gave no gain. This result is separate from the 2015 negative ablation (30.76, 32.10, 36.73, 41.75) and from M3 numbers.
R0 and R1 equal the reproduced baseline values.

Latency check (`scripts/m5_latency_sample.py`, `docs/m5/results/m5_latency_sample.json`): the latest 40 IMERG Early granules of today's
service were produced 4.1 to 4.6 h after their end (median 4.3 h) and inserted 4.4 to 5.0 h after (median 4.7 h). Late: 14.2 to 14.7 h produced.
So the 4 h rule is slightly early. Rung I1 re-run with 5 h (`m5_i1_stage_p_2015_latency5h.json`): I1 MAE 35.94 against 34.11 for R2.
The result is unchanged. This sample is the current service, not the 2015 archive. The I1 result covers the 2015 season only; it does not generalise.

### 2b. Rung H1: ERA5 hindsight diagnostic, Stage P (Amendment 5)

ERA5 (10 m and 850 hPa wind, 10 m rain; 30 columns) added to the R2 ridge. Hindsight only: never an issue-time claim.
Result file: `docs/m5/results/m5_h1_stage_p.json`. 5,195 scored rows per season.

| Season | R0 | R1 | R2 | H1 |
|---|---|---|---|---|
| 2015 (haze) | 30.76 | 32.10 | 34.11 | 41.75 |
| 2016 (clean) | 8.62 | 7.10 | 7.39 | 7.57 |

| Pair | 2015 skill (95% interval) | 2016 skill (95% interval) |
|---|---|---|
| H1 vs R2 | -0.224 (-0.366, -0.102) | -0.024 (-0.092, 0.039) |
| H1 vs R1 | -0.301 (-0.459, -0.167) | -0.066 (-0.137, -0.005) |

Finding: ERA5 made the ridge worse in the haze season, and did not help in the clean season. The 2015 H1 value of 41.75 equals the
published 2015 ablation figure for ERA5 plus FIRMS, so the new code agrees with the release code. This is one model class
with 24 lags plus 39 extra columns; overfitting is a likely reason, and it was not tested. No skill claim.

### 2c. M5-C: event 12 to 24 h ahead, held-out 2019 (`m5-protocol-c-1`)

Fit on 2015 to 2017, Platt calibration on out-of-fold blocked predictions, score on 2019. Event: any region above 55 ug/m3 in (T+12 h, T+24 h].
Result file: `docs/m5/results/m5_c_v1.json`. 1,386 scored issues, 349 events, **one episode**. Training base rate 0.338.
Brier skill is against the constant training base rate (C0, Brier 0.196). Interval: bootstrap by ISO week.

| Rung | Brier | Skill | 95% interval | ROC area | Coverage / error (abstain in 0.2 to 0.8) | Calibration gap | Frozen label |
|---|---|---|---|---|---|---|---|
| C1 persistence 0/1 | 0.168 | 0.142 | -0.179 to 0.753 | 0.699 | 1.00 / 0.168 | not assessed | no_supported_signal |
| C2 lags | 0.113 | 0.425 | 0.286 to 0.648 | 0.903 | 0.60 / 0.046 | 0.105 | no_supported_signal |
| C3 lags + FIRMS | 0.103 | 0.474 | 0.267 to 0.643 | 0.915 | 0.58 / 0.047 | 0.093 | useful_signal |
| C4 trees (gate met) | 0.114 | 0.419 | -0.056 to 0.733 | 0.941 | 0.65 / 0.064 | 0.087 | not labelled (interval includes 0) |

Exploratory bands, added AFTER the primary run (Amendment C3, post hoc, outside the label decision and the headline; file `m5_c_v1_post_hoc_bands.json`), coverage / error / calibration gap:

| Rung | 0.1 to 0.9 | 0.3 to 0.7 |
|---|---|---|
| C2 | 0.20 / 0.062 / 0.103 | 0.80 / 0.091 / 0.083 |
| C3 | 0.17 / 0.063 / 0.067 | 0.78 / 0.060 / 0.107 |

The band choice moves the calibration gap across the 0.1 limit for both rungs. This is a second reason the C3 label is fragile.

Random abstention at equal coverage has an error of about 0.13 to 0.15, so the abstention band selects easier issues, as intended.

How far to trust it (Amendment C1 checks, same 2019 data):

- **The label is fragile.** C3 passes the frozen rule by a small margin (gap 0.093 against the limit 0.1). With FIRMS delayed by 24 h the gap is 0.128 and the label becomes
  `no_supported_signal` (skill 0.469, interval 0.056 to 0.747). With within-season FIRMS ranks (hindsight diagnostic) the gap is 0.101 and the label also fails.
- **Most of the skill comes from the PM2.5 lags.** C2 alone has skill 0.425. FIRMS adds 0.05 at most, and a paired test of C3 against C2 was not pre-registered, so it is not claimed.
  Haze persists, so a lag-based model predicts "haze tomorrow" well. This is not the same as skill at the start of an episode.
- **The 2015 haze does not explain it.** Lags only, fitted on 2016 and 2017 without 2015: skill 0.465 (interval 0.205 to 0.518), label `useful_signal`. FIRMS in that setting is worse (0.379).
- **Calibration is imperfect.** Low probabilities are too high: the 0.14 bin has an observed rate of 0.03. The reliability table is in the result file.
- **One scored episode.** All 349 events come from one connected haze period in 2019. The week bootstrap cannot show variation between episodes. The result is not evidence of skill on a new episode.
- IMERG was not used (2015 only). The latency rules are nominal (see the latency note in section 2a).

Headline: the skill comes from the PM2.5 lags. A FIRMS increment is not supported. The week-bootstrap intervals reflect variation between weeks inside one episode, not between independent episodes.

Reading: for this one held-out episode, a lag-based model with Platt calibration and abstention predicts the event much better than the training base rate and better than 0/1 persistence.
FIRMS adds little. The frozen rule gives `useful_signal` for C3 but the label does not survive two sensitivity checks. Claim no operational forecast.

## 3. Experiment A: retrospective association (hindsight allowed)

Daily Singapore mean PM2.5 against lagged FIRMS counts (boxes A, B, C and sum), ERA5 850 hPa wind component toward
Singapore, and ERA5 rain. 58 scored days per season. Both seasons have 32 tests (ERA5 2016 arrived later; extracts built with `scripts/m5_era5_extract.py`).

- **Frozen result:** no test is `supported_association`. This is by construction: the shift null has 31 shifts,
  so the smallest p value is 0.031, and the Holm correction over 32 tests cannot go below 1.0.
  See `docs/m5/M5_PROTOCOL_V1_AMENDMENTS.md`, Amendment 1.
- **Exploratory view, unadjusted:** in 2015, three pairs reach the smallest attainable shift-null p value (0.031).
  They are all about source box B (Jambi and South Sumatra): FIRMS detections at lag 1 (rho 0.38, interval −0.01 to 0.54),
  and the 850 hPa transport component at lag 1 (0.37, 0.01 to 0.52) and lag 2 (0.40, 0.08 to 0.53).
  These are temporal associations, consistent with a Sumatra-to-Singapore pathway. They are not source attribution.
- **2016 (clean year, with ERA5):** all 32 tests are descriptive only. The smallest shift-null p value is 0.0625: the 850 hPa component from box A at lag 0 (rho −0.38, interval −0.61 to 0.03). The strongest FIRMS pair is box C at lag 0 (−0.33, p 0.094), with a negative sign. Fire counts were low. ERA5 rain has no pair below p 0.25. The 2015 box B pattern does not repeat in 2016.

## 4. Data suitability

| Layer | Result | Evidence |
|---|---|---|
| MCD64A1 | Sep 2015 valid land 0.970 (pass). Oct 0.460 (fail, `insufficient_data`). | existing burned-area report |
| HLS L30 | `HLS_not_eligible`. Tile T50MKB, pair 13 Sep and 15 Oct 2015: 2.7% of box pixels are clear land on both dates. High-aerosol flag on 99.8% (13 Sep) and 96.4% (15 Oct) of pixels. | `docs/m5/qa/hls_qa.json` |
| HLS vs MCD64A1 | Descriptive only. On the 2.7% overlap, dNBR separates mapped-burned from control cells with AUC 0.85 (439 burned and 1,308 control valid pixels). MCD64A1 is not ground truth. High aerosol means the surface reflectance is less certain. | same |
| SMAP L3 36 km | `SMAP_unsuitable`. Kalimantan box: 78 retrieved cell-passes, 0 with recommended quality. Cells show vegetation water content 9.6 to 17.3 kg/m² and evergreen broadleaf land cover. Maritime continent: 116 of 6,392 retrieved cells recommended (1.8%). Sumatra box B: 19 of 293 (6.5%). | `docs/m5/qa/smap_qa.json` |
| IMERG V07 | Unblocked after the owner authorised the GES DISC app. Reader checked on real files. Final run for 19, 27, 30 and 31 Oct 2015 and Early run for 30 Oct (about 1.9 GB, 240 granules). 19 Oct was dry, so it is uninformative. | `docs/m5/qa/rain_compare_final.json`, `rain_compare_early.json` |
| ERA5 vs IMERG hourly rain | Three wet days (27, 30, 31 Oct), 71 paired hours per corridor. Mean rain is similar (0.51 vs 0.46, 0.39 vs 0.37, 0.52 vs 0.40 mm/h for boxes A, B, C). Rank correlation: A 0.48, B 0.30, C −0.41. A shift of ERA5 by 1 to 2 hours earlier raises A to 0.56. No single shift fixes C. The two estimates are related for A and B, and disagree in timing and pattern for C. This is three days, not a validation. | same |
| MAIAC | not assessed | status doc |

The HLS tile covers only part of the box. One Landsat scene date covers a path strip. The 13 September scene of tile T49MHS has
0.2% non-fill pixels in the box. A full-box pre/post pair needs scenes from more than one date and path, and clear skies. October 2015
scenes are 80 to 100% cloudy by the provider's own value.

## 5. Limits

- Two haze seasons (2015 and 2019). Intervals are wide and clustered by day.
- The 2019 season is validation data in the repository split. Earlier M3 work used it for other models.
  No M5 model was fitted on it.
- FIRMS standard processing was not real time. The 3 h delay is an assumption. IMERG latency values are nominal.
- Missing PM2.5 lags are filled with the training mean after scaling in ridge. Trees read the gaps as missing.
- The protocol's Experiment A cannot reach `supported_association` (Amendment 1).
- Thresholds for the HLS and SMAP gates were set after one look at the pilot data. They are not independent of it.
- **Deviation (M5-C).** The owner asked for the 0.1 to 0.9 and 0.3 to 0.7 abstention rows by amendment before any M5-C run. The primary run (`a7a3c14`) happened first,
  on the owner's direct go-ahead, before that decision reached this session. The rows were added afterwards as post-hoc exploratory rows (Amendment C3 and its correction). The primary result is unchanged. An earlier commit (`81883e9`) wrongly wrote the rows into the primary result file. The next commit removes them.
- M5-C holds one scored episode (2019). Week-bootstrap intervals reflect weeks, not independent episodes.
- No sealed data (NEA from 2024-01-01) was used. The loader sets those hours to missing, and a test checks it.

## 6. What is not known

- Whether IMERG Early rain adds issue-time information in other seasons. Rung I1 ran on 2015 only (Stage P). Other seasons were not downloaded.
- Whether ERA5 helps a model other than a 24-lag ridge. H1 used one model class.
- Whether the elevated-hour effect of FIRMS features repeats. One season shows it. A new protocol must test it with more haze seasons.
- Whether HLS and MCD64A1 agree over the full box. Clear scenes cover too little of it.

## 7. Cost

All fits ran on CPU in under two seconds each. Each stage run took about two minutes of wall time, with at most four threads.
No GPU, no MPS and no model server was used. Downloads: about 25 GB (IMERG 22.8 GB Early season plus 1.9 GB pilot, SMAP 249 MB, HLS 110 MB, FIRMS and ERA5 small).

## 8. Reproduce

```bash
uv sync --all-extras
uv run python scripts/m5_coverage_inventory.py       # CMR catalogue, no data
uv run python scripts/m5_run_ladder.py <DATA_ROOT> <runs/haze-2015> p
uv run python scripts/m5_run_ladder.py <DATA_ROOT> <runs/haze-2015> t
uv run python scripts/m5_run_assoc.py <DATA_ROOT> <runs/haze-2015>
```

Raw data sits in `<DATA_ROOT>` outside Git. Receipts with SHA-256 are in `docs/m5/receipts/`.

## 9. Evidence package for M4 (ScientificEvidencePackageV1)

`scripts/m5_build_evidence.py` writes `docs/m5/evidence/scientific_evidence_package_v1.json` from committed artifacts only.
It holds the three registered questions (M5-A primary), the AOI and source boxes, the frozen-protocol hashes,
the availability rule per source, 3,256 asset hashes from the receipts, the QA verdict per modality, the feature contracts,
the baseline and I1 MAE values read from result files, the limitations and the claims M5 does not make.
Every feature and source carries `issue_time_valid` or `retrospective_only`. The package carries its own SHA-256, and a test rebuilds it.
It holds no raw data. M4 reads it and critiques it. M4 does not replace the numerical runs or the owner's approval.
Rebuild it after any change to the result files or this report; the test fails if it is stale.


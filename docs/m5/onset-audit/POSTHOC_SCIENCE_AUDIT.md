# M5 post-hoc science audit (one page)

Status: post hoc and exploratory. Date: 2026-11-04. Base: main `35de956` (PR 118 merged).
Frozen results, protocols and the evidence package are unchanged. Nothing here is in `docs/m5/results/`.

## 1. Onset versus continuation (M5-C, 2019)

Full text: `POSTHOC_ONSET_AUDIT.md`. Result file: `m5_c_onset_audit.json` (audit 2).

- **Saved predictions: NO.** M5-C wrote aggregates only. No state-split skill was computed. No model was fit.
- 279 of 349 events (80%) follow an exceedance already inside the 24 lag hours. The event rate is
  0.667 for ongoing issues (418) and 0.072 for onset-eligible issues (968).
- **Independent onsets: 4** at the primary setting. Across 24 tested settings the count is 1 to 5.
  The threshold of 10 was declared before the computation. Verdict: **insufficient independent onsets**.
- Two of the four onsets are single-hour exceedances. The 20 Sep episode counts as a continuation.
- The M5-C week bootstrap covers 9 weeks of one episode. It does not estimate skill across episodes.
- Reading: the M5-C skill is consistent with persistence of a running episode. The data cannot show
  whether M5-C predicts the start of new episodes. No lead-time claim.

## 2. M5-B readiness (local disk, checked 2026-11-04)

M5-B needs the ERA5 850 hPa wind (pressure-level files) for 2017, 2018 and 2019.

| Season | Pressure-level files (needed) | Single-level files (not needed by M5-B) |
|---|---|---|
| 2015 | present (`runs/haze-2015`) | present |
| 2016 | present (Sep, Oct) | present |
| 2017 | **missing** (09, 10) | present (09, 10) |
| 2018 | **missing** (09, 10) | missing; 09 queued at CDS |
| 2019 | **missing** (09, 10) | missing; 09 queued at CDS |

- M5-B is **not runnable**. No M5-B result exists. The six pressure-level requests were rejected by
  the CDS server ("maximum number of queued requests for this dataset"). No new downloads were started
  by this audit. One collector still waits for the two queued 2018 and 2019 single-level files.
- FIRMS 2015 to 2019 is present. The extract builder needs a change to skip the unused 10 m extract.

## 3. Release review

- **Evidence package.** `m5-evidence-4`, SHA-256 `bd8cf0bd...58be881`. A fresh build equals the committed file.
  `verify()` passes. 3,256 assets, 11 artifacts. Tests pass (evidence, strict JSON, protocol freeze).
- **Primary M5-C result** `m5_c_v1.json`: SHA-256 `7ec0a05e...`, byte-identical, 9 `NaN` tokens kept.
  The strict export `m5_c_v1.strict_v1.json` records that digest and lists the 9 missing values.
- **Receipts.** The 16 raw files in `season_*.json` receipts that exist locally (ERA5 2016, FIRMS 2016 to 2019)
  were re-hashed. 16 match, 0 differ. Files that no longer exist (IMERG, HLS, SMAP raw) were not re-checked.
- **FIRMS issue-time class. Finding.** The package marks `fire_count_box_{a,b,c}` and the IMERG rain
  features as `issue_time_valid`. The data is the FIRMS standard-processing archive (`MODIS_SP`), not an
  observed publication time. The 3 h delay is an assumption. A live feed would be the near-real-time
  product, which is a different product and may differ in detections. This audit did not compare them.
  The protocol text says "by assumption" and "by nominal latency", but the package field does not.
  Evidence on the effect: with FIRMS delayed by 24 h the C3 label fails (report section 2c).
- **Recommendation.** Issue a new package version with a third class, for example `nominal_latency_assumed`,
  and change the two report headings that say "issue-time-valid". The current schema allows only two
  classes. M5 sources were read-only for this audit, so no change was made.

## 4. Limits

Post hoc. 2019 only, one episode. Merge and coverage rules are choices of this audit. Observations only.
No causal attribution, no operational forecast, no health advice.

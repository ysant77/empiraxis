# Science data audit: 2015 haze, H0 and H1

Audit date: 2026-11-01. Code base: commit `0816d46`. Base-rate code: branch
`feat/haze-base-rate`, commit `1f99d47`, read with `git show` and not merged.

This audit read the local files. Where a planning note and a file disagree, the file decides.
The audit made no download, no paid call and no model inference. It read no held-out question.
It changed no code and no data.

## 1. Result

- H0 is functional and reproduced. It describes observations only.
- H1 is functional and reproduced. It gives transport plausibility only.
- The H1 result has low specificity. The wind and rain check passes often in clean hours.
- No data in this audit supports attribution, causation or prediction.
- ERA5 and the three regional FIRMS boxes exist locally, and every hash matches. They are in the
  gitignored folder `runs/haze-2015/`, not in the repository. A clean clone cannot run H1.

### Words used in this audit

| Word | Meaning here |
|---|---|
| Functional | The command runs on the pinned files at `0816d46` and gives its report. |
| Reproduced | A new run of the same code on the same files gave byte-equal or digest-equal output. Reproduction shows that the arithmetic is stable. It does not validate the science. |
| Independently verified | A separate method, or a separate code path, gave the same value. Section 9 limits what this word means. |
| Missing | The data or the method does not exist locally. |
| Scientifically unsupported | The available evidence cannot carry the claim. |

## 2. Status of H0, H1 and related outputs

| Output | Functional | Independently verified | Missing | Scientifically unsupported |
|---|---|---|---|---|
| H0, `earthlab haze-h0` | Yes. `h0.json` digest `a3b4be0c...` reproduced. 38 event periods, 844 event hours. | Yes for the arithmetic. A separate stdlib parser gave the same regional means and maxima, 593 clean hours, and 160 hours above 150 ug/m3. | The NEA hour-label convention. Station-level values. The method that NEA uses to make a regional value. | Any source statement. PSI or AQI values. Any statement about a point location. |
| ERA5 extract, `earthlab haze-era5-extract` | Yes. Both extract files reproduced byte for byte. | Yes for the arithmetic. A separate corridor mean over decoded fields matched: maximum difference 3e-6 m/s (wind) and 3e-7 mm (rain). | Boundary layer height is downloaded but is not extracted. | Smoke height. Any concentration. |
| H1, `earthlab haze-h1` | Yes. Digests `8f5786b0...` (10 m) and `2c2c9f97...` (850 hPa) reproduced. | Yes for the statuses. A separate stdlib recomputation agreed on 246 of 246 box statuses. It used the same extract, so it checks the code only. | A usable control group. Three control labels exist. One box status is decided. | Attribution. Causation. A claim that a pass is evidence for a specific box. |
| Base rate, branch `feat/haze-base-rate` | Yes on that branch. Not in `0816d46`. | No. A rerun of the branch code on the extracts gave the same values as `h1_base_rate.json`. This is reproduction. The H1 recheck covers only the 246 onset statuses. | Provenance. The report has no source hashes, and no evidence class. | Any significance statement. The hours are autocorrelated. |
| PM2.5-only fallback | Yes as code. Not needed for this case, because ERA5 exists. | Not run in this audit. | Not applicable. | Any wind statement. The report states that wind is not checked. |
| Burned area, `earthlab burned-area` | Yes. September 77,426.0 ha, reportable. October 46,118.0 ha, `insufficient_data`. | Partly. Tool and verifier agree, and both agree with the Earth Engine reference within the allowed difference. All three read the same product. | Source-box MCD64A1. The approval for it does not exist. | Tree loss, forest loss or emissions. Use as an H1 input. |

H0 and H1 are command-line tools. No agent tool calls them, and no workflow calls them. The
tools folder holds only `pm25_tools.py` and `burned_area_tools.py`. The UI shows wind-linked haze
as disabled, which is correct.

## 3. Dataset inventory and hash check

Every file was hashed with `shasum -a 256` and compared with its manifest. `earthlab haze-verify`
also passed for all five run-folder manifests, including the byte caps.

| Dataset | File | Location | Bytes | Rows or messages | SHA-256 starts | Match |
|---|---|---|---|---|---|---|
| NEA PM2.5 | `Historical1hrPM2.5.csv` | `data/nea/` | 3,150,004 | 109,584 rows | `2fb76e1c` | Yes |
| FIRMS AOI | `firms_modis_sp_2015_09_2015_11.csv` | `data/kalimantan-2015/` | 807,287 | 10,257 rows | `75bf1fbc` | Yes |
| MCD64A1 | `mcd64a1_2015_09.tif` | `data/kalimantan-2015/` | 88,070 | 5 bands | `126a6c50` | Yes |
| MCD64A1 | `mcd64a1_2015_10.tif` | `data/kalimantan-2015/` | 60,592 | 5 bands | `daf55465` | Yes |
| ERA5 single levels | `era5_sl_2015_09.grib` | `runs/haze-2015/era5/` | 22,273,920 | 2,880 messages | `125a6820` | Yes |
| ERA5 single levels | `era5_sl_2015_10.grib` | `runs/haze-2015/era5/` | 23,016,384 | 2,976 messages | `7702d9d3` | Yes |
| ERA5 850 hPa | `era5_pl_2015_09.grib` | `runs/haze-2015/era5/` | 11,136,960 | 1,440 messages | `6ffd4adb` | Yes |
| ERA5 850 hPa | `era5_pl_2015_10.grib` | `runs/haze-2015/era5/` | 11,508,192 | 1,488 messages | `ee5f98ab` | Yes |
| FIRMS box A | `firms_modis_sp_2015_08_2015_11.csv` | `runs/haze-2015/firms/box-a/` | 382,624 | 4,902 rows | `22daf432` | Yes |
| FIRMS box B | same file name | `runs/haze-2015/firms/box-b/` | 2,967,064 | 37,544 rows | `acdb8455` | Yes |
| FIRMS box C | same file name | `runs/haze-2015/firms/box-c/` | 3,276,146 | 41,778 rows | `ae040d7c` | Yes |

The derived files `h0.json`, `h1.json`, `extract_10m.json` and `extract_850hpa.json` have no
manifest. The audit checked them by reproduction.

### 3.1 Dataset properties

| Property | NEA PM2.5 | ERA5 10 m wind | ERA5 850 hPa wind | ERA5 rain | ERA5 boundary layer height | FIRMS boxes A, B, C | FIRMS AOI | MCD64A1 |
|---|---|---|---|---|---|---|---|---|
| Variable | Regional 1-hour PM2.5 | `10u`, `10v` | `u`, `v` | `tp` | `blh` | Thermal anomaly: location, confidence, FRP | Same | Burn date, uncertainty, QA, first day, last day |
| Unit | ug/m3, integers in the 2015 window | m/s | m/s | m per hour, stored as mm | m | Detection; MW for FRP | Same | Day of year; QA bits |
| Time role | Observation | Reanalysis, `type=an` | Reanalysis, `type=an` | Short forecast, `type=fc` | Reanalysis, `type=an` | Observation at overpass | Same | Monthly mapped product |
| Time support | One hour. Label start or end is not stated. | Instantaneous | Instantaneous | Hour ending at the valid time | Instantaneous | Overpass, UTC | Same | Calendar month |
| Period | 2014-04-01 01:00 to 2026-10-01 00:00 SGT | 2015-09-01 00Z to 2015-10-31 23Z, 1,464 hours | Same | Same | Same | 2015-08-25 to 2015-10-31 (box C rows end 10-30) | 2015-09-01 to 2015-10-30 | 2015-09 and 2015-10 |
| Spatial support | Five regions, no coordinates | 0.25 degree, 93 x 41 cells, 95-118 E, 6 S-4 N | Same | Same | Same | Detection pixels | 1 degree x 1.2 degree box | 463 m sinusoidal, 289 x 267 cells |
| Interpolation | None. No gap filling. | No grid or time interpolation in the repository. Corridor mean is an unweighted mean of cell centres. | Same | Same | Not used | None | None | None. Pixel centre in box. |
| Lag | H1 windows of 12, 24, 36, 48 and 72 h | Same windows | Same windows | Same windows | Not used | One 72 h count for all lags | Not used in H1 | Not used in H1 |
| Mask | None. Non-numeric or negative values become missing. None occur. | No land-sea mask. 0 missing values. | Same | Same | 0 missing values | Confidence >= 30 in H1. No `type` filter. No day or night filter. | Burned-area work does not use it | QA bits. -1 and -32768 keep their documented meanings. |

The H1 corridor is a rectangle from the box centre to the receptor, with a 0.25 degree pad.

| Box | Name in code | Corridor cells | Bearing | Distance | Sector | Lag at 5 m/s |
|---|---|---|---|---|---|---|
| A | Riau / central Sumatra | 7 x 11 | 242.0 | 260.6 km | 197.0-287.0 | 14.5 h |
| B | Jambi / South Sumatra | 19 x 5 | 170.6 | 462.1 km | 125.6-215.6 | 25.7 h |
| C | Central / West Kalimantan | 13 x 34 | 108.1 | 927.9 km | 63.1-153.1 | 51.5 h |

GRIB metadata confirms the manifests: edition 1, class `ea`, stream `oper`, expver `0001`, grid
`regular_ll`, no bitmap. `tp` has base time 18Z of the previous day and step `5-6` for the 00Z
valid hour. The valid time is the end of the accumulation hour, as `grib.py` states.

### 3.2 NEA file

- 109,584 rows equal the 109,584 hours in the coverage period. The file has one row per hour.
- The loader gives 109,580 distinct labels, four conflicting duplicates and four missing labels.
- By row position, all four duplicates are mislabelled rows. The four missing hours are those rows.
  NEA has not confirmed this. The inference comes from the row order only.

| File line | Printed label | Label by position | Effect in the loader |
|---|---|---|---|
| 16957 | `7/3/2016 0:00` | 2016-03-07 12:00 | Row dropped. 12:00 looks missing. |
| 17617 | `2016-04-04 010:00:00` | 2016-04-04 00:00 | Row kept as 10:00. The real 10:00 row is dropped. 00:00 looks missing. |
| 35641 | `24/4/2018 0:00` | 2018-04-25 00:00 | Row dropped. 2018-04-25 00:00 looks missing. |
| 38356 | `16/8/2018 2:00` | 2018-08-16 03:00 | Row dropped. 03:00 looks missing. |

None of these rows is in the 2015 window, so H0 and H1 do not change. Any multi-year work must
handle them. See the forecast protocol.

The September-October 2015 window has 1,464 of 1,464 hours in all five regions.

### 3.3 FIRMS: the AOI file and the regional boxes are separate assets

| Property | AOI, `data/kalimantan-2015/` | Box A | Box B | Box C |
|---|---|---|---|---|
| Purpose | Burned-area case context | H1 | H1 | H1 |
| In the repository | Yes | No | No | No |
| Extent | 113.8-114.8 E, 3.2-2.0 S | 100-103.5 E, 1.5 S-2 N | 102.5-106.5 E, 4.5-1 S | 108.5-115 E, 3.5 S-1 N |
| Rows | 10,257 | 4,902 | 37,544 | 41,778 |
| Rows, 1 Sep to 31 Oct | 10,257 | 3,895 | 34,925 | 38,988 |
| Terra / Aqua | 5,105 / 5,152 | 2,125 / 2,777 | 17,095 / 20,449 | 17,354 / 24,424 |
| Confidence >= 30 | 9,214 | 4,591 | 34,700 | 38,377 |
| `type` 0 / 1 / 2 / 3 | 9,985 / 0 / 272 / 0 | 4,741 / 0 / 161 / 0 | 24,314 / 1 / 13,225 / 4 | 39,493 / 0 / 2,282 / 3 |
| Day / night | 2,985 / 7,272 | 2,672 / 2,230 | 16,585 / 20,959 | 20,988 / 20,790 |

Checks and results:

- All rows are inside their manifest boxes. No file has exact duplicate rows.
- **The AOI file is a subset of box C.** All 10,257 AOI rows are in box C, and box C has no other
  rows in that box and period. This shows that the two downloads agree. It is not independent
  confirmation, because both are the same product.
- Boxes A and B overlap. 342 detections are in both files. H1 counts them in both boxes.
- Every row has `version` 6.03. The manifests say Collection 6.1. The audit did not confirm this
  mapping from a local source.
- **`type` matters in box B.** At confidence >= 30, type 2 ("other static land source") is 35.4% of
  box B detections and 60.5% of box B FRP. The values for box A are 3.2% and 7.0%. The values for
  box C are 5.3% and 6.8%. Type 2 rows in box B cluster in 73 cells of 0.1 degree, on all 68 days.
  The audit does not know the reason. H1 counts these rows as fire detections.
- FIRMS is not a complete fire record. Each box has detections in only a few UTC hour groups each
  day, and cloud and smoke hide fires. The files cannot show how many fires were not detected.

## 4. H0 result

Window: 2015-09-01 00:00 to 2015-11-01 00:00 SGT. Evidence class: observation.

| Region | Mean ug/m3 | Max ug/m3 | Max at (SGT label) | Hours > 55 | Hours > 150 | Hours > 250 |
|---|---|---|---|---|---|---|
| North | 66.20 | 284 | 2015-09-25 08:00 | 703 | 74 | 16 |
| South | 72.67 | 353 | 2015-09-25 03:00 | 732 | 118 | 20 |
| East | 66.06 | 339 | 2015-09-25 04:00 | 669 | 81 | 15 |
| West | 74.76 | 471 | 2015-10-19 23:00 | 761 | 120 | 25 |
| Central | 57.88 | 267 | 2015-09-24 18:00 | 589 | 51 | 4 |

- Hours with a network peak above 55: 871 of 1,464. Hours in event periods of 3 h or longer: 844.
- An "event" here is common, not rare. 57.7% of the window is in an event period.
- 38 event periods are not 38 independent episodes. Many runs are separated by a few hours.
- An event start is a threshold crossing of the five-region maximum. It is not a measured arrival
  of smoke. Onsets occur at many hours of the day, with a peak at 10:00 to 15:00 SGT (22 of 38).

H0 supports: "NEA reported these regional values." H0 does not support any source statement.

## 5. H1 result

Method: for each onset and box, each lag window [onset - L, onset) is checked. A lag is consistent
if at least half of the non-calm hours blow from the box sector, the along-bearing wind run is at
least half the distance, no hour has corridor-mean rain above 1 mm, and at most 10% of hours are
missing. A box is consistent if any lag is consistent. Hour convention: `hour_ending`.

Box status over the 38 event onsets:

| Level | Box | Consistent | Inconsistent | Inconclusive |
|---|---|---|---|---|
| 10 m | A | 0 | 25 | 13 |
| 10 m | B | 25 | 11 | 2 |
| 10 m | C | 19 | 19 | 0 |
| 850 hPa | A | 6 | 20 | 12 |
| 850 hPa | B | 33 | 3 | 2 |
| 850 hPa | C | 23 | 15 | 0 |

- **Controls.** H0 finds 593 clean hours, but H1 uses a 14:00 SGT label clear of events by 24 h.
  Only three labels qualify: 2015-09-01, 10-30 and 10-31. All three are at or below 55 ug/m3.
  Across all boxes and both levels, only box B on 10-31 has a decided status. The `association`
  field is `insufficient` for every box. This is the correct value.
- **Negative controls.** `fire_upwind_no_pm25_rise` reports 0. This is an artefact of the three
  control labels. It is not a passed control: the base rate in section 6 finds many clean hours
  that pass. `pm25_rise_without_upwind_detections` reports 0 because no 72 h window has zero
  detections in any box, in any of 1,383 hours. The minimum counts are 3, 286 and 26 for boxes A,
  B and C. So the fire condition adds almost no information.
- **`rain_or_wind_shift`** reports 10 onsets at 10 m and 1 onset at 850 hPa.
- **Hour convention.** `time_sensitive_boxes` is `[box-b]` at both levels. Under `hour_beginning`,
  two box B statuses swap at 10 m, and one changes from inconclusive to consistent at 850 hPa.
- **Early onsets.** ERA5 starts at 2015-09-01 00Z. An onset before 2015-09-04 00Z has no full 72 h
  history. This affects the first event and the 09-01 control.

## 6. Base-rate result

Source: local run file `h1_base_rate.json`, method `haze-h1-base-rate` version 1, `hour_ending`. It applies the
same check to 1,383 hours, from 2015-09-04 09:00 to 2015-10-31 23:00 SGT. Its `h0_digest` matches
`h0.json`. Each cell is consistent / decided = rate. Decided excludes inconclusive hours.

| Level | Box | All hours | Clean, peak <= 55 | Peak > 150 | Event onsets |
|---|---|---|---|---|---|
| 10 m | A | 48 / 796 = 0.060 | 0 / 294 = 0.000 | 41 / 90 = 0.456 | 0 / 25 = 0.000 |
| 10 m | B | 727 / 1,310 = 0.555 | 249 / 476 = 0.523 | 114 / 160 = 0.713 | 24 / 35 = 0.686 |
| 10 m | C | 540 / 1,255 = 0.430 | 153 / 429 = 0.357 | 61 / 160 = 0.381 | 18 / 37 = 0.486 |
| 850 hPa | A | 88 / 778 = 0.113 | 35 / 300 = 0.117 | 4 / 60 = 0.067 | 6 / 26 = 0.231 |
| 850 hPa | B | 1,097 / 1,322 = 0.830 | 346 / 483 = 0.716 | 155 / 160 = 0.969 | 32 / 35 = 0.914 |
| 850 hPa | C | 876 / 1,255 = 0.698 | 273 / 429 = 0.636 | 129 / 160 = 0.806 | 22 / 37 = 0.595 |

The group sizes are 1,383 hours, 529 clean hours, 160 hours above 150 ug/m3 and 37 onsets.
The first of the 38 onsets has no full history, so it is not in this table.

Meaning:

- A pass tells little. At 850 hPa, box B passes in 71.6% of clean hours and box C in 63.6%.
- The result does not separate the boxes. At 850 hPa, boxes B and C both pass in 722 of 1,383
  hours. Two boxes pass in 797 hours. No box passes in 119 hours.
- The overlap has a clear reason. The two sectors overlap at 125.6-153.1 degrees. The period mean
  850 hPa wind is from 139 degrees in the box B corridor and 136 degrees in the box C corridor.
  Both directions are in both sectors.
- A base rate in a high-haze window is itself conditional. This window has only two months of one
  extreme year. It cannot give a seasonal or a climatological rate.

The stdlib script `haze_base_rate.py` beside the JSON gives slightly different group counts (for
example 538 and not 529 clean hours). It maps labels by a different hour rule, and it counts the
last nine hours, which have no PM2.5 value, as clean. Use the JSON, which comes from the branch
code. The script is valid only as a check of H1 statuses.

## 7. Exploratory discrimination checks

This audit added these checks. They were not pre-registered. They use the base-rate grid. They
describe one window, and they give no significance.

### 7.1 PM2.5 given a status

Overall in these 1,383 hours: P(peak > 55) = 0.617 and P(peak > 150) = 0.116.

| Level | Box | P(>55) if consistent | P(>55) if inconsistent | P(>150) if consistent | P(>150) if inconsistent | P(>150) if inconclusive |
|---|---|---|---|---|---|---|
| 10 m | A | 1.000 | 0.607 | 0.854 | 0.066 | 0.119 |
| 10 m | B | 0.657 | 0.611 | 0.157 | 0.079 | 0.000 |
| 10 m | C | 0.717 | 0.614 | 0.113 | 0.138 | 0.000 |
| 850 hPa | A | 0.602 | 0.616 | 0.045 | 0.081 | 0.165 |
| 850 hPa | B | 0.685 | 0.391 | 0.141 | 0.022 | 0.000 |
| 850 hPa | C | 0.688 | 0.588 | 0.147 | 0.082 | 0.000 |

The box A 10 m row looks strong, but its 48 passes are three runs on two episodes: 17 hours from
2015-09-10 13:00, then 8 and 23 hours from 2015-09-23 23:00 SGT. The effective sample is about two.

### 7.2 Time-shift control

The PM2.5 series was shifted against the unchanged status series by 3 to 54 whole days, with
wrap-around. Each shift keeps the hour of day and the autocorrelation. The value is the rate above
150 ug/m3 minus the rate in clean hours.

| Level | Box | Observed difference | Shift range | Shifts at or above observed |
|---|---|---|---|---|
| 10 m | A | 0.456 | -0.142 to 0.188 | 0 of 52 (see 7.1: about two episodes) |
| 10 m | B | 0.189 | -0.495 to 0.423 | 9 of 52 |
| 10 m | C | 0.025 | -0.455 to 0.233 | 28 of 52 |
| 850 hPa | A | -0.050 | -0.223 to 0.515 | 28 of 52 |
| 850 hPa | B | 0.252 | -0.376 to 0.276 | 2 of 52 |
| 850 hPa | C | 0.170 | -0.418 to 0.385 | 14 of 52 |

The shifts are not independent, so these counts are not p-values. Box B at 850 hPa is the only
result that is near the edge of its shift range with a large number of passes. It needs another
season or an independent test before anyone treats it as more than a description.

### 7.3 Design limits that this data shows

- **Rain selection.** Rain makes an hour inconclusive. Inconclusive hours are mostly clean: at
  850 hPa box B, 0 of 61 are above 150 ug/m3, and P(>55) is 0.246. So "decided" is not a random
  subset, and rain and low PM2.5 are mixed in the clean rate.
- **Any-lag rule.** `combine` passes a box if any of five lags passes. This raises the clean rate.
  At 850 hPa box B, the best single lag gives 0.660, and any lag gives 0.716.
- **Lag dominance.** Box C passes through the 72 h lag in nearly all cases. At 10 m, no lag up to
  36 h passes. A 72 h window with half its hours in sector does not show when air left a box.
- **Half distance.** The advection test requires half the distance. It does not show arrival.
- **Fire term.** The 72 h fire count does not depend on which lag passed. A pass at 12 h and a
  detection 70 h earlier are not linked by the code.
- **Sector width.** Each sector is 90 degrees, tested against one bearing to the box centre.
- **Corridor means.** A mean over a rectangle can hide curved flow, sea breeze and local rain.
- **Rain limit.** The 1 mm limit is a design choice for a corridor mean. It was not calibrated.
  The 1 mm level is rare: 35, 2 and 9 hours for the corridors of boxes A, B and C.
- **Control time.** Controls use 14:00 SGT only, while onsets occur at many hours.

## 8. Claim ladder

These classes are separate. Support for one class gives no support to a higher class.

| Class | Question | Current status | What the local data supports |
|---|---|---|---|
| Observation | What did NEA report? | Supported | H0 tables. |
| Co-occurrence | Did two things happen in the same period? | Supported, weak | Thermal anomalies were detected in every box in every 72 h window, in clean and in hazy hours. This does not separate the two. |
| Spatial association | Do fire location and PM2.5 pattern relate in space? | Not tested, not testable with this data | NEA gives five regional values over one small area. Box limits are analyst choices. H1 gives no spatial statistic. |
| Transport plausibility | Do wind and rain allow transport from a box? | Supported only as "not excluded" | H1 and the base rate. A pass is common in clean hours. A fail at one level does not exclude transport at another level. |
| Attribution | What share of PM2.5 came from a source? | Unsupported | No emissions, no dispersion or trajectory model, no composition data, no plume height. FRP and detection counts are not emissions. |
| Causation | Did this source cause the PM2.5? | Unsupported | `Provenance` refuses this class. No design here can identify it. |
| Prediction | What will PM2.5 be? | Not done | H1 is retrospective and uses ERA5. See `docs/science-data-forecast-protocol.md`. |

Allowed wording: "Wind and rain were consistent with transport from box B at this onset. The same
check passes in 71.6% of clean hours in this window." State the base rate with every pass.

Do not write: "Smoke came from box B", "fires caused the rise", or "H1 confirms the source".

`EvidenceClass` has `association`, but no class for co-occurrence as distinct from spatial
association. Any report that uses `association` must state which one it means.

## 9. Independence matrix

No cell in this matrix says "independent". The local files cannot prove independence. A cell can
state only what the files or the published product descriptions show.

Key: **NOT** = shares data or a pipeline. **OVERLAP** = different quantity, but a shared sensor or
input is known or is not excluded. **DIFF** = different quantity and no shared input is known to
this audit; this is not proof of independence. **N/A** = no meaningful comparison.

| | NEA PM2.5 | FIRMS AOI | FIRMS boxes | MCD64A1 | ERA5 wind | ERA5 rain |
|---|---|---|---|---|---|---|
| **NEA PM2.5** | NOT: five regions, one network | DIFF | DIFF | DIFF | DIFF | DIFF |
| **FIRMS AOI** | | N/A | NOT: same rows (subset of box C) | OVERLAP | OVERLAP | OVERLAP |
| **FIRMS boxes** | | | NOT between box A and box B: same product, 342 shared rows | OVERLAP | OVERLAP | OVERLAP |
| **MCD64A1** | | | | N/A | DIFF | DIFF |
| **ERA5 wind** | | | | | NOT: 10 m and 850 hPa are one system | NOT: same system |

Reasons:

- **Five NEA regions** are not five samples. They are one publisher and one area, and a haze event
  affects all of them. The audit does not know how NEA makes a regional value.
- **FIRMS and MCD64A1** both come from MODIS on Terra and Aqua. The published MCD64A1 method uses
  active-fire data as an input. Agreement between them is not independent confirmation. This
  statement comes from product documentation, and the audit did not check it in local files.
- **ERA5 and FIRMS.** ERA5 assimilates satellite data, and the audit cannot exclude a shared MODIS
  input. Wind and thermal anomalies are different quantities in any case.
- **10 m and 850 hPa** are not two independent lines of evidence. Rain in both checks is the same
  ERA5 field.
- **Reproduction is not independence.** H1 and the base rate use the same extract. The stdlib
  recheck uses the same extract. The Earth Engine reference reads the same MCD64A1 raster.
- **A website that copies NEA values** would add no evidence. No such source is in use.

Candidates that are not local have no status here. The audit makes no claim for them.

| Candidate | Local | Note before any use |
|---|---|---|
| Other ground networks | No | Coverage, calibration and comparability are not established. |
| FIRMS VIIRS | No | Owner has not approved it. Different sensor from MODIS. Check 2015 coverage. |
| CAMS forecast or analysis | No | Deferred. Published descriptions show use of satellite aerosol and fire data, so overlap with FIRMS needs a check. |
| MERRA-2 aerosol | No | Assimilates satellite aerosol data. Not ground truth. |
| Satellite AOD, AERONET | No | Column quantity. PM2.5 needs a model and assumptions. |
| HLS imagery | No | No download without approval. |

## 10. Time availability audit

Valid time is not availability. `available_at` is the time a value could have been known.

| Dataset | Event time | `available_at` | Usable at a 2015 issue time? |
|---|---|---|---|
| NEA PM2.5, this file | Label hour, convention not stated | Not recorded. File retrieved 2026-10-27. Real-time latency and revisions are not known. | Only with a modelled rule. Label it as modelled. |
| FIRMS MODIS_SP | Overpass, UTC | Not recorded. Retrieved 2026-10-27 and 2026-10-29. This is standard-processing data, which is released later than near-real-time data. | No. A simulated latency gives a hindcast, not a forecast. |
| ERA5 wind and height | Valid hour | Not recorded. Retrieved 2026-10-29. Production came after 2015. Published ERA5 descriptions state that the analysis window can include observations after the valid hour. This audit did not check that locally. | No. |
| ERA5 rain | Hour ending at valid time | Same | No. |
| MCD64A1 | Calendar month | Not recorded. Retrieved 2026-10-27. | No. |

The local manifests record retrieval times only. These are upper limits, not publication times.

## 11. Gap inventory

| Gap | Effect | Needs |
|---|---|---|
| Run-folder data is not pinned in the repository | A clean clone cannot reproduce H1. ERA5 and FIRMS need accounts and fresh approval. | Owner decision. See section 13. |
| `config/haze/datasets.yaml` and `config/acquire/haze-2015-h1.yaml` are stale | They say `owner_approval_and_account`, `registered_not_downloaded` and `data/haze-2015`. The files exist in `runs/haze-2015/`. | Maintainer update. |
| Download approvals expired on 2026-10-31T16:00Z | Files already downloaded are not affected. A new download needs a new approval. | Owner decision. |
| No usable control group in H1 | No event-control contrast exists in `h1.json`. | Method change, or merge of the base rate. |
| Base rate is not merged and has no provenance | The main finding of this audit is outside the main code path. | Maintainer decision. |
| NEA hour convention is not known | Box B statuses change at a few onsets. | Ask NEA, or keep both conventions. |
| ERA5 starts on 09-01 00Z | First 81 labels have no full 72 h history. | Extra August ERA5, with approval. |
| No plume height, trajectory or dispersion model | No attribution and no arrival test. | Later research. |
| No emissions data | FRP and counts stay proxies only. | Later research. |
| No source-box MCD64A1, no VIIRS, no CAMS | No cross-sensor check for boxes. | Owner has not approved these. |
| One extreme two-month window | No generalisation. No climatology. | Multi-year data. |
| 2015 Kalimantan AOI is a small part of box C | Burned-area values say nothing about the other boxes. | Scope statement in reports. |
| October 2015 MCD64A1 valid fraction is 0.460 | The October area is not a reportable finding. | No action. The gate works. |

## 12. Corrections to the planning notes

| Planning note | Local files show |
|---|---|
| Do not assume ERA5 or broader FIRMS is local | ERA5 and three regional FIRMS boxes are local in `runs/haze-2015/`, hash-checked, but not in the repository. |
| Pinned FIRMS is a Kalimantan AOI of 10,257 records | True. It is an exact subset of box C. 1,043 of these rows are below confidence 30, and 272 are type 2. |
| Burn scar is an independent, different view of fire | MCD64A1 and FIRMS MODIS share a sensor family, and MCD64A1 uses active-fire input. Do not call them independent. |
| Candidates may give independent evidence | No local pair is shown to be independent. See section 9. |

Code issues for the maintainer are in section 14. Owner decisions are in section 13.

## 13. Owner decisions

1. Pin the ERA5 and regional FIRMS files for release, or state that H1 is not reproducible from a
   clean clone. ERA5 is 67.9 MB and the FIRMS boxes are 6.6 MB. Licence terms are in the manifests. Check attribution
   text before any redistribution.
2. Decide if the demo may show H1 at all. If it does, show the base rate beside every pass.
3. Confirm the wording in section 8 for reports.

## 14. Code issues for the maintainer

This audit changed no code.

| ID | Location | Issue | Scope |
|---|---|---|---|
| C1 | `src/earthlab/haze/contracts.py:155` | `known_by` falls back to `valid_time`. `FeatureSet` accepted an ERA5 and a MODIS_SP feature with `available_at` unset. It refuses them only if the caller sets `available_at`. | Confirmed by a run. No forecast code uses it yet. |
| C2 | `src/earthlab/data/nea_pm25.py:23`, `:129` | `2016-04-04 010:00:00` is parsed as 10:00. By position it is 00:00. First-row-kept then drops the real 10:00 row. | Outside the 2015 window. |
| C3 | `src/earthlab/haze/fires.py:37` | No `type` filter. H1 counts type 2 and type 3 rows as fire detections. | Counts only. Statuses do not use counts. |
| C4 | `src/earthlab/haze/h1.py:194` | `fire_upwind_no_pm25_rise = 0` looks like a passed control. It comes from having three control labels. | Risk of misreading. |
| C5 | `src/earthlab/haze/h1.py:83` | The docstring says "control-quality hour", but the code does not call `is_control_hour`. The three labels do pass that test. | No current effect. |
| C6 | `src/earthlab/haze/sector.py:136` | Any-lag rule and excluded inconclusive hours raise and bias pass rates. See 7.3. | Method design. |
| C7 | branch `feat/haze-base-rate` | `BaseRateReport` has no `Provenance`: no source hashes and no evidence class. | Before merge. |

## 15. Reproduce

Use an environment with the `haze` extra. Write outputs outside the repository.

```bash
uv run earthlab haze-h0 --out /tmp/h0.json
uv run earthlab haze-era5-extract --manifest runs/haze-2015/era5/era5-sl-haze-2015.manifest.json --level 10m --out /tmp/e10.json
uv run earthlab haze-era5-extract --manifest runs/haze-2015/era5/era5-pl850-haze-2015.manifest.json --level 850hPa --out /tmp/e850.json
uv run earthlab haze-h1 --met /tmp/e10.json --met /tmp/e850.json --firms runs/haze-2015/firms/box-a/firms-modis-sp-haze-2015-box-a.manifest.json --firms runs/haze-2015/firms/box-b/firms-modis-sp-haze-2015-box-b.manifest.json --firms runs/haze-2015/firms/box-c/firms-modis-sp-haze-2015-box-c.manifest.json --out /tmp/h1.json
```

Expected digests: H0 `a3b4be0cb3f27bb5a93d1ce07736cc21f0daa77565baaf87e27d3e75e17afbe3`,
H1 10 m `8f5786b0a119c0c4c7ba29bee75f9765a67df7b01d519aceb1df80002d876693`,
H1 850 hPa `2c2c9f974adb6ea03483dfb229c6c8e8fe7b79be95a6927fd29e18013e389c52`.

The haze, NEA and acquire unit tests passed on `0816d46`. The exploratory checks in section 7 ran
from temporary scripts and are not in the repository.

# Data suitability, S3 and S4, measured results

Status: research results. Result files stay outside the repository in
`earthlab-e1-runs/suitability-v1`. No model ran and nothing was downloaded for these results.

## Audit of local data

`python -m earthlab.harness.audit` reads local state only.

| Product | Local state | Approval state |
|---|---|---|
| NEA hourly PM2.5 | hash matches | public archive |
| ERA5 2015, FIRMS boxes A, B, C, MCD64A1 | hashes match | `recorded_expired`: recorded approvals, expired 2026-10-31, not signed records |
| Prithvi weights, HLS chips | hashes match `provenance.json` | `chat_only_unsigned`: owner chat approval, no signed record |
| MAIAC, SMAP, EMIT, CAMS | not acquired | none |

The earlier handoff gave 109,584 NEA rows. The audit found 109,580 rows after repair.

## S3: wind, rain and fire, 2015

Evidence class: perfect-weather hindsight diagnostic. ERA5 is a reanalysis, so this is not a
forecast and cannot show forecast skill. The result covers two haze-heavy months.

Overall verdict: **inconclusive. The source is not identifiable.** This is not an attribution.

| Box | Level | Verdict | Event rate | Clean-hour rate | Stable over 54 settings |
|---|---|---|---|---|---|
| A | 10 m | inconsistent | 0.000 | 0.000 | 0.89 |
| A | 850 hPa | inconsistent | 0.231 | 0.117 | 0.85 |
| B | 10 m | inconclusive | 0.686 | 0.523 | 0.52 |
| B | 850 hPa | inconclusive | 0.914 | 0.716 | 0.63 |
| C | 10 m | inconclusive | 0.486 | 0.357 | 0.76 |
| C | 850 hPa | inconclusive | 0.595 | 0.636 | 0.67 |

Finding: no box reached consistent. Box B at 850 hPa passes in 91 percent of event onsets but
also in 72 percent of clean hours, so that test says little. Wind-bearing sign tests pass in
all 5 cases, and the hourly clocks have no gaps.

## S4: burn-scar segmentation gate

The gate read one real HLS chip and mask. No score exists, because nothing ran.

| Request | Verdict | Blocker |
|---|---|---|
| Score Prithvi on the shipped chips | `request_resources` | no signed approval for the weights |
| Map burn scars in the Kalimantan box | `request_resources` | chips cover Texas, so six-band HLS for the box is needed, and the same approval |

Chip facts: 804 chips and 804 masks, 512 by 512, six bands, float32, 30 m. Band order comes from
the dataset card only, because the files carry no band names. The gate records this limit.
MCD64A1 is refused as a reference mask. HLS is multispectral, and a hyperspectral claim is refused.

## Not done

There is no availability query for real HLS granules, so the S4 route to a person uses a mock
URL in tests. The real Prithvi requests stop at `pm_endorsed`.

# M5 feasibility report: multi-source Kalimantan 2015 characterisation

Experiment ID: `m5-feas-v1`. Date: 2026-11-03. Status: **feasibility only. No model ran. No file was downloaded. No training ran.** This report is separate from M4 and has its own acceptance criteria (section 8).

Sources: the Advanced Science Kit of 2026-11-03 (`01_SCOPING_DECISION.md`, `06_GO_NO_GO_GATES.md`, `protocols/04_FROZEN_PROTOCOL.md`, `02_DATA_CATALOG.csv`), the repository data card `data/kalimantan-2015/DATA_CARD.md`, the dataset audit of 2026-11-01 (hashes verified against manifests on that date), and four read-only metadata queries to NASA's public catalogue (CMR) on 2026-11-03. The queries returned hit counts and granule lists. They moved no data files.

## 1. Recommendation

| Part | Decision | One-line reason |
|---|---|---|
| M5-A: descriptive baseline B0 (MCD64A1 + FIRMS + ERA5, local files) | **GO** | All data is local, pinned and hashed. It needs no new approval. September passes the 80 percent valid-land rule. |
| M5-B: add HLS L30 dNBR/NDVI (B1) | **NO-GO now. Conditional GO after a scoped, signed request.** | 28 granules (3.26 GB per CMR) exist, but only a few are clear. No pre/post pair is proven. |
| M5-C: add rainfall lags (B2) | **Conditional.** ERA5 (local) is too coarse. IMERG needs a subset request. | The box holds about 20 ERA5 cells. |
| M5-D: add SMAP soil moisture (B3) | **NO-GO** | Dense-forest and peat flags are likely to remove most cells. No quality check exists. Latency rules out issue-time use. |
| M5-E: any trained model (B4, Prithvi, B5) | **NO-GO** | One season, one box, no independent labels. Kit gate V7. |

Overall: **GO for a narrow M5-A, NO-GO for the full multimodal study.** A result of `no_incremental_gain` or `insufficient_coverage` is a valid outcome and ends the study.

## 2. What exists locally (verified on 2026-11-01)

| Asset | Coverage | Fact |
|---|---|---|
| MCD64A1 v6.1 GeoTIFFs | Box 113.8 to 114.8 E, 3.2 to 2.0 S; Sep and Oct 2015; 463 m cells, 289 x 267 | Sep: 96.7 percent valid land, 3,623 burned pixels, 77,426 ha. Oct: **46.0 percent** valid land, fails the 80 percent gate (`insufficient_data`). |
| FIRMS MODIS_SP CSV | Same box; 1 Sep to 30 Oct 2015 | 10,257 rows. Terra 5,105, Aqua 5,152. 272 rows are static land sources (`type` 2). |
| ERA5 single-level and 850 hPa | 95 to 118 E, 6 S to 4 N; hourly; 0.25 degree | Hash verified. Perfect-weather hindcast only. The approval expired on 2026-10-31. |
| NEA PM2.5 | Five regions, hourly | Not used by M5. It belongs to the separate forecast study. |
| Prithvi weights and HLS chips | One US test chip | Not valid evidence for Kalimantan. The kit says so. |

## 3. Data the study would need (not local)

CMR queries on 2026-11-03, box 113.8 to 114.8 E, 3.2 to 2.0 S:

| Product | 1 to 31 Aug 2015 | 1 Sep to 31 Oct 2015 | 1 to 30 Nov 2015 | Note |
|---|---|---|---|---|
| HLSL30 v2.0 granules | 14 | 28 | 11 | Four MGRS tiles: T49MHS, T49MHT, T50MKB, T50MKC. |
| HLSS30 v2.0 granules | 0 | 0 | 0 | Sentinel-2 based product does not cover 2015 here. |
| SPL3SMP v009 granules | not queried | 62 (daily, global) | not queried | Global daily files. The box does not limit the count. |
| GPM IMERG Early v07 granules | 1,489 | 2,929 | 1,441 | Half-hourly global files. A subset request is needed. |

### HLS L30 scene clarity (September and October 2015)

The granule metadata holds `CLOUD_COVERAGE` for the whole scene, in percent. It does not say how much of the study box is clear. Scenes with 5 percent or less:

- 2015-09-13: T49MHS 0, T50MKB 1.
- 2015-09-29: T49MHS 1.
- 2015-10-15: T49MHS 1.

All other scenes show 14 to 100 percent. The tiles T50MKC and T49MHT have no scene under 25 percent in September or October. The clear scenes sit on two tiles (T49MHS, T50MKB). Which part of the box these tiles cover is not computed here.

What this means:

- A pre-fire to post-fire pair on one tile is possible in principle: 13 Sep (clear) and 29 Sep or 15 Oct (clear) on T49MHS.
- The scene-level cloud figure does not prove clear pixels over burned cells. Haze smoke also affects reflectance. Both need a pixel check on the real scenes.
- The size of the 28 granules is 3.26 GB by the catalogue field `SizeInBytes`. A subset of the clear scenes would be smaller. The exact size is not measured.

## 4. One falsifiable question

**Q1.** In the fixed Kalimantan box, for September 2015, on 500 m MCD64A1 valid-land cells: does the count of FIRMS detections in the cell and its neighbours separate burned from unburned cells better than chance, when scored by spatial-block bootstrap with blocks of 0.1 degree?

- **Metric:** area under the ROC curve (AUC) of the FIRMS count against the MCD64A1 burned flag.
- **Pass:** the 95 percent block-bootstrap interval of AUC lies above 0.5.
- **Fail:** the interval contains 0.5. The outcome is `no_incremental_gain`, and nothing is added to the baseline.
- **What it does not claim:** FIRMS is not burned area. MCD64A1 is a mapped reference, not ground truth. The test says nothing about smoke origin in Singapore.

**Q2 (only after Q1 passes and IMERG is approved).** Does a 30-day antecedent rainfall feature add to AUC over FIRMS alone, on the same complete-case rows? The pre-registered gain is a lower interval bound above 0.02 AUC. Otherwise: `no_incremental_gain`.

Why Q1 is falsifiable: there are about 69,000 cells in the box and 3,623 burned in September, so both classes are large. A wrong claim shows as an AUC interval that crosses 0.5. Both classes are large, so the interval can be narrow. No such test has run on the repository data, so no result is stated here.

## 5. Deterministic baseline and ablation plan

Follows `protocols/04_FROZEN_PROTOCOL.md`. The plan is fixed before any result.

| Step | Content | Data | Needs approval |
|---|---|---|---|
| B0 | Monthly QA-qualified burned area; FIRMS count overlay; ERA5 wind and rain as description only | local | no |
| B1 | B0 plus HLS dNBR or NDVI change, only where a clear pre and post scene exist | HLS L30, 2 to 4 granules | yes: signed request with byte cap and licence |
| B2 | B1 plus lagged IMERG rainfall | IMERG subset | yes |
| B3 | B2 plus SMAP, only if recommended-quality retrievals exist | SMAP, about 34 MB per day per catalogue | yes |
| B4, B5 | Regularised model, Prithvi transfer | - | no-go (section 1) |

Rules for every step: compare B(n) and B(n+1) on the same complete-case rows. Report how many rows drop. Fit nothing on the evaluation blocks. Keep observation, publication, retrieval and analysis times separate. Keep the sealed PM2.5 test period closed. Do not read it for M5.

## 6. Provenance and licence

| Asset | Licence | Status |
|---|---|---|
| MCD64A1, FIRMS | NASA open data, no restriction on use | Pinned in `config/cases/kalimantan-2015-burned-area.yaml`. The 2026-10-27 approvals expired on 2026-10-31. A new run needs a fresh recorded approval, even for local files, by the repository's own rule. |
| ERA5 | CC-BY 4.0 | Hash verified. Approval expired 2026-10-31. |
| HLS L30, SMAP, IMERG | NASA Earthdata terms. Not yet verified per asset. | Not acquired. The kit says a portal link does not authorise redistribution. Record each licence first. |

## 7. Risks and unknowns

- **One season, one box.** No geographic or seasonal holdout beyond blocks inside the box. Only descriptive claims are possible.
- **October is not usable.** Valid land is 46 percent, below the 80 percent gate.
- **ERA5 is coarse.** About 4 by 5 cells cover the box. Rainfall differences inside the box are small.
- **Haze affects optical data.** Smoke can mask both burned and unburned cells. The pixel check may remove most scenes.
- **Peat fires smoulder.** Thermal anomalies and mapped burn can differ in time and place.
- **Not known:** pixel-level clear fraction of HLS scenes over the box; SMAP quality over this box; IMERG subset size.

## 8. Acceptance criteria for M5 (feasibility)

| Criterion | Met? |
|---|---|
| Data availability and spatio-temporal coverage stated with numbers | Yes (sections 2 and 3) |
| Provenance and licences stated | Yes, with gaps named (section 6) |
| One falsifiable question with a pass and a fail rule | Yes (section 4) |
| Deterministic baseline and ablation plan | Yes (section 5) |
| Go or no-go stated | Yes (section 1) |
| No large acquisition, no retraining | Yes. Four metadata queries only. |

## 9. Next steps if the owner agrees

1. Approve a fresh read-only run of B0 on local files. It needs no download.
2. Query HLS granule footprints against the box to compute the clear fraction per tile. This is still metadata.
3. Only then write a scoped, signed request for 2 to 4 HLS granules with a byte cap.

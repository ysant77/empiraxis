# M5 data integration status

Audit date: 2026-11-03. Base: `release/hackathon-2026` = `4e4a4f1`. Branch: `feat/m5-multisource-environment`.
A dataset is not "integrated" because a YAML file lists it. Seven levels are tracked apart.

| Level | Meaning |
|---|---|
| L1 | Registered or planned |
| L2 | Acquisition code implemented |
| L3 | Real data acquired and provenance-verified |
| L4 | Processed and usable |
| L5 | Used in a reproducible experiment |
| L6 | Independently validated |
| L7 | Available in the UI |

Marks: **Y** met. **P** partly met (see the note). **N** not met. **B** blocked.

## Registered research questions

Verbatim text is in `M5_RESEARCH_QUESTIONS.md`.

| ID | Short name | Stage | State |
|---|---|---|---|
| M5-A | Multisource T+6 PM2.5 prediction | primary, first | pilot run; no supported gain; IMERG Early rung I1 run, no gain |
| M5-B | Regional transport consistency | own protocol (`m5-protocol-b-1`) | frozen; waits for ERA5 2017 to 2019; no source attribution |
| M5-C | Severe-event prediction 12 to 24 h, calibrated, with abstention | own protocol (`m5-protocol-c-1`) | run on 2019: lag model skilful vs base rate; FIRMS adds little; one episode; label fragile |

The 2015 negative ablation stays a separate finding.

## Matrix

| Dataset | L1 | L2 | L3 | L4 | L5 | L6 | L7 |
|---|---|---|---|---|---|---|---|
| NEA hourly PM2.5 | Y | Y | Y | Y | Y | P | Y |
| ERA5 10 m wind, rain, BLH | Y | Y | Y | Y | Y | P | P |
| ERA5 850 hPa wind | Y | Y | Y | Y | Y | P | P |
| FIRMS MODIS_SP (AOI and boxes A, B, C) | Y | Y | Y | Y | Y | N | P |
| MCD64A1 v6.1 (Sep, Oct 2015) | Y | Y | Y | Y | P | P | Y |
| GPM IMERG V07 | P | Y | Y | P | P | N | N |
| HLS L30 v2.0 | N | Y | Y | P | P | N | N |
| HLS S30 v2.0 | N | N | N | N | N | N | N |
| SMAP L3 SPL3SMP v009 | P | Y | Y | Y | P | N | N |
| MAIAC MCD19A2 v061 | P | N | N | N | N | N | N |
| FIRMS VIIRS | N | N | N | N | N | N | N |
| CAMS forecast | Y | N | N | N | N | N | N |
| Prithvi BurnScars chip (HLS, US) | Y | Y | Y | Y | P | N | N |

The "M5 pilot" entries (HLS, SMAP, IMERG reader) come from this branch. All other entries come from the release code.

## Verification of the owner's assessment

The assessment says: NEA, ERA5 wind and rain, FIRMS and MCD64A1 are in real use. IMERG, HLS and SMAP are not shown.

- **Confirmed for the release code (`4e4a4f1`).** `grep` for IMERG, SMAP and HLSL30 found only catalogue
  text (`harness/audit_catalogue.py`, `docs/live-data-and-forecast-inputs.md`), the Prithvi chip tools
  and a test. No acquisition or processing code existed. The audit module reported MAIAC, SMAP, EMIT
  and CAMS as `not_acquired` (`docs/data-suitability-results-v1.md`).
- **Correction 1.** MCD64A1 is in real use for burned-area work (`earthlab burned-area`), but it
  never entered the 2015 ablation. The protocol excludes it: the monthly map is not available during
  that month (`docs/haze-2015-ablation-protocol.md`).
- **Correction 2.** ERA5 is not in `data/`. The GRIB files, the extracts and the FIRMS boxes A, B, C
  live in the gitignored folder `runs/haze-2015/`. A clean clone cannot rerun the ablation
  (`docs/science-data-audit.md`, section 1).
- **Correction 3.** All download approvals expired on 2026-10-31 (`config/approvals/*.yaml`).
  They were recorded from chat, not signed. New pilot downloads on this branch rely on the owner
  instruction in the M5 brief. The receipts say so.
- **Correction 4.** HLS data exists in the release as one US test chip for Prithvi (six bands,
  Level A inference). It says nothing about Kalimantan.

## Evidence per dataset

### NEA hourly PM2.5

- L1: `config/haze/datasets.yaml` (`nea-historical-1hr-pm25`).
- L2: `src/earthlab/acquire/nea_live.py`; reader `src/earthlab/data/nea_pm25.py`, `forecast/dataset.py`.
- L3: `data/nea/manifest.json`. SHA-256 `2fb76e1c…` matches (`docs/science-data-audit.md`, section 3).
- L4: audited grid, no repair or fill (`forecast/dataset.py`).
- L5: published 2015 ablation, M3 runs, and this branch (`docs/m5/results/`).
- L6 (partial): a separate stdlib parser agreed on regional means, maxima and hour counts. No second
  source for the values exists.
- L7: chart and caption in `src/earthlab/ui/common.py`.

### ERA5 10 m wind, rain, boundary layer height; ERA5 850 hPa wind

- L1: `config/haze/datasets.yaml`, `config/acquire/haze-2015-h1.yaml`.
- L2: `src/earthlab/acquire/era5.py`. The module accepts only the 2015 request.
- L3: four GRIB files in `runs/haze-2015/era5/`, manifests with hashes. I re-hashed all four on 2026-11-03: each matches its manifest.
  M5 added four GRIB files for 2016 (Sep, Oct; single and pressure levels) outside Git, hashes in `docs/m5/receipts/season_2016.json`. Extracts: `scripts/m5_era5_extract.py`.
- L4: corridor-mean extracts (`haze/met.py`, `haze/grib.py`). Boundary layer height is downloaded but not extracted.
- L5: H1, S3 and the 2015 ablation. I reproduced the ablation exactly on 2026-11-03.
- L6 (partial): a separate corridor mean over the decoded fields matched to 3e-6 m/s. Wind conventions are tested (`tests/test_haze_wind.py`).
  ERA5 itself is a reanalysis; no station wind was compared.
- L7 (partial): the UI shows summary text and tiles from replays (`ui/lab_data.py`). No wind-vector or rain layer exists.

### FIRMS MODIS_SP

- L1: `config/haze/datasets.yaml`.
- L2: `src/earthlab/acquire/firms.py`; this branch adds `scripts/m5_acquire_season.py`.
- L3: AOI file in `data/kalimantan-2015/` and three boxes in `runs/haze-2015/firms/`, hashes match.
  This branch adds Aug 25 to Nov 1 files for 2016 to 2019 (`docs/m5/receipts/`).
- L4: `haze/fires.py`, `haze/ablation_features.py`.
- L5: H1, ablation (B3), and the M5 ladder.
- L6: none. No second fire source was compared.
- L7 (partial): detection counts appear in the report text. No hotspot layer exists in the UI.

### MCD64A1 v6.1

- L1: case file `config/cases/kalimantan-2015-burned-area.yaml`.
- L2: `src/earthlab/acquire/mcd64a1.py` (Earth Engine).
- L3: two GeoTIFFs in `data/kalimantan-2015/`, manifest hashes match.
- L4: `science/burned_area.py`. September passes the 0.80 valid-land gate (0.970). October fails (0.460).
- L5 (partial): burned-area reports and the HLS contrast on this branch. Not in the ablation.
- L6 (partial): tool, verifier and Earth Engine reference agree within set tolerances. All three read the same product.
- L7: map and caption in the UI (`ui/common.py`, `ui/engineering_lab.py`).

### GPM IMERG V07

- L1: source register on this branch (not in the release `datasets.yaml`).
- L2: `scripts/m5_acquire_imerg.py`, `src/earthlab/m5/{imerg,rain_compare}.py`.
- L3: GES DISC returned HTTP 403 until the owner authorised "NASA GESDISC DATA ARCHIVE". Then 240 granules downloaded
  (Final 19, 27, 30, 31 Oct 2015; Early 30 Oct), about 1.9 GB, hashes in `docs/m5/receipts/imerg_*.json`.
- L4 (partial): reader checked on real files; fill is NaN; hourly total needs both half hours.
- L5: descriptive ERA5-versus-IMERG comparison on three wet days (`docs/m5/qa/`). Rung I1 (Early, 2015 Stage P, 2,976 granules, 22.8 GB, corridor means kept, raw deleted) made T+6 MAE worse: 36.11 against 34.11 for R2 (`docs/m5/results/m5_i1_stage_p_2015.json`).
- L6, L7: none.
- Catalogue: Early and Late V07 run 1998 to 2026. Final V07 stops on 2025-09-30.

### HLS L30 v2.0

- L1: this branch (source register).
- L2: `scripts/m5_acquire_hls.py`, `src/earthlab/m5/{acquire,fetch,hls}.py`.
- L3: 16 band files (B04, B05, B07, Fmask) for tiles T49MHS and T50MKB on 2015-09-13 and 2015-10-15, 110 MB, hashes in `docs/m5/receipts/hls_pilot.json`.
- L4 (partial): reader, Fmask decoding and NBR work. Only 2.7% of the Kalimantan box has clear land on both dates.
  More than 96% of the pixels carry the high-aerosol flag. Verdict under the protocol gate: `HLS_not_eligible`.
- L5 (partial): descriptive dNBR contrast against MCD64A1 (`docs/m5/qa/hls_qa.json`). Not a model input.
- L6: none. MCD64A1 is another satellite product, not ground truth.
- L7: none.

### HLS S30 v2.0

CMR shows no S30 granule over the Kalimantan box in August to November 2015. S30 starts 2015-11-28 in the catalogue. Not used.

### SMAP L3 SPL3SMP v009 (36 km)

- L1 (partial): `harness/audit_catalogue.py` lists SPL3SMP_E as `not_acquired`. This branch adds SPL3SMP.
- L2: `scripts/m5_acquire_smap.py`.
- L3: eight daily granules (2015 and 2016, 16/19/22/25 October), 249 MB, hashes in `docs/m5/receipts/`.
- L4: reader `src/earthlab/m5/smap.py`. Result: no recommended-quality retrieval in the Kalimantan study box
  (78 retrieved cell-passes, 0 recommended). Verdict: `SMAP_unsuitable` for this region.
- L5 (partial): QA statistics only (`docs/m5/qa/smap_qa.json`). Not a model input, by the protocol gate.
- L6, L7: none.

### MAIAC MCD19A2 v061

Catalogue only. CMR shows one granule per tile and day. The files are HDF4; this branch has no HDF4 reader. Not assessed.

### Others

- FIRMS VIIRS and EMIT: not approved or not applicable (EMIT starts in 2022).
- CAMS forecast: registered, permission `deferred`. No code, no data.
- Prithvi BurnScars: weights and one US chip, Level A inference, IoU 0.912 (`docs/prithvi-level-a.md`). A reproduction on the publisher's split.
  It is not evidence for Kalimantan.

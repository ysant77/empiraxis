# Data card: Central Kalimantan, September–October 2015

Study area: box 113.8–114.8° E, 3.2–2.0° S (EPSG:4326), about 111 × 133 km. The repository owner confirmed this box, and approved both downloads (each capped at 10 MB, expiring 31 October 2026), on 27 October 2026. The records are in `config/approvals/kalimantan-2015-burned-area.yaml`. The case is `config/cases/kalimantan-2015-burned-area.yaml`.

## Files

| File | Source | Bytes | SHA-256 |
| --- | --- | --- | --- |
| `mcd64a1_2015_09.tif` | NASA MODIS MCD64A1 v6.1, via Google Earth Engine `MODIS/061/MCD64A1` | 88,070 | `126a6c50…` (full hash in the manifest) |
| `mcd64a1_2015_10.tif` | same | 60,592 | `daf55465…` |
| `firms_modis_sp_2015_09_2015_11.csv` | NASA FIRMS area API, source `MODIS_SP` (standard processing) | 807,287 | `75bf1fbc…` |
| `*.manifest.json` | written by `earthlab acquire` | — | the case file pins each manifest by its SHA-256 |

## MCD64A1 GeoTIFFs

- One file per month, five int16 bands: BurnDate, Uncertainty, QA, FirstDay, LastDay.
- Native sinusoidal grid (SR-ORG:6974), 463.3127 m pixels, 289 × 267 cells. The affine transform is in the manifest.
- **−1 means "masked in Earth Engine".** Earth Engine masks BurnDate wherever no burn was mapped. A −1 cell can be unburned or unmapped; only the QA bits decide which. Never read −1 as 0.
- **−32768 is nodata.** It marks cells outside the study-area polygon, at the corners of the sinusoidal rectangle.
- QA bit 0 = land, bit 1 = enough valid data to map the cell, bit 2 = shortened mapping period, bits 5–7 = special condition code. Source: the Earth Engine catalog page for MCD64A1.
- Licence: "MODIS data and products acquired through the LP DAAC have no restrictions on subsequent use, sale, or redistribution." Cite DOI 10.5067/MODIS/MCD64A1.061.

## Earth Engine reference (computed server side before download, recorded in the manifest)

The counts use pixel centres inside the box, on the native grid, as unweighted sums.

| Month | Pixels in box | Land | Valid land | Burned (valid) | Burned area, EE `pixelArea` |
| --- | --- | --- | --- | --- | --- |
| 2015-09 | 69,044 | 68,826 | 66,765 (96.7%) | 3,618 | 773.19 km² |
| 2015-10 | 69,044 | 68,826 | 31,640 (45.8%) | 2,154 | 460.32 km² |

October has valid data for less than half of the box, most likely because of haze and cloud. Any October result must carry that coverage, and may fail a coverage threshold.

These are product-mapped values for 500 m cells. They are not destroyed trees, forest loss or emissions.

## Preliminary local cross-check (not yet a committed test)

A separate reader (`tifffile` + NumPy, pixel-centre test from the sinusoidal formula) gave these counts, as local / Earth Engine:

| Month | Pixels in box | Valid land | Burned | Burned area |
| --- | --- | --- | --- | --- |
| 2015-09 | 69,049 / 69,044 | 66,776 / 66,765 | 3,623 / 3,618 | 777.71 km² (count × native pixel area) vs 773.19 km² (EE `pixelArea`) |
| 2015-10 | 69,049 / 69,044 | 31,677 / 31,640 | 2,158 / 2,154 | 463.23 vs 460.32 km² |

Two differences are not explained yet:

- **Edge pixels:** about five pixels differ. I believe these are cells near the box edge, but that is not proven.
- **Area method:** the areas differ by about 0.6%. The likely reason is that EE's `pixelArea` uses the ellipsoid, while the MODIS sinusoidal grid assumes a sphere.

The burned-area PR must explain both, set a tolerance in advance and make the check a test.

## FIRMS MODIS_SP detections

- 10,257 rows, 1 September to 30 October 2015 (58 days with detections). All rows are inside the box, and there are no exact duplicate rows.
- Satellites: Terra 5,105, Aqua 5,152. `type` 0 (presumed vegetation fire) 9,985; type 2 (other static land source) 272.
- The FIRMS area API accepts at most 5 days per request, so the download used 13 requests. The MAP_KEY is read from the environment and is never written.
- **A detection is a thermal anomaly at overpass time.** Repeated overpasses and adjacent pixels can detect the same fire. Detection counts are never burned area.
- Licence: NASA open data. Cite the MODIS Collection 6.1 active-fire product distributed by NASA FIRMS (DOI 10.5067/FIRMS/MODIS/MCD14ML).

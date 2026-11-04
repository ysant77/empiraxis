# M5 source and licence register

Checked 2026-11-03. A licence line on a portal page does not by itself allow redistribution of raw
files in a public Git repository. This branch keeps all raw files outside Git. It commits only
receipts (hashes, sizes, URLs), small QA summaries and code.

| Source | Product and version | Provider | Licence or terms (as recorded) | Access used | Latency class | Raw files in Git |
|---|---|---|---|---|---|---|
| NEA PM2.5 | Historical 1-hr PM2.5 (data.gov.sg `d_6c0d5fc3…`) | NEA Singapore | Singapore Open Data Licence v1.0 | public download | live feed has publication time; archive has none | yes (3.1 MB, already in `data/nea`) |
| ERA5 | `reanalysis-era5-single-levels`, `…-pressure-levels` (850 hPa), final (expver 1) | Copernicus C3S CDS | CC-BY 4.0 | `~/.cdsapirc` | hindsight | no |
| FIRMS | MODIS Collection 6.1 standard processing (`MODIS_SP`) | NASA FIRMS | NASA Earth science data, no restrictions | FIRMS area API, MAP key from env | assumed pass + 3 h | AOI file only (already in repo) |
| MCD64A1 | v6.1, via Earth Engine `MODIS/061/MCD64A1` | NASA LP DAAC | no restrictions on use or redistribution (LP DAAC statement) | Earth Engine export | hindsight, monthly | two small GeoTIFFs (already in repo) |
| IMERG | GPM_3IMERGHH V07 (Final), `…HHE` (Early), `…HHL` (Late) | NASA GES DISC | NASA Earth science data | **blocked: HTTP 403** | Early about 4 h, Late about 14 h, Final about 3.5 months (nominal) | no |
| HLS L30 | HLSL30 v2.0 | NASA LP DAAC | NASA Earth science data, no restrictions | Earthdata bearer token from env | archive, hindsight | no |
| HLS S30 | HLSS30 v2.0 | NASA LP DAAC | same | not used; starts 2015-11-28 | n/a | no |
| SMAP | SPL3SMP v009 (36 km); SPL3SMP_E v006 (9 km) | NASA NSIDC DAAC | NASA Earth science data | Earthdata bearer token from env | about 48 to 50 h (nominal) | no |
| MAIAC | MCD19A2 v061 | NASA LP DAAC | same | metadata only | reprocessed, hindsight | no |

## Credentials

- The Earthdata token is read from the `EARTHDATA_TOKEN` environment variable only. No code prints,
  logs or writes it. `src/earthlab/m5/fetch.py` sends it on the first request only. It drops it on the redirect.
  A test checks that errors do not contain it.
- The FIRMS key is read from `FIRMS_API_KEY` only. The CDS key is read by `cdsapi` from `~/.cdsapirc`.
- An Earthdata token expires. Re-issue it in Earthdata Login if a download returns HTTP 401.

## Authority for the pilot downloads

The M5 brief of 2026-11-03 says: small pilot downloads of free, openly licensed data are approved;
a download over about 5 GB, or a change of provider permissions, needs the owner. This is an
instruction relayed to the session. It is not a signed `HumanApproval` record. Every receipt
carries this text in its `authority` field. Total downloaded so far: about 0.4 GB, listed in
`docs/m5/receipts/`.

## Attribution lines for any figure or video

- NEA: "Contains information from Historical 1-hr PM2.5 accessed from data.gov.sg, made available
  under the terms of the Singapore Open Data Licence version 1.0."
- ERA5: "Contains modified Copernicus Climate Change Service information (ERA5)."
- NASA products: cite the product DOI and the DAAC. SMAP L3: NSIDC. HLS: LP DAAC.
  FIRMS: MODIS Collection 6.1 active fire product distributed by NASA FIRMS.
- Exact DOIs for HLS and SMAP are not checked in this branch. Check them before publication.

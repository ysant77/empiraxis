# M5 video hand-off: validated real layers

Date: 2026-11-03. Machine-readable list: `docs/m5/layers_manifest.json`.
Rule for the film: show only values that a source file holds. Do not draw measurement pixels, wind
vectors between points, smoke plumes or interpolation. Label hindsight data as hindsight.

## Fit for a video now

| Layer | What is real | Required on-screen label | Do not |
|---|---|---|---|
| NEA regional PM2.5, Sep to Oct 2015 | hourly values for five regions, `data/nea/` | "NEA Historical 1-hr PM2.5, five regions" and the attribution line in `data/nea/manifest.json` | say "stations"; say PSI or AQI |
| FIRMS MODIS detections, Sep to Oct 2015 | 10,257 detections in the Kalimantan box (`data/kalimantan-2015/`); box A, B, C files are local only | "thermal anomaly detections" | say burned area, emissions or "source of the haze" |
| ERA5 850 hPa wind, box-to-Singapore corridor means | hourly (u, v) per box from `runs/haze-2015/extract_850hpa.json` (local only) | "ERA5 reanalysis, made later (hindsight)" | draw a gridded wind field from these; they are corridor means |
| MCD64A1 burned area, September 2015 | 500 m raster, valid land 0.970 | "MODIS MCD64A1 v6.1, mapped burned area" | show October: valid land is 0.460 and the gate fails |

Use `earthlab.m5.layers.read_fire_points` and `read_wind_vector` to pull exact values for a chosen UTC day or hour.

## Real results that can be shown

- The 2015 ablation: persistence 30.76, ridge 32.10, + ERA5 36.73, + FIRMS 41.75 µg/m³. Say "no gain".
  Never place these next to M3 numbers.
- M5 ladder on the held-out 2019 season (`docs/m5/results/m5_ladder_stage_t.json`). All hours: ridge on history
  beats persistence by 13%; FIRMS features make it 13% worse. Elevated hours: FIRMS features cut the error by 39%.
  Label the last number "exploratory, one season, not a supported gain".

## Not fit for a video

| Layer | Reason |
|---|---|
| HLS L30 imagery | 2.7% clear land on both dates; high-aerosol flag on more than 96% of pixels |
| SMAP soil moisture | no recommended-quality retrieval over the Kalimantan box |
| IMERG rainfall | blocked: the owner must authorise the GES DISC app in Earthdata Login |
| MAIAC aerosol | not assessed |
| MCD64A1 October 2015 | fails the 0.80 valid-land gate |
| Prithvi BurnScars chip | a US scene; says nothing about Kalimantan |

If a film needs a rainfall or soil-moisture scene, call it "proposed research", not a result.

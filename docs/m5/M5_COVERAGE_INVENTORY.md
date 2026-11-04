# M5 coverage inventory, 2015 to 2026

Built from NASA CMR catalogue counts (metadata only; no granule was downloaded for this table) and from the local NEA file. 2026 is a partial year. NEA years from 2024 are sealed and are not reported. Counts are granules, not data quality. Regenerate with `scripts/m5_coverage_inventory.py`, `scripts/m5_nea_completeness.py` and `scripts/m5_coverage_report.py`.

## Granules over the Kalimantan study box, August to November

| Product | 2015 | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| HLSL30 | 53 | 45 | 44 | 49 | 52 | 41 | 37 | 88 | 105 | 92 | 92 | 81 |
| HLSS30 | 0 | 45 | 84 | 117 | 124 | 104 | 91 | 97 | 106 | 100 | 128 | 92 |
| MAIAC_MCD19A2 | 122 | 122 | 122 | 122 | 122 | 122 | 122 | 122 | 122 | 122 | 122 | 93 |
| MCD64A1 | 4 | 4 | 4 | 4 | 4 | 4 | 4 | 4 | 4 | 4 | 4 | 1 |
| SMAP_L3_36km | 122 | 121 | 122 | 122 | 122 | 122 | 122 | 76 | 122 | 122 | 122 | 94 |
| SMAP_L3_9km | 122 | 121 | 122 | 122 | 122 | 122 | 122 | 76 | 122 | 122 | 122 | 92 |

HLSS30 has no 2015 granule: S30 starts in late 2015-11. MCD64A1 has one granule per month, so four in the season. SMAP shows 76 of about 122 daily granules in 2022.

## Global gridded products, August to November (granules)

| Product | 2015 | 2016 | 2017 | 2018 | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| IMERG_Early | 5856 | 5856 | 5856 | 5856 | 5856 | 5856 | 5856 | 5856 | 5856 | 5856 | 5856 | 4528 |
| IMERG_Final | 5856 | 5856 | 5856 | 5856 | 5856 | 5856 | 5856 | 5856 | 5856 | 5856 | 2928 | 0 |
| IMERG_Late | 5856 | 5856 | 5856 | 5856 | 5856 | 5856 | 5856 | 5856 | 5856 | 5856 | 5856 | 4508 |

Nominal count is 5,856 (48 per day for 122 days). IMERG V07 Final ends on 2025-09-30: it has 2,928 granules in 2025 and none in 2026. Early and Late continue.

## HLS L30 and S30 over the Kalimantan box, August to November

`cloud_cover` is the provider's value. It does not measure smoke haze. In 2015 the Fmask high-aerosol flag covered more than 96% of the pilot pixels.

| Product | Year | Scenes | Mean provider cloud % | Scenes with cloud ≤ 20% |
|---|---|---|---|---|
| HLSL30 | 2015 | 53 | 55.1 | 14 |
| HLSL30 | 2016 | 45 | 75.4 | 5 |
| HLSL30 | 2017 | 44 | 70.7 | 1 |
| HLSL30 | 2018 | 49 | 54.7 | 9 |
| HLSL30 | 2019 | 52 | 55.1 | 11 |
| HLSL30 | 2020 | 41 | 75.7 | 1 |
| HLSL30 | 2021 | 37 | 77.3 | 1 |
| HLSL30 | 2022 | 88 | 81.9 | 1 |
| HLSL30 | 2023 | 105 | 47.2 | 33 |
| HLSL30 | 2024 | 92 | 66.5 | 4 |
| HLSL30 | 2025 | 92 | 73.8 | 6 |
| HLSL30 | 2026 | 81 | 35.3 | 40 |
| HLSS30 | 2015 | 0 | nan | 0 |
| HLSS30 | 2016 | 45 | 65.3 | 8 |
| HLSS30 | 2017 | 84 | 76.1 | 0 |
| HLSS30 | 2018 | 117 | 63.9 | 10 |
| HLSS30 | 2019 | 124 | 57.4 | 16 |
| HLSS30 | 2020 | 104 | 68.7 | 7 |
| HLSS30 | 2021 | 91 | 78.9 | 1 |
| HLSS30 | 2022 | 97 | 68.4 | 2 |
| HLSS30 | 2023 | 106 | 52.1 | 20 |
| HLSS30 | 2024 | 100 | 63.4 | 2 |
| HLSS30 | 2025 | 128 | 67.5 | 3 |
| HLSS30 | 2026 | 92 | 42.3 | 32 |

## NEA regional PM2.5 completeness (open years)

| Year | Hours with a value per region (of grid hours) | Missing fraction |
|---|---|---|
| 2014 | 6599 / 6599 / 6599 / 6599 / 6599 | 0.0000 / 0.0000 / 0.0000 / 0.0000 / 0.0000 |
| 2015 | 8760 / 8760 / 8760 / 8760 / 8760 | 0.0000 / 0.0000 / 0.0000 / 0.0000 / 0.0000 |
| 2016 | 8780 / 8780 / 8780 / 8780 / 8780 | 0.0005 / 0.0005 / 0.0005 / 0.0005 / 0.0005 |
| 2017 | 8760 / 8760 / 8760 / 8760 / 8760 | 0.0000 / 0.0000 / 0.0000 / 0.0000 / 0.0000 |
| 2018 | 8756 / 8756 / 8756 / 8756 / 8756 | 0.0005 / 0.0005 / 0.0005 / 0.0005 / 0.0005 |
| 2019 | 8760 / 8760 / 8760 / 8760 / 8760 | 0.0000 / 0.0000 / 0.0000 / 0.0000 / 0.0000 |
| 2020 | 8784 / 8784 / 8784 / 8784 / 8784 | 0.0000 / 0.0000 / 0.0000 / 0.0000 / 0.0000 |
| 2021 | 8760 / 8760 / 8760 / 8760 / 8760 | 0.0000 / 0.0000 / 0.0000 / 0.0000 / 0.0000 |
| 2022 | 8760 / 8760 / 8760 / 8760 / 8760 | 0.0000 / 0.0000 / 0.0000 / 0.0000 / 0.0000 |
| 2023 | 8760 / 8760 / 8760 / 8760 / 8760 | 0.0000 / 0.0000 / 0.0000 / 0.0000 / 0.0000 |

Region order: north, south, east, west, central. Years 2016 and 2018 have the excluded labels listed in `forecast/dataset.py`.

## Other areas

Counts for the Singapore receptor box and source boxes A, B and C are in `docs/m5/coverage/coverage_inventory.csv`. FIRMS and ERA5 have no CMR record; ERA5 covers 1940 to now, the FIRMS MODIS archive covers 2000 to now.

# Licensing

## Project code and documents

The original Empiraxis source code and the project-authored documents are licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE).

- The grant covers only material that the project author has the right to license.
- It does not change upstream notices or third-party terms.
- External code copied into this repository keeps its own licence and notices.
- The Python package and CLI keep the name `earthlab`. The licence is the same.

## Third-party data

These sources keep their own terms. The Apache-2.0 licence does not apply to them.

| Source | Terms | In this repository |
|---|---|---|
| NEA Historical 1-hr PM2.5 (data.gov.sg) | Singapore Open Data Licence v1.0. See [data/nea/DATA_CARD.md](data/nea/DATA_CARD.md). | `data/nea/Historical1hrPM2.5.csv` |
| ERA5 (Copernicus Climate Change Service) | CC-BY 4.0. Attribution: "Contains modified Copernicus Climate Change Service information (ERA5)." | Derived values and receipts only |
| NASA FIRMS, MCD64A1, IMERG, HLS, SMAP, MAIAC | NASA Earth science data terms, as recorded in [docs/m5/M5_SOURCE_AND_LICENCE_REGISTER.md](docs/m5/M5_SOURCE_AND_LICENCE_REGISTER.md) | FIRMS area file, two small MCD64A1 GeoTIFFs, receipts |
| HLS Burn Scars dataset | CC-BY-4.0, as reported by the source catalogue | Not redistributed |

Attribution lines for figures and the film are in the M5 source and licence register.

## Models

No model weights are in this repository. Each model keeps its own licence and usage policy. The software licence gives no rights to third-party weights, model outputs or trademarks.

| Model | Role in the project | Terms |
|---|---|---|
| Muse Glimmer 30B (Meta) | Planner seats: PM and Lead, and specialist seats in M3 | Apache-2.0 and the Meta usage policy |
| Muse Spark Open (Meta, hosted) | Configured endpoint | Provider terms and the Meta licence |
| Llama 3.2 3B Instruct (Meta) | M4 and M4.1 specialist seats, M4 critic | Llama 3.2 Community License |
| Llama Guard 3 8B (Meta) | Safety check in the investigation path | Llama 3.1 Community License |
| Qwen3 4B Instruct 2507 (non-Meta) | M4.1 ML specialist seat | Apache-2.0, as stated on the model card |
| Prithvi BurnScars (pretrained) | One Level A chip inference | Apache-2.0, as reported by the source catalogue |
| Kokoro v1.0 | Narration voice of the film | Apache-2.0 |

Check each model card again before a new release. A model card can change.

## Python dependencies

Each package keeps its own licence. The exact versions are in `uv.lock`.

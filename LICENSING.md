# Licensing scope — proposed for owner approval

This is a **draft licensing proposal**, not a claim that every file or external artifact in this repository is owned by the project.

## Original software

Original Axiom EarthLab software source code and project-authored documentation are proposed to be distributed under the Apache License, Version 2.0. See [LICENSE](LICENSE). This grant covers only material for which the copyright holder has the right to grant a license. It does not override upstream notices or third-party terms. Any external software copied into this repository must retain its original license and notices.

## Data, pretrained models and third-party materials

- **Singapore NEA PM2.5 data**: `data/nea/Historical1hrPM2.5.csv` is attributed under the **Singapore Open Data Licence v1.0**, as documented in [data/nea/DATA_CARD.md](data/nea/DATA_CARD.md). It is not being relicensed under Apache-2.0.
- **ERA5, FIRMS, MCD64A1 and other geospatial inputs**: their respective providers' terms apply; source and provenance records govern use.
- **Prithvi pretrained weights**: an external pretrained model with its own terms (the source catalogue reports Apache-2.0). Axiom EarthLab does not assert authorship or automatically redistribute weights.
- **HLS Burn Scars dataset**: the source catalogue reports CC-BY-4.0, independently of the software license. The dataset is not automatically redistributed.
- **Meta models and safety models**: separate model licenses and usage policies apply. The software license does not grant rights to third-party weights, model outputs or trademarks.
- **Python dependencies**: retain their respective upstream licenses.

## Publication checklist

Before changing repository visibility, the owner should verify:
1. They own or are authorized to license the project-authored code and documents, including any contributions.
2. All bundled datasets, images, icons, and screenshots can be redistributed under their own licenses.
3. Published commits, history, run artifacts and screenshots do not disclose credentials, private local paths or personal data unintentionally.
4. Source requirements of the hackathon, research institution and any employer are satisfied.
5. The chosen project license and copyright notice are intentionally approved.

The repository may remain private while a public, replay-only Streamlit app is published separately.

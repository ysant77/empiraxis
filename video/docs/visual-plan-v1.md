# Empiraxis — cinematic replay: visual implementation plan

## Approach

A self-contained replay page, now `video/replay/` in this repository. It reads recorded artifacts only. It calls no model, trains nothing and changes no evidence. The release `4e4a4f1` stays frozen.

- **Stack:** one HTML page, plain JS and CSS, and MapLibre GL 5.6.1 with globe projection.
- **Data:** `build_data.py` writes `data.js` from these sources:
  - `examples/replay/scenario-muse-method-comparison/trace.jsonl` and `result.json`, at release `4e4a4f1`;
  - the run 95e7a3 acquisition receipt and its capture log;
  - the prediction ledger;
  - FIRMS MODIS manifests and CSVs for the three 2015 study boxes;
  - NEA station coordinates;
  - the NEA PM2.5 file.
- **Two modes:**
  - **Interactive:** play, scrub, hover. Feed rows show the full trace record, and tool chips list the trace records that called them.
  - **Capture (`?capture=1`):** a deterministic `seek(t)` that waits for map tiles. Playwright renders it frame by frame at 1920×1080, 30 fps.

## Scenes

| Scene | Time | What is real | Labels on screen |
|---|---|---|---|
| Earth View | 0:00–0:18 | 84,224 FIRMS MODIS detections build up by date inside the three study boxes from their manifests. NEA region points. The 471 µg/m³ hourly peak on 19 Oct 2015 from the NEA file. | "REAL DATA · NASA FIRMS + NEA". Legend: "Basemap: NASA Blue Marble (modern composite, not 2015 imagery) · context only, not smoke-source attribution". No smoke trajectories. |
| Problem + logo | 0:18–0:34 | Kinetic type over a dimming globe. | No claim. |
| Council View | 0:34–1:22 | All 52 trace records in their recorded order. Role cards light on their own `model_turn` records. The REFUSED / VALID stamps come from `proposal_reviewed`. The lifecycle stepper follows `harness_transition`. Call and token counters sum the recorded usage, reaching 12 calls and 22,516 tokens. Popovers show recorded proposals verbatim: #14 strategy, #16 TCN configuration, #33 reload check. | "FOUR ROLES · ONE LOCAL MODEL — not four independent models". Tags: MODEL PROPOSAL, CODE EXECUTION, RECORDED REPLAY · NOT LIVE. |
| Evidence View | 1:22–1:44 | MAE bars on an axis from 0 to 6: 4.680, 4.697, 4.711 and 5.465. Elevated-hour bars: 30.25, 30.58, 32.43 and 26.32. Reload checks 0.0 / 0.0. Skill 0.142 [0.132, 0.151]. The Lead's recorded `recommend` reason from trace #42. | HISTORICAL VALIDATION 2019–2023 · REUSED YEARS. CODE RULE ✓ matches. HUMAN APPROVAL PENDING. |
| Human gate | 1:44–1:50 | Authentic dark-theme capture of the Control Room at the release tree: "Human decision pending". | REAL UI · RECORDED RUN. |
| Signed data | 1:50–2:02 | An exact grid: 3 days × 5 regions × 24 hours, with the real missing hours dashed and the 17 real mismatches red, all on 15 Nov 2023. | REAL RUN RECORD. |
| Negative results | 2:02–2:11 | Crops of the real S2, S3 and S4 decision panels. | REAL STUDIES · RECORDED. |
| Proof | 2:11–2:21 | Real trace hash prefixes. The 5 ledger predictions against the observed values. | REAL TRACE + REAL LEDGER. MAE 7.2 · n = 5 · not evidence of forecast skill. |
| Close + credits | 2:21–2:35 | Back out to the globe. Credits list every role, model and data source. | Music and voice credits. |

## Audio

- **Narration:** Kokoro v1.0 (Apache-2.0), voice `af_heart`, rendered locally. There are no subtitles.
- **Music:** generated locally with Meta MusicGen-medium (CC-BY-NC 4.0 weights): a dark ambient intro, then an uplifting electronic bed from the logo reveal. Sidechain ducking keeps the music under the voice. The mix is normalised to −15 LUFS with a −1.5 dBTP true peak.

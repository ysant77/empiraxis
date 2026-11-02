# Four-scenario demonstration

The four scenarios are in `examples/replay/` as `scenario-s1-regression`, `scenario-s2-encoder-reuse`, `scenario-s3-transport` and `scenario-s4-resource-request`. `scripts/build_scenario_fixture.py` writes them from saved results. No model runs in this step, and no number is typed by hand. Each scenario opens on all three surfaces with one run name, one trace head and one `result.json` digest.

## Labels

| Scenario | What ran | Science label | Trace | Open work |
|---|---|---|---|---|
| S1 | Real execution, recorded replay | Simulated-availability hindcast | The run's own trace | Human decision on the model |
| S2 | Real execution, recorded results | Simulated-availability hindcast | Packaging trace | None |
| S3 | Retrospective reanalysis, recorded results | Hindsight diagnostic | Packaging trace | None |
| S4 | Real execution, recorded replay, no segmentation model ran | Historical raster analysis | The run's own trace | Human decision on the request: no signed approval exists |

S2 and S3 came from jobs that wrote reports and no run trace. Their trace records the packaging step and the digest of each source. It does not claim that the job ran again.

## Results

| Scenario | Decision | Evidence |
|---|---|---|
| S1, PM2.5 at T+6 h | `adopt_limited` for the GRU, by the code rule | Validation MAE: GRU 4.588, lagged ridge 4.680, persistence 5.465. Above 55 µg/m³ the GRU is worse than persistence: 28.772 against 26.324. Do not rely on it in elevated hours. The elevated-hour rule is exploratory. A separate verified bundle, `s1-ridge`, reproduced its predictions with a largest difference of 0.0. Its readiness is `research`, and `production_ready` is false. |
| S2, exceedance above 35 µg/m³ | `retain_baseline` | Frozen-GRU reuse ran, with F1 0.255 against 0.162 for logistic. The persistence alarm has F1 0.306, and the hybrid's F1 gain limits are −0.165 to −0.001. Reuse worked, and adoption is not justified. Hybrid inference is refused, because no single verified bundle loads it. |
| S3, wind, rain and fire, 2015 | `abstain`, inconclusive | No box reached consistent. Box B at 850 hPa passed in 91% of event onsets and 72% of clean hours. ERA5 is hindsight. This is not a forecast and not an attribution. |
| S4, burn-scar segmentation | `request_resource` | The inputs do not fit: 500 m MCD64A1 has no six-band imagery and no reference masks. The chips cover Texas, not the Kalimantan box. No segmentation score exists. The request names six-band HLS for the box and a signed approval for the weights. |

S4 stops at the human gate. The signed approval is an owner action, and this demonstration does not show one.

## Demo sequence

1. Start the replay interface. It calls no model.

   ```bash
   uv run --extra ui streamlit run src/earthlab/ui/app.py --server.address 127.0.0.1
   ```

2. Open `?view=workspace&run=replay/scenario-s1-regression`. Read the caption: what ran, the science label and the digest. Show the MAE table and the elevated-hour limit.
3. Use the links in the run panel to open the same run in the Control Room and the Engineering Lab. Show that the run name, trace head and digest are the same.
4. Select S2. Say that reuse ran and that the correct decision is to keep persistence.
5. Select S3. Say that the correct decision is to abstain. Name no source.
6. Select S4. Show the request and the open human gate.
7. In a terminal, replay the verified investigations and show the hash chain check.

   ```bash
   uv run earthlab --data-dir data/nea replay examples/replay/live-september-verified
   ```

## What not to say

- Do not call any model production-ready.
- Do not say S1 forecasts PM2.5. The NEA file has no available-at time, so S1 and S2 are simulated-availability hindcasts on validation years.
- Do not say S3 attributes haze to a source.
- Do not say S4 was approved, or that any segmentation ran.

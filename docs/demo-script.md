# Demo script (3 minutes)

This script uses recorded runs, because one live run takes about 10 minutes on the development Mac.
State this in the video. A label on each screen shows that a run is a recorded replay.

## Setup

Start the replay interface. It calls no model:

```bash
uv run --extra ui streamlit run src/earthlab/ui/app.py --server.address 127.0.0.1
```

## Script

| Time | Screen | Say |
|---|---|---|
| 0:00 | Research Workspace | Axiom EarthLab is a research prototype. It studies the 2015 Kalimantan fires and the Singapore haze. It is not a forecast and it gives no health advice. Models plan. Code checks every number. |
| 0:25 | Saved runs, `replay/live-september-verified` | The question goes to Muse Glimmer, which writes a typed brief. Python checks the brief and hands one bounded task to the engineer role. The engineer can use approved read-only tools only. |
| 1:10 | Verified values block | This value is 77,426 hectares, with a valid fraction of 0.970144. The independent verifier recomputed both values from the source raster. The model text holds no numbers. |
| 1:45 | Saved runs, `replay/live-october-abstained` | The same question for October stops. The valid fraction is 0.4597 and the gate is 0.8. The system shows no area. This abstention is a correct result. |
| 2:10 | Control Room, then a terminal | Each run has a hash-chained trace. The replay command repeats the checks without a model: |
| 2:35 | Comparison table | The direct investigator was the fastest arm. The PM route added latency, and we saw no accuracy difference in these few runs. So the PM route stays experimental. We do not claim that one topology is better. |

Replay command for the 2:10 step:

```bash
uv run earthlab --data-dir data/nea replay examples/replay/live-september-verified
```

## What not to say

- Do not say that the system attributes haze to a source. H1 shows transport plausibility only.
- Do not say that FIRMS detections are burned area.
- Do not say that the system forecasts PM2.5.
- Do not call the A2A work conformant, unless a conformance test passed.

# Submission text package (draft for the owner)

Status: **draft. Not submitted.** The owner submits through the portal and keeps the receipt.
Every number here is in `docs/release/source_to_screen.csv` or in the trace that the row names.
The M4.1 fields come from the benchmark report `docs/m41/m41-benchmark-report.md` (PR #117).

## Title

Empiraxis: AI-directed scientific engineering, evidence before conclusions

## One-line pitch

Meta open-weight models plan environmental studies; code runs and scores them; a person decides, and the system records when the answer is "the extra data did not help".

Central message: Empiraxis explores how AI agents can coordinate reproducible scientific engineering, with evidence and deterministic verification determining what conclusions are justified.

## Problem and approach (150 words)

Language models can write a confident scientific answer that no experiment supports. Empiraxis tests a different arrangement on the 2015 and 2019 Southeast Asian haze. Meta open-weight models do the planning: they scope the question, choose a method and propose the next step. They do not compute results. Allowlisted tools get the data and train the models. Separate evaluator code scores every candidate against simple baselines such as persistence. A hash-chained trace records each model call, tool call and checkpoint hash. A person makes the final decision. The allowed outcomes include "train", "keep the baseline", "abstain" and "request better data". The project keeps its negative results. In the multisource pilot, satellite fire counts, reanalysis wind and satellite rain did not give a supported gain over PM2.5 history. A team of models reached the same decision as a deterministic pipeline, at a higher cost. Both results are part of the submission.

(150 words. Count again after any edit.)

## Real Meta model participation

| Model | Where it ran | What it did | Evidence |
|---|---|---|---|
| Muse Glimmer 30B (GGUF Q4_K_M, Apache-2.0) | Local, llama.cpp `llama-server` | Product manager and Lead seats: scope, method, review, recommendation. In the M3 team runs it also filled the data and ML specialist seats. | `examples/replay/scenario-m4-heterogeneous-council/trace.jsonl` (`role_binding`, checkpoint SHA-256 `4cc57c0f5104...`); `scenario-muse-*` replays |
| Llama 3.2 3B Instruct (GGUF Q4_K_M, Llama 3.2 Community License) | Local, llama.cpp | M4 run: data specialist, ML specialist and advisory critic seats. M4.1 benchmark: data specialist seat in arms H and HC. | Same trace, checkpoint SHA-256 `6c1a2b411610...`; `docs/m41/evidence/m41-v2-benchmark.json` |
| Qwen3 4B Instruct 2507 (GGUF, Apache-2.0; non-Meta, secondary seat) | Local, llama.cpp | M4.1 benchmark: ML specialist seat in arms H and HC | `examples/assess/replay/20261104T060024Z-HC-e-m5-handoff-v2-r1`, checkpoint SHA-256 `3605803b982c...` |
| Llama Guard 3 8B | Local, Ollama | Safety check on questions and answers in the investigation path only | README "Safety gate"; in-sample 16 cases |

Counts from the recorded M4 run (`scenario-m4-heterogeneous-council`): 13 model calls on 2 checkpoints. Muse 8 (PM 2, Lead 6). Llama 3.2 3B 5 (data 2, ML 2, critic 1).

What the models did **not** do:

- The M5 environmental models (ridge, trees, calibrated event models) are deterministic Python on CPU. No Meta model produced an M5 number.
- The M4.1 council read the frozen M5 evidence package afterwards and critiqued it. It did not re-run M5. In the M4.1 benchmark (`docs/m41/m41-benchmark-report.md`), the code rule, Muse alone and Muse in every seat were correct on 5 of 5 packages. The mixed council (Llama 3.2 3B, Qwen3 4B, Muse Glimmer 30B), with or without the Muse critic, was correct on 4 of 5.
- The critic is advisory. It sets no score, outcome or approval.
- No human approval is shown in the recorded runs. Each run stops at "awaiting a human decision".

## Findings, with caveats

1. **Multisource data did not give a supported gain (M5).** On the held-out 2019 haze season (6,930 region-hours), ridge on PM2.5 lags had MAE 9.87 µg/m³ against 11.33 for persistence. Adding FIRMS fire features raised the all-hours MAE to 11.21 (frozen label: worse). Caveats: FIRMS data is the MODIS standard-processing archive with a nominal latency, assumed at 3 h; the release time was not measured. Do not call FIRMS "issue-time valid". The package `m5-evidence-5` (PR #120, on `main` at `0c564e8`) corrects the label to `nominal_latency_assumed`. No M5 source has a verified publication time per observation. The 2019 season was also used by earlier work and by M5-C, so it is not an independent test.
2. **One exploratory signal.** On elevated hours (above 55 µg/m³, 588 hours on 17 days) FIRMS features lowered MAE from 28.16 to 17.27. Trees on lags only also lowered it (to 23.76), so part of the effect may come from training on the 2015 haze. Exploratory. Not a claim.
3. **The 2015 negative ablation reproduces exactly.** MAE: persistence 30.76, ridge 32.10, ridge + ERA5 36.73, ridge + ERA5 + FIRMS 41.75 µg/m³. ERA5 is hindsight data. Not a causal statement.
4. **Event 12 to 24 h ahead (M5-C, 2019): the skill comes from PM2.5 lags.** Brier skill 0.425 (lags) and 0.474 (lags + FIRMS) against the training base rate. The FIRMS label passes the frozen rule by a small margin (calibration gap 0.093, limit 0.1) and fails with FIRMS delayed 24 h. All 349 events come from **one** connected episode. Not an operational warning. A post-hoc onset audit (PR #119, merged at `62fdc83`) finds that 279 of 349 events (80%) are continuations. There are only 4 independent onset episodes, below the declared threshold of 10: too few to judge onset skill.
4a. **M5-B (transport consistency 2017 to 2019): no result.** The ERA5 pressure-level files for 2017 to 2019 did not arrive from the data service. M5-B did not run. M5 is frozen for this submission.
5. **Data suitability.** SMAP had no recommended-quality retrieval over the Kalimantan box. HLS had 2.7% clear land on the two dates. These results apply to these footprints and dates only.
6. **Recorded scenarios (validation years, sealed test period not read).** S1: a GRU had MAE 4.588 against 5.465 for persistence, but was worse above 55 µg/m³ (28.772 against 26.324), so "adopt with limits". S2: a reused encoder lost to a persistence alarm (F1 0.255 against 0.306), so the baseline stays. S3: no box was consistent (0 of 6), so the system abstains. S4: the imagery did not fit, so the system requests resources.
7. **No multi-agent advantage in this five-case evaluation.** The earlier comparison found a team of models reached the same decision as the deterministic pipeline, at higher cost (`docs/comparative-evidence-report.md`). The M4.1 benchmark confirms this. Arms F, S and T were correct on 5 of 5 packages; the mixed council H and HC on 4 of 5, at higher cost (HC: 91,601 tokens and 91 minutes; S: 14,070 tokens and 26 minutes). The Muse critic found 1 of 12 seeded faults with support. It runs on the Lead's checkpoint and is not independent.

## Architecture (diagram description)

Left to right: a research question goes to the safety gate. The Muse PM seat scopes it. The Muse Lead seat chooses a method. Specialist seats (Muse or Llama 3.2 3B) call allowlisted tools only. Tools read hash-checked data and train models in deterministic code. Independent evaluator code scores every candidate against baselines and applies a pre-registered rule. An advisory critic may comment. Every step goes into a hash-chained trace with checkpoint hashes. A human decision gate is last. The replay UI (Research Workspace, Engineering Lab, Control Room) reads the recorded traces and calls no model.

## Demo steps (replay, no model, no key, no network after install)

1. `git clone https://github.com/ysant77/empiraxis.git` then `cd empiraxis`.
2. `uv sync --all-extras`
3. `uv run --extra ui streamlit run src/earthlab/ui/app.py --server.address 127.0.0.1`
4. Open `?view=workspace&run=replay/scenario-s1-regression`, then S2, S3, S4.
5. Open `?view=control&run=replay/scenario-m4-heterogeneous-council` to see each seat, its checkpoint file and SHA-256.
6. Check a run offline: `uv run earthlab --data-dir data/nea replay examples/replay/scenario-m4-heterogeneous-council` (exit 0; a changed file exits 1).

## Video

- Primary: Video 2.0 from Session C, if the owner approves it before the cutoff. `[VIDEO 2.0 PENDING: file, SHA-256, duration]`
- Fallback: `Empiraxis_V1_1_voice_only.mp4` (2:49, 1920×1080, SHA-256 `fd54e3d26145ecf8a38442667b3f99f3dde4172165f8710a0c0480c5b647af4d`). It is the V1.1 picture with the Kokoro narration only and no music. Its credits say "no music". It shows M3 only, not M4, M4.1 or M5.

## Credits and licences

| Item | Licence or terms |
|---|---|
| Empiraxis source code and documents | Apache-2.0 (`LICENSE`, `LICENSING.md`) |
| NEA historical 1-hour PM2.5 | Singapore Open Data Licence v1.0 |
| NASA FIRMS MODIS, MCD64A1, HLS, SMAP, IMERG | NASA Earthdata terms; see `docs/m5/M5_SOURCE_AND_LICENCE_REGISTER.md` |
| ERA5 | Copernicus licence (C3S) |
| Muse Glimmer 30B | Apache-2.0 (model card; see `LICENSING.md` for the source of each licence) |
| Llama 3.2 3B Instruct | Llama 3.2 Community License |
| Llama Guard 3 8B | Llama 3.1 Community License |
| Qwen3 4B Instruct 2507 (non-Meta, M4.1 ML specialist seat) | Apache-2.0, as stated on the model card |
| Narration voice | Kokoro v1.0 (Apache-2.0), generated locally |
| Music | None in the release cut, or a track whose licence the owner has verified |
| Python dependencies | Each package's own licence (`uv.lock`) |

Engineering disclosure: one developer, with AI-assisted engineering under the developer's review (README, "Engineering disclosure").

## Link checklist

- [ ] Repository URL `https://github.com/ysant77/empiraxis` opens without login (public; the owner confirmed this is intended).
- [ ] Release commit: owner picks one (see the release QA report).
- [ ] Video URL plays without login, and the file matches its SHA-256.
- [ ] Hosted replay URL, if published (`docs/hosted-replay.md`). Not published at last check.
- [ ] Portal deadline and time zone read from the portal itself.
- [ ] Portal confirmation screenshot or receipt saved.

## Known blockers

See `docs/release/release-qa-report.md`, section "Blockers".

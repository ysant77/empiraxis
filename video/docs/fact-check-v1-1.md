# Empiraxis Video V1.1: attribution and fact check

V1.1 is a focused polish of V1. V1 stays unchanged as the fallback. The films are kept outside Git; `video/README.md` lists their SHA-256.

## Changes from V1

| Change | V1 | V1.1 |
|---|---|---|
| Opening question | none | "Can wind, rainfall and regional fires help us understand and predict Singapore's haze episodes?" |
| 2015 ablation | not shown | a real, completed result, labelled as separate from M3 |
| Problem line | "An AI agent can build a model in minutes." | "Training a model takes minutes. Knowing whether to trust it takes evidence." |
| Council section | 0:34–1:22 (48 s) | 0:48–1:12 (24 s) |
| Training | one narration line | a 22 s scene from recorded run artifacts |
| M5 | none | a teaser labelled "PROPOSED RESEARCH · NOT YET RUN · NO RESULTS" |
| Captions | sidecar SRT | sidecar SRT plus a separate burned-caption render |
| Mobile readability | numbers 24 px | evidence numbers 30–44 px |

## On-screen numbers and their sources

Each line gives the source file first, then the values taken from it.

**2015 ablation**
- Source: `docs/evidence/haze-2015-ablation.json` and `docs/haze-2015-ablation-results.md` at 4e4a4f1.
- MAE values: 30.76 / 32.10 / 36.73 / 41.75 µg/m³.
- Scope: 5,195 region-hours, 18 Sep – 31 Oct 2015, T+6 h.
- On-screen labels: "deterministic, no AI model" and "ERA5 is reanalysis: association, not issue-time skill".

**Ridge rolling-origin folds**
- Source: run `829fed` / `rolling-origin-ridge.json`.
- Fold MAE at α 10,000 against persistence: 2016 6.44 vs 7.77; 2017 6.01 vs 7.36; 2018 5.42 vs 6.79.

**Penalty search**
- Source: `rolling-origin-ridge.json` and trace #32 (`mean_fold_mae` 5.957).
- Mean fold MAE by α:

  | α | 1 | 10 | 100 | 1,000 | 10,000 |
  |---|---|---|---|---|---|
  | Mean fold MAE | 6.107 | 6.105 | 6.090 | 6.014 | 5.957 |

- The film says that 10,000 is the top of the searched range.

**TCN configuration**
- Source: trace #16 (the proposal) and `train-candidate-1/job.json`.
- Values: 96 h window, 1 layer × 32, Huber loss, lr 0.001, batch 256, patience 3, max 10 epochs, seed 20261101.

**TCN training**
- Source: `train-candidate-1/training.json`.
- Values: 10,287 parameters, 8 epochs run, 176.9 s training, 8.685 s prediction.

**Loss curve**
- Source: `training.json` history, all 8 epochs, with no interpolation of new values.
- Best validation loss is 0.5744 at epoch 5. Early stopping came after 3 epochs without gain. Epochs 9–10 are shown as "not run".

**Reload checks**
- TCN: trace #33 and `verify.json`. Max |Δ| 0.0, 43,818 rows, sha256 af008771….
- Ridge: trace #32. Max |Δ| 0.0, weights 889b6be8….

**Memory peak**
- Source: `result.json` usage. Value: 383 MB (`peak_training_rss_mb` 382.7).

**Validation MAE and evidence values**
- Source: M3 `result.json` comparison.
- These are unchanged from V1: 4.680 / 4.697 / 4.711 / 5.465 µg/m³; above 55 µg/m³, 30.25 / 30.58 / 32.43 / 26.32.
- They are labelled "HISTORICAL VALIDATION 2019–2023 · REUSED YEARS".

**Recommendation and human gate**
- Trace #42 records retain_baseline → B4. The real UI shows "Human decision pending".

**Other scenes** (globe, signed data, negative results, proof)
- These use the same sources as V1. See `acceptance-check-v1.md`.

## Honesty checks

- ✓ M3 shows one model, Muse Glimmer 30B, in four roles: "FOUR ROLES · ONE LOCAL MODEL". Llama and Qwen do not appear in M3.
- ✓ The film states that trusted code trained the models and that Muse only proposed them.
- ✓ The 2015 ablation and the M3 validation are on separate screens, with separate labels and separate units of evidence.
- ✓ The M5 questions (M5-A, M5-B, M5-C) are shown as planned research with no results. The film claims no causal attribution and no operational forecast.
- ✓ The film has no smoke trajectories, interpolated measurement pixels or wind vectors. The basemap is labelled as a modern composite.
- ✓ The concept images (kept outside Git) were used for visual direction only. No concept pixels appear in the film.

## Measured checks on the final files

- **Runtime:** 2:49.2, which is under 3:00. The format is 1920×1080 at 30 fps.
- **Loudness:** −15.7 LUFS integrated, with an LRA of 2.7 LU.
- **Intelligibility:** faster-whisper transcribed the final mix. The word match is 0.92 against the 393 script words. All differences are number formatting, such as "10 000" for "ten thousand". The other differences are known ASR errors with names ("Mehta", "pyraxis"). No content word is wrong.
- **Timing:** the SRT cue times are the exact narration start and end times from `v4/timeline.json`.
- **Captions:** `Empiraxis_V1_1.srt` is a sidecar file. `Empiraxis_V1_1_captioned.mp4` is the same film with the captions burned in. The main file has no captions.
- **Music:** Meta MusicGen-medium, generated locally. The weights are CC-BY-NC 4.0, so the music is for non-commercial use only, and the credits name it. The intro bed is extended by one crossfaded repeat of the same generated audio.
- **Voice:** Kokoro v1.0 (Apache-2.0), voice `af_heart`, rendered locally.
- **Fallback:** V1 is unchanged. `video/README.md` lists its SHA-256.
- **Checksums:** the V1.1 checksums are in `V1_1_SHA256SUMS.txt`.

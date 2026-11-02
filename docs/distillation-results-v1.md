# Distillation on PM2.5: results

Protocol: `docs/science-model-tiers-protocol.md`, section 2. The decision rule was set before the runs. Distillation helped only if the lower 95% limit of paired MAE skill, distilled student against direct student, is above zero.

**Decision: distillation is not justified as a default.** The rule passed for 2 of 3 seeds and failed for 1. The gain is at most 0.05 µg/m³ of MAE. No student beats persistence in hours above 55 µg/m³.

All scores are on validation, 2019 to 2023, at T+6 h, over 5 regions. The test period stays sealed. This is a rehearsal of the method on small data. It is not a Prithvi result, and it says nothing about distillation in general.

## Models

| Model | Architecture | Parameters | Trained on | Seeds |
|---|---|---|---|---|
| Teacher | Mean of 3 GRU members, hidden 128, 2 layers | 3 × 156,303 | Labels, 2014 to 2018 | 20261101, 20261102, 20261103 |
| Direct student | GRU, hidden 8, 1 layer | 711 | Labels | 7, 11, 13 |
| Distilled student | GRU, hidden 8, 1 layer | 711 | Labels and teacher values, weight 0.5 | 7, 11, 13 |

The settings that both students share are:

- window 48 h;
- input offset 2 h;
- MAE loss;
- learning rate 0.001;
- batch 256;
- at most 12 epochs, patience 3.

Teacher values come only from train samples. Each direct and distilled pair uses the same seed and the same feature file (`features-5bcf09f8ccc2`).

## Paired result, T+6 h

| Seed | Direct MAE | Distilled MAE | Paired skill | 95% limits | Rule |
|---|---|---|---|---|---|
| 7 | 4.631 | 4.591 | 0.0086 | 0.0045 to 0.0111 | passed |
| 11 | 4.563 | 4.552 | 0.0022 | -0.0025 to 0.0061 | failed |
| 13 | 4.616 | 4.566 | 0.0109 | 0.0081 to 0.0140 | passed |

There are 219,090 paired samples per seed (43,818 issue times by 5 regions). The limits come from the evaluator's moving-block bootstrap of whole days.

I recomputed all three rows from the saved predictions with `earthlab.forecast.evaluator` and the pipeline's truth reader. Each value matched the recorded summary to four decimals.

## Context on the same validation period

| Model | MAE | Skill against persistence | MAE above 55 µg/m³ |
|---|---|---|---|
| Persistence | 5.465 | 0 | 26.32 |
| Lagged ridge | 4.680 | 0.144 | 30.25 |
| Teacher | 4.521 | 0.173 | 27.31 |
| Distilled students, 3 seeds | 4.552 to 4.591 | | 28.03 to 29.83 |
| Direct students, 3 seeds | 4.563 to 4.631 | | 29.99 to 32.45 |

Distillation moved the students toward the teacher. This shows best in hours above 55 µg/m³. But in those hours, every learned model, the teacher included, has a larger error than persistence.

## Cost

These times are from one shared Mac. They show scale, not a benchmark.

| Item | Measured |
|---|---|
| Teacher training, 3 members | 85.4 s, 114.9 s and 83.6 s; 283.9 s in total |
| Teacher prediction on validation | 3.7 s to 4.2 s per member; about 11.7 s for the ensemble |
| Student training | 12.5 s to 15.8 s |
| Student prediction on validation | 0.29 s to 0.31 s |

A distilled student predicts about 40 times faster than the ensemble. It costs one extra teacher training, about 284 s. The saving is about 11 s per validation-sized pass. So the teacher pays back after about 26 such passes.

That count includes no cost for keeping a teacher, and it does not apply to a direct student. A direct student is as fast as a distilled one and needs no teacher. The cost argument therefore compares the two students, and the accuracy gap between them is at most 0.05 µg/m³.

## Limits

- One feature set, one horizon and one teacher.
- Three seeds give counts, not a significance claim.
- Many models were scored on this validation period, so a small gain can come from selection.
- The cost figures are from one machine under swap pressure.

## Inputs

The run records are local, in `earthlab-e1-runs/`.

| File | SHA-256 |
|---|---|
| `tiers-seeds/summary.json` | `bde3b151446ce413ab158fd2971b6f02f5ac9b468255f810124f20cb69dd10b9` |
| `tiers/20261101T084420Z-bf4b1a/result.json` | `4b871ae5a288515303a559d84ddbb4fec1eee6fdf638647321f265732ad8b8e1` |
| `tiers/20261101T084420Z-bf4b1a/soft-teacher.npy` | `2f6da19b24c26dd51efa5a50d4b6ff11aed07b0809fa287aa420e15dd1450fc0` |

The teacher run is `uv run earthlab e1-tiers --no-model`. It used the preset with no model, so no Muse call took part. The seed study trained the two students with the job settings above, against the same teacher values.

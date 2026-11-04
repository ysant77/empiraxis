# M3 retrospective

M3 is the recorded run `20261103T061204Z-829fed`. Its replay is `examples/replay/scenario-muse-method-comparison`. This note changes no recorded file.

## What M3 was

- **One model.** All four roles were prompts to one local checkpoint, Meta Muse Glimmer 30B, served by llama.cpp. The roles were PM, Lead (Geospatial engineer), data specialist and ML specialist.
- **Not a multi-model system.** Different system prompts and different tool lists do not make different models. Do not call M3 multi-model.
- **No Llama and no Qwen.** No model call in M3 went to a Llama or a Qwen checkpoint.

## Recorded facts

| Item | Value | Source |
|---|---|---|
| Records in the trace | 52, head `6740b801` | `trace.jsonl` |
| Model turns | 12: Lead 5, PM 3, data specialist 2, ML specialist 2 | `model_turn` records |
| Tokens | 22,516 (14,428 prompt, 8,088 completion) | `result.json`, `usage` |
| Served model on every turn | `muse-glimmer-30B` | `model_turn.served_model` |
| Wall time | 2,222.7 s, of which 2,030.1 s model inference and 180.1 s training | `usage` |
| Recommendation | `retain_baseline`, model `B4_lagged_ridge` | `recommendation` |
| MAE (µg/m³), validation | lagged ridge 4.680, tuned ridge 4.697, TCN 4.711, persistence 5.465 | `comparison` |
| Prospective check | Flow 6, MAE 7.2, n = 5 | `docs/prospective-verification.md` |

## What M3 shows

- A model-planned workflow can run end to end. Trusted tools train and reload the models. Separate code scores every model on the same rows.
- Code refuses bad proposals. Two answers failed a length rule and were corrected on the retry.
- The Lead chose to finish and keep the lagged ridge. The evaluator's numbers support that choice.

## What M3 does not show

- **No independence.** The Lead reviewed its own results. No second model checked the choice. Reuse of one model for all roles means a shared blind spot is possible.
- **No critic.** The method review gate was off. The recorded run holds no critic record.
- **No checkpoint hash in the trace.** The trace holds the alias `muse-glimmer-30B` only. The provider name sits in `result.json`, which is hashed in the replay manifest but not inside the trace chain.
- **Not independent evidence.** Validation years 2019 to 2023 were used in many earlier experiments. The TCN chose its best epoch on the same years. One seed, one configuration.
- **Two faults in agent text.** The Lead said the TCN "trains fast vs GRU", and the code's own table says otherwise. The PM note left out that B4 is also worse than persistence above 55 µg/m³. The decision record states it.

## Wording rule for the video and the README

Say: "four roles, one local model". Do not say "multi-model council" for M3. M4 is the first experiment that puts different checkpoints in different seats.

# Comparative evidence report

Built by `scripts/build_comparative_report.py` from 48 saved runs. No run was made for this report, and no model ran. The machine record is `docs/evidence/comparative-v1.json`. The #75 results in `docs/benchmark-matrix-results-2026-11-02.md` are unchanged.

## 1. Answer

Prefer the simplest execution that meets the goal. On the tested tasks, no agent workflow showed a benefit over the deterministic pipeline.

- **Multi-agent execution:** it did not improve verified goal completion on any task that all three workflows ran, and it cost more. In the benchmark screen, median wall time to the decision gate was 1.1 s deterministic, 682.9 s single agent and 1573.1 s team. The overhead is not justified on this evidence.
- **The deterministic pipeline** cannot choose a new method, so this result covers these four tasks only. A model has shown value in writing a case or a review, and not in a measured gain in outcome.
- **What a team needs:** the closing fix. Without it, the team failed 3 of 3 confirm runs.

## 2. How to read this

- Sources ran at different commits. Do not add or compare across sources.
- VGC is verified goal completion, the five rules in benchmark protocol section 4.1, recomputed here from each saved record. Replay ran again at this commit on every run.
- VGC compares a run with its own plan. It does not say that one plan is scientifically better.
- Each cell has 1 to 3 runs. There are no intervals and no significance claims.
- Wall time here is the time inside the run. The #75 report used the outer manifest time, so its medians differ by up to about a second for F. Both are correct for their own measure.
- Wall times are from one shared Mac under swap pressure. They are not a hardware benchmark.
- Model tokens are for the local model, and billed cost is zero. Energy: not measured. System memory by run: not measured. Largest training memory is recorded only where training ran.

## 3. Task coverage

Numbers are runs. A comparison is matched only where one source ran the same scenario in each arm.

| Source | Scenario | deterministic | single agent | multi-agent | small-model fallback | All three |
|---|---|---|---|---|---|---|
| benchmark confirm | burned-area-method | 0 | 0 | 4 | 0 | no |
| benchmark confirm | pm25-exceedance | 0 | 0 | 2 | 0 | no |
| benchmark fallback | burned-area-method | 0 | 0 | 0 | 2 | no |
| benchmark fallback | burned-area-segmentation | 0 | 0 | 0 | 2 | no |
| benchmark fallback | pm25-exceedance | 0 | 0 | 0 | 2 | no |
| benchmark screen | burned-area-method | 1 | 1 | 2 | 0 | yes |
| benchmark screen | burned-area-segmentation | 1 | 1 | 2 | 0 | yes |
| benchmark screen | pm25-exceedance | 1 | 1 | 2 | 0 | yes |
| benchmark screen | pm25-regression | 1 | 1 | 0 | 0 | no |
| harness-v1 | burned-area-method | 2 | 2 | 2 | 0 | yes |
| harness-v1 | burned-area-segmentation | 2 | 0 | 2 | 0 | no |
| harness-v1 | pm25-exceedance | 2 | 2 | 2 | 0 | yes |
| harness-v1 | pm25-regression | 2 | 2 | 2 | 0 | yes |

Not matched, and not compared here: a team on `pm25-regression` in the benchmark, a single agent on `burned-area-segmentation` in harness-v1, and F at the `confirm` commit. Team arms with mixed models did not run.

## 4. Results by arm

| source | workflow | group | runs | vgc | safe_stops | failed | replays_clean | median_wall_s_reached_gate | total_wall_s | median_model_calls | median_tokens | largest_training_rss_mb |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| benchmark screen | deterministic | F | 4 | 4 | 0 | 0 | 4 | 1.1 | 24.4 | 0.0 | 0.0 | 363.9 |
| benchmark screen | single agent | S-M | 4 | 3 | 0 | 0 | 4 | 682.9 | 3135.3 | 4.0 | 7013.5 | not measured |
| benchmark screen | multi-agent | T-M-v1 | 3 | 2 | 1 | 0 | 3 | 1573.1 | 3327.5 | 11.0 | 16765.0 | not measured |
| benchmark screen | multi-agent | T-M-v2 | 3 | 2 | 1 | 0 | 3 | 1715.8 | 3666.6 | 15.0 | 21315.0 | not measured |
| benchmark confirm | multi-agent | T-M-base | 3 | 0 | 0 | 3 | 3 | not measured | 2569.4 | 5.0 | 7547.0 | not measured |
| benchmark confirm | multi-agent | T-M-win | 3 | 3 | 0 | 0 | 3 | 1297.7 | 4614.4 | 10.0 | 14664.0 | not measured |
| benchmark fallback | small-model fallback | S-q4 | 3 | 0 | 0 | 0 | 3 | 28.9 | 81.9 | 3.0 | 3203.0 | not measured |
| benchmark fallback | small-model fallback | S-l3 | 3 | 0 | 1 | 0 | 3 | 6.5 | 14.8 | 3.0 | 1934.0 | not measured |
| harness-v1 | multi-agent | team | 8 | 3 | 2 | 3 | 8 | 2281.9 | 9434.6 | 6.5 | 8921.0 | not measured |
| harness-v1 | single agent | single | 6 | 6 | 0 | 0 | 6 | 653.2 | 4481.1 | 4.0 | 7670.5 | not measured |
| harness-v1 | deterministic | fixed | 8 | 8 | 0 | 0 | 8 | 0.7 | 46.0 | 0.0 | 0.0 | 342.4 |

Failures and stops are real results. They stay in the counts.

## 5. Matched tasks, benchmark screen

| Scenario | Arm | Outcome | VGC | Median wall s | Calls | Tokens |
|---|---|---|---|---|---|---|
| burned-area-method | F | {'adopt_limited': 1} | 1 of 1 | 0.2 | 0.0 | 0.0 |
| burned-area-method | S-M | {'adopt_limited': 1} | 1 of 1 | 576.2 | 3.0 | 4579.0 |
| burned-area-method | T-M-v1 | {'adopt_limited': 1} | 1 of 1 | 1582.4 | 11.0 | 16765.0 |
| burned-area-segmentation | F | {'request_resource': 1} | 1 of 1 | 0.1 | 0.0 | 0.0 |
| burned-area-segmentation | S-M | {'adopt_limited': 1} | 0 of 1 | 650.7 | 4.0 | 6285.0 |
| burned-area-segmentation | T-M-v1 | {'abstained': 1} | 0 of 1 | 181.3 | 1.0 | 1298.0 |
| pm25-exceedance | F | {'retain_baseline': 1} | 1 of 1 | 1.9 | 0.0 | 0.0 |
| pm25-exceedance | S-M | {'retain_baseline': 1} | 1 of 1 | 1193.4 | 6.0 | 11060.0 |
| pm25-exceedance | T-M-v1 | {'retain_baseline': 1} | 1 of 1 | 1563.8 | 12.0 | 20105.0 |

One run per arm on each scenario. The team's safe stop on segmentation is a stop and not a goal met. `S-M` chose `adopt_limited` there, which is not the required `request_resource`.

## 6. Matched pairs, benchmark confirm

| Scenario | Arm | Outcome | VGC | Median wall s | Calls | Tokens |
|---|---|---|---|---|---|---|
| burned-area-method | T-M-base | {'failed': 2} | 0 of 2 | 769.7 | 5.0 | 7347.0 |
| burned-area-method | T-M-win | {'adopt_limited': 2} | 2 of 2 | 1228.5 | 10.0 | 14097.5 |
| pm25-exceedance | T-M-base | {'failed': 1} | 0 of 1 | 1030.0 | 7.0 | 10181.0 |
| pm25-exceedance | T-M-win | {'retain_baseline': 1} | 1 of 1 | 2157.5 | 17.0 | 27524.0 |

Baseline wall time is not a cost control, because those runs stopped early.

## 7. Model selection and abstention

Model runs with a decision: 25. The outcome matched the code rule in 20. A model changed the plan in 15 of 36 model runs. An outcome more permissive than the code rule appeared in 2 runs: [('S-l3', 'burned-area-method'), ('S-l3', 'burned-area-segmentation')].

Runs that stopped with no decision:

| Source | Scenario | Arm | Stop reason |
|---|---|---|---|
| benchmark screen | burned-area-segmentation | T-M-v1 | the PM found it out of scope |
| benchmark screen | burned-area-segmentation | T-M-v2 | the PM found it out of scope |
| benchmark confirm | burned-area-method | T-M-base | Stopped: data_specialist used its turns without submit_note |
| benchmark confirm | pm25-exceedance | T-M-base | Stopped: ml_engineer used its turns without submit_note |
| benchmark confirm | burned-area-method | T-M-base | Stopped: data_specialist used its turns without submit_note |
| benchmark fallback | pm25-exceedance | S-l3 | the Lead chose to run no experiment |
| harness-v1 | pm25-exceedance | team | Stopped: ml_engineer stopped without submit_note |
| harness-v1 | burned-area-method | team | Stopped: data_specialist used its turns without submit_note |
| harness-v1 | burned-area-segmentation | team | the PM found it out of scope |
| harness-v1 | burned-area-method | team | Stopped: data_specialist used its turns without submit_note |
| harness-v1 | burned-area-segmentation | team | the PM found it out of scope |

Scientific correctness: rule 5 of VGC checks the one scenario with a required outcome. On the others, VGC checks agreement with the code rule. On `pm25-regression`, F chose `adopt_limited` and `S-M` chose `retain_baseline`. Both are consistent with their own plans, and this record does not say which plan is right. The GRU is worse than persistence above 55 µg/m³, so the simpler reading favours `retain_baseline` for elevated hours.

## 8. Independent critique

No critique in this report is independent: the critic ran as a second pass on the same model as the Lead.

Seeded rows: 2. Live critic rows: 2. Usable critiques: 1. Accepted by the Lead and passed by code: 1. Rebutted: 0. Left open: 0. These are seeded cases, so a changed case here is not a changed real decision.

Matched live runs with and without the gate: not measured.

## 9. Missing measurements

| Measure | State |
|---|---|
| Critic on another model | not measured |
| Team with small specialists | not measured |
| Team on `pm25-regression` with the closing fix | not measured |
| Sealed test period | not measured: it was not read |
| Energy and system memory by run | not measured |

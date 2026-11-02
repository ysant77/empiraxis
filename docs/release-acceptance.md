# Release acceptance, November 2026

This register records what each capability shows, from saved runs and tests. A status follows the evidence. No run was made for this register.

Status values: `demonstrated_bounded` (shown on real evidence, inside stated limits), `partial`, `blocked`, `deferred`.

## Milestone register

| # | Capability | What ran | Evidence | What is missing | Blocks submission | Status |
|---|---|---|---|---|---|---|
| 2 | Human supervision | S4 stops at a pending human decision. Replay has no approve control. | `test_team_resources.py`: denied, edited, forged, expired and wrong-key approvals are refused. `test_harness_lifecycle.py`: no model or controller path can approve. `test_ui_surfaces.py`: replay has no live or unapproved control. | No signed approval was made in a scenario run. | No | demonstrated_bounded |
| 4 | Engineering Lead | Muse as Lead chose a statistical strategy, set parameters, asked for one refinement and recommended `retain_baseline` (team run). In Part B it wrote three full method cases live. | `examples/replay/scenario-muse-team-exceedance/trace.jsonl`, `docs/method-review-validation-results.md` | In 1 of 3 live cases the Lead wrote method names as free text, which the registry refused. | No | demonstrated_bounded |
| 6 | Agent orchestration | One recorded multi-role run: PM, Lead, data specialist, ML specialist, evaluator, forward to a human. 17 model calls, 4 tool calls, hash-chained trace. | Team run trace; budget, interruption and handoff tests in `test_a2a_engineer.py`, `test_board_store.py`, `test_mlops_models.py`, `test_harness_engine.py` | One recorded team run is in the repository. Other team runs are local. | No | demonstrated_bounded |
| 7 | Safe tool execution | Models call fixed, allowlisted tools. Code checks each proposal. | `test_agent.py` (turn budget, rejected tools), `test_harness_lifecycle.py` (no code or pass mark in a proposal) | No general shell or browser agent, by design. | No | demonstrated_bounded |
| 8 | Scientific critic | review-gate-v1 and v2, all planned runs complete. | `docs/method-review-validation-results.md` | The same-model critic added no detection beyond code rules. In live runs the gate stopped 2 of 3 correct plans. No independent critic model ran. | No: the gate stays off | partial |
| 10 | Heterogeneous data | S3: ERA5 wind at two levels, rain, FIRMS boxes, 54 variants of tolerance, rain limit, lag and clock convention, haze onsets against clean hours. | `examples/replay/scenario-s3-transport/` | No humidity or other products, by decision. | No | demonstrated_bounded |
| 11 | Resource decisions | S4 names the missing imagery, masks and weights approval, with an estimated size, and stops. | `test_segmentation_gate.py`, S4 replay | No acquisition ran, by decision. | No | demonstrated_bounded |
| 13 | Method selection | Five cases below: a justified simple method, a challenged neural plan, a hybrid that lost, a refused satellite method and an abstention. | Scenario replays, seeded review cases, `docs/comparative-evidence-report.md` | Selection thresholds such as the elevated-hour rule are exploratory. | No | demonstrated_bounded |
| 15 | Transfer and distillation | S2: a frozen GRU encoder with a fitted logistic head. Distillation: 3 seeds, distilled against direct student. | S2 replay; distillation records are local in `earthlab-e1-runs/tiers-seeds/summary.json` | Distillation gain was small and not consistent: paired MAE skill 0.009, 0.002 and 0.011, and the lower limit of seed 11 is below zero. No report in the repository yet. Prithvi did not run. | No | partial |
| 16 | MLOps lifecycle | Data checks, train-only transforms, feature artifacts, registry, ridge, trees, GRU, hybrid, bundle verification. | `docs/mlops-results-v1.md`, `docs/model-acceptance-v1.md` | Tuning code has tests, but no real search ran. | No | demonstrated_bounded |
| 18 | Workflow comparison | 48 saved runs: deterministic, single agent, team. | `docs/comparative-evidence-report.md` | Team arms with mixed models did not run. Energy and system memory were not measured. | No | demonstrated_bounded |
| 19 | Interface | Three surfaces, four scenarios and the team run, one run identity in the URL. | Browser check below; `tests/test_ui_surfaces.py`, `tests/test_scenario_demo.py` | None known at P0. | No | demonstrated_bounded |
| 20 | Research deployment readiness | Ridge and trees bundles: saved-bundle inference on 43,818 issues, largest difference 0.0. The hybrid is refused. | `docs/model-acceptance-v1.md` | No prospective run, monitoring or operator. The schema cannot hold a production-ready claim. | No | demonstrated_bounded |

## Method selection cases

| Case | What happened | Source |
|---|---|---|
| A simple method is enough | The deterministic raster path reported September 2015 and held back October 2015. The team chose a statistical model and kept persistence. | Part B `burned-area-method` off; team run |
| A neural plan is challenged | A GRU case with no simple comparison was found by code in 6 of 6 runs. The Lead accepted and added ridge in 5 of 5 usable answers. | `gru-no-comparison`, v1 and v2 |
| A model works but loses | The hybrid beat logistic regression, F1 0.255 against 0.162, and lost to the persistence alarm, 0.306. | S2 |
| A satellite method is refused | The imagery covers Texas, not the study box. There are no reference masks and no signed weights approval. No segmentation ran. | S4 |
| An investigation abstains | No box and level reached consistent, 0 of 6. Winds that pass in haze hours also pass in clean hours. | S3 |

## Four-scenario acceptance

| Scenario | Requirement | Verified | Limit |
|---|---|---|---|
| S1 | Real training, baselines, MAE, elevated-hour failure, sealed test, separate ridge inference | GRU trained 20.2 s. MAE 4.588 against persistence 5.465 µg/m³. Above 55 µg/m³: 28.772 against 26.324. Scored on validation only. Ridge bundle reproduced 43,818 rows, and the page says it is ridge, not the GRU. | Simulated-availability hindcast. The elevated-hour rule is exploratory. |
| S2 | Encoder provenance, frozen features, fitted head, classification evaluation, rejection | The encoder is a separate GRU with the S1 settings, trained on 2014 to 2018, selected on 2019 to 2021, then frozen. A logistic head was fitted. Validation years 2022 to 2023: 87,570 scored hours, 828 exceedances. F1 gain over persistence -0.165 to -0.001. | Cut and calibration are optimistic. Hybrid inference is refused. |
| S3 | Reanalysis labels, time conventions, transport checks, inconclusive result, no attribution | ERA5, 1,464 hours per series, 0 gaps. Sign tests 5 of 5. Clock convention is one of the varied settings. Verdict inconclusive, no identifiable source. | Hindsight diagnostic. Two haze-heavy months. |
| S4 | Data suitability, deficiencies, no fabricated score, pending approval | MCD64A1 at 500 m has no six-band imagery or masks. The chips are outside the box. Segmentation score: none. Human decision pending. | No acquisition ran. |

Each scenario opens on all three surfaces with one run name, one trace head and one result digest. The S1 to S4 traces hold no model turn. The team run is the only scenario where Muse ran, and its page says so.

## Interface check

A real browser loaded 9 pages (Workspace S1 to S4 and the team run, Lab S1 and S2, Control Room S4 and the team run) at 1440 by 900, 768 by 1024 and 390 by 844. All 27 had no horizontal overflow, no clipped element, no exception and no error box. Pills, surface changes, back, refresh and direct links kept the page and the selected controls. Screenshots: `docs/evidence/demo/` and `docs/evidence/screens/`.

## Known limits

- Nothing was scored on the sealed test period, and no prospective run exists.
- No model is production-ready. No result is a forecast, a health warning or a source attribution.
- The raw benchmark and validation runs are local. The repository holds the derived record and a test that the report renders from it.
- Wall times come from one shared Mac under swap pressure.
- The method critic is a second pass by the same model. It is off by default.
- This project was built with AI-assisted engineering. The README says so.

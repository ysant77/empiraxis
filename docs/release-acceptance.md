# Release acceptance, November 2026

This register records what each capability shows, from saved runs and tests. A status follows the evidence. No run was made for this register.

This register uses the 20 milestone definitions of the original plan. Each row has two labels:

- `hackathon_demonstrated`: `bounded` (shown on real evidence, inside the stated limits), `partial`, or `future`.
- `original_scope_complete`: `no` for every row. No row reaches the full original scope.

A scripted test is not a live model evaluation. A replay is not a new training run.

**Superseded on 3 November 2026.** `docs/vision-matrix-final.md` assesses each milestone again after the runs of 3 November. This register stays as the earlier record.

## Milestone register

| # | Milestone | Implementation and real run | Independent test | hackathon_demonstrated | original_scope_complete | Main blocker | Release relevance |
|---|---|---|---|---|---|---|---|
| 1 | Reusable engineering organization across projects | None in this repository | None | future | no | No core is extracted and no second domain ran | none |
| 2 | Human Director: signed approvals, bounded autonomy | S4 stops at a pending human decision. Replay has no approve control. | `test_team_resources.py`: denied, edited, forged, expired and wrong-key approvals are refused. | bounded | no | Signed approvals were made for the Prithvi weights and chips (2026-11-03). None was made in a scenario run. | high |
| 3 | PM: typed requirements, constraints and acceptance tests | Muse as PM wrote the typed problem in the team run. | Contract tests; one recorded team run | bounded | no | One live task; no unseen requests | medium |
| 4 | Engineering Lead: defensible method choices | Muse as Lead chose a strategy, asked for one refinement and recommended `retain_baseline` (team run). It wrote three method cases live in review-gate-v2. | `docs/method-review-validation-results.md` | bounded | no | In 1 of 3 live cases the Lead wrote free-text method names | high |
| 5 | Compact specialist team | Muse data and ML specialist seats in the team run | Team run trace; delegation tests | bounded | no | No software or QA seat ran live | medium |
| 6 | Durable run harness: state, trace, budgets, recovery | Team run: 17 model calls, 4 tool calls, hash-chained trace | Budget, interruption and handoff tests | bounded | no | One process at a time; no distributed recovery | high |
| 7 | Secure real tools | Models call fixed, allowlisted tools. Code checks each proposal. | `test_agent.py`, `test_harness_lifecycle.py` | bounded | no | No general code, shell, MCP or computer-use execution, by design | medium |
| 8 | Independent scientific design critique | review-gate-v1 and v2, all planned runs | Seeded faults: 7 of 7 found, all by code rules. The later contract rules, applied offline to every saved critique, refuse 8 of 8 sealed tests and 6 of 6 untyped thresholds (`docs/method-review-gate-v1.md`). | partial | no | The same-model critic added no detection. The gate stopped 2 of 3 correct live plans. It stays off. | medium |
| 9 | Scientific provenance and data quality | NEA, ERA5, FIRMS and MCD64A1 hashes; claim verifier | `python -m earthlab.harness.audit`; verifier tests | bounded | no | ERA5, FIRMS and MCD64A1 approvals expired on 2026-10-31 and were not signed records | high |
| 10 | Heterogeneous environmental modeling | S3: ERA5 wind at two levels, rain, FIRMS boxes, 54 settings. NEA live wind, rain, humidity and PM2.5 catalogue, with one capture of 141 values (`docs/live-data-and-forecast-inputs.md`) | S3 replay | bounded | no | Retrospective only; no aligned predictive features | high |
| 11 | Data suitability, abstention, approved acquisition | S4 names the missing imagery, masks and weights approval, and stops. | `test_segmentation_gate.py`, S4 replay | bounded | no | No acquisition ran | high |
| 12 | Data engineering: train-only transforms, feature artifacts | `docs/mlops-results-v1.md` | `docs/model-acceptance-v1.md` | bounded | no | One tabular source | medium |
| 13 | Method selection: deterministic, statistical, ML, DL or abstention | Five cases below | Scenario replays, seeded review cases | bounded | no | Selection thresholds such as the elevated-hour rule are exploratory | high |
| 14 | Classical, hybrid and neural experiments | Ridge, trees, GRU, frozen-GRU hybrid | `docs/mlops-results-v1.md`, S1, S2 | bounded | no | Few families; no controlled comparison across many seeds | high |
| 15 | Reuse, transfer, distillation, pretrained satellite models | S2: a separate frozen GRU encoder with a fitted logistic head. Distillation: 3 seeds, local records. | S2 replay; `docs/distillation-results-v1.md`, recomputed from saved predictions | partial | no | Exact S1 checkpoint reuse is blocked (below). Prithvi ran once at Level A, a reproduction on one chip (`docs/prithvi-level-a.md`). Distillation passed its rule for 2 of 3 seeds, with a gain of at most 0.05 µg/m³ MAE, so it is not adopted. | medium |
| 16 | Reproducible experiments: tracking, tuning, registry | Registry, bundles, bundle verification. A rolling-origin ridge search ran on the train years: 5 candidates, 3 folds. | `docs/model-registry.md`, `docs/rolling-origin-ridge-v1.md` | bounded | no | One small search; the selected penalty is at the edge of the grid | medium |
| 17 | Independent evaluation: baselines, leakage, subgroups | Persistence baselines, elevated-hour subgroup, sealed test period | S1 elevated-hour failure; leakage tests; adversarial suite, 35 of 35 attacks refused and 20 of 20 controls allowed (`docs/adversarial-qa-v1.md`) | bounded | no | No prospective validation | high |
| 18 | Routing, prompt and orchestration cost optimization | 48 saved runs compared by workflow; profiler; static prompt rules; router function | `docs/comparative-evidence-report.md`, `docs/efficiency-evaluation.md` | partial | no | Cost is measured, but no change showed a repeated gain, and none was promoted | low |
| 19 | Responsive UI: Workspace, Lab, Control Room | Three surfaces, four scenarios and the team run | 27 browser pages; `test_ui_surfaces.py`; hosted replay tests | bounded | no | No usability or accessibility study | high |
| 20 | Deployment readiness | Ridge and trees bundles: saved-bundle inference on 43,818 issues, largest difference 0.0. Hosted replay entry (`docs/hosted-replay.md`). Prospective prediction ledger, off by default (`docs/prediction-ledger.md`). | `docs/model-acceptance-v1.md` | bounded | no | No prospective run, monitoring or operator. The hosted replay is not published. | medium |

## Status of the November 3 work

| Item | Implemented | Demonstrated with real records | Scientifically validated | Refused or blocked |
|---|---|---|---|---|
| Adversarial QA suite, 55 cases | yes | yes: 35 of 35 attacks refused, 20 of 20 controls allowed | no: one input per case | Humidity fraction, soil-moisture units and a hyperspectral label have no check |
| Four difficulty tiers (`docs/four-tiers.md`) | evidence map only | yes, from existing runs | no | S2, S3 and `sb05-september` do not use the harness lifecycle |
| Rolling-origin ridge search | yes | yes: train years only | no: no unused period for an independent score | none |
| NEA live capture | yes | yes: one capture, 141 values | no | Station-to-region join: no rule written |
| Prospective prediction ledger | yes | no: off, no prediction issued | no | Needs the owner's signed activation |
| Prithvi Level A | yes | yes: one chip, IoU 0.912, signed approvals | no: one chip from the publisher's test split | Levels B and C: no independent labels, single-date chips |

Counts: 16 `bounded`, 3 `partial` (8, 15, 18), 1 `future` (1). The earlier count of 17 bounded listed milestone 18 as bounded. That row shows measurement, not an optimization gain, so it is `partial` here.

## S1 checkpoint reuse: blocked

The S1 GRU checkpoint is valid. Its export passed the hash check, on a scratch copy. The raw run did not change.

S1 selected its best epoch (epoch 3 of 6) on validation rows 41,663 to 85,486, which is all of 2019 to 2023. The sealed period starts at row 85,487. No unsealed period is left that S1 did not use for selection. `earthlab.mlops.encoder.check_reuse` refuses each unsealed span for this encoder.

So no independent reuse score exists, and none was made. The sealed period stays closed. S2 is a different experiment: a separate GRU with the S1 settings, selected on 2019 to 2021 and scored on 2022 to 2023. A valid S1 reuse score needs new data after the release, or a new protocol that is registered before the run.

## Satellite feasibility

Inventory, 2026-11-02. No model ran. Nothing was downloaded.

| Asset | Local state | Hash | Licence | Approval |
|---|---|---|---|---|
| Prithvi-EO-2.0-300M-BurnScars weights, revision `a3f2c410` | 1,297,798,380 bytes | matches `provenance.json` | Apache-2.0, from the model card | `chat_only_unsigned` |
| HLS burn scars chips, revision `1864285e` | 2,645,552,531 bytes; 540 training and 264 validation chip and mask pairs | matches `provenance.json` | CC-BY-4.0, from the dataset card | `chat_only_unsigned` |

| Level | Status | Reason |
|---|---|---|
| A: one pretrained forward pass | done, 2026-11-03 (`docs/prithvi-level-a.md`) | Signed approvals for the weights and chips. One test-split chip from an unseen tile: IoU 0.912. A reproduction, not a transfer result. |
| B: score against a baseline | blocked | The model was fine-tuned on these chips. The validation chips served the model card's own evaluation, so they are not independent. Each chip is one date, so dNBR cannot be computed. |
| C: adaptation | not started | Levels A and B did not pass. No independent labels or compute budget are set. |

Preflight facts that need no approval, checked on one extracted chip:

- The image is 512 by 512 by 6, float32, with values from 0.003 to 0.514 (reflectance from 0 to 1).
- The mask is int16, with values 0 and 1 in this chip.
- TerraTorch 1.2.13 is on PyPI. It needs torch, torchgeo, segmentation-models-pytorch and timm. None is in an isolated environment yet.

To unblock Level A, the owner approves the queued Prithvi request in the local operator UI with the operator key. A model cannot do this step.

The chips cover the United States. A result on them says nothing about the Kalimantan box. S4 stays `request_resources`.

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

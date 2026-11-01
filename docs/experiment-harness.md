# Experiment harness v1

Status: experimental research code. It stops at a human decision. Results are historical
evaluations, not operational forecasts. The test period of the forecast protocol stays sealed.

## Reuse

| Need | Existing part reused |
|---|---|
| Hash-chained audit | `RunTrace` |
| Task view on every surface | `board.progress.fold` |
| Bounded model roles | `harness/seats.py`, extracted from E1 with no change in behaviour |
| Regression science | `forecast.Workbench`, its splits, templates and evaluator |
| Isolated training | `forecast.isolated`, `templates_train_nn.py` |
| Rule 9.1 | `forecast.gate` |
| Raster science | the pinned MCD64A1 tool and independent verifier |
| Signed human records | `team.resources` |
| Resource path | `team.request_flow`, `config/fetch/large-assets.yaml` |

## Added

| Record or part | Why it was needed |
|---|---|
| `ProblemSpecV1`, `ResearchRequestV1` | E1 records fit one regression only |
| `DatasetProfileV1` | Code-measured facts for any problem kind |
| `ExperimentPlanV1`, `SpecialistTaskV1` | The delegation ticket fits one QA table only |
| `EvaluationReportV1`, `DecisionRecordV1` | One shape for every evaluator and outcome |
| `harness/lifecycle.py` | Authority for each state, folded from the trace |
| `harness/gates.py` | Typed refusals before any work |
| `harness/engine.py` | One control path for three arms and every adapter |
| `harness/classify.py`, `eval_classify.py` | Scenario B and its independent evaluator |
| `harness/raster.py` | Scenario C |
| `harness/replay.py` | Reproduction with no model |

## Authority

The controller names each actor. A model never does. Only the evaluator enters `evaluated`.
Only a valid signed record enters `approved` or `denied`. A proposal has no field that can carry
code, a pass mark or an approval, and extra fields are refused. A run is called autonomous
only when a model changed the plan from the preset. Otherwise it is labelled a deterministic
workflow.

## Scenarios

```bash
earthlab --data-dir data/nea harness pm25-regression --arm fixed
```

```bash
earthlab --data-dir data/nea harness pm25-exceedance --arm team
```

```bash
earthlab --data-dir data/nea harness burned-area-method --arm team
```

```bash
earthlab --data-dir data/nea harness burned-area-segmentation --arm fixed
```

```bash
earthlab harness-replay runs/<run>
```

Scenario A needs `EARTHLAB_TRAIN_PYTHON`, set to the pinned training environment.

## Rules recorded after results were seen

- Scenario A reports elevated-hour error, and a model worse than persistence there can only be
  `adopt_limited`. E1 validation results showed this weakness before the rule was written.
- Scenario B's threshold of 35 ug/m3 was set from the train split's positive rate only. Its
  alarm cut is tuned on 2019 to 2021, and only 2022 to 2023 is scored.

## Known limits

- A failed run ends in `failed`. Training resumes from a checkpoint, but the engine does not
  resume a run at a lifecycle stage.
- The specialist tools take no arguments in the harness. The Lead's choice sets the job.
- Isolation applies to neural training. Classical adapters run in process, and they are
  fixed code with menu values.

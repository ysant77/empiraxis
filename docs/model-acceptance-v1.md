# Model artifact verification and inference acceptance, v1

This report covers the step between a finished experiment and reusable experimental inference. No model was trained for this report. No provider was called, and no data was downloaded. The sealed test period was not read: the batch input stops at the last validation row.

## What changed

| Item | Before | Now |
|---|---|---|
| Evaluation verdict | `Registry.evaluate` took a caller Boolean. | It takes `EvaluationRecordV1`. `harness.attest` makes the record from saved files. The registry checks the bundle, feature, source, report, evaluator name, evaluator code digest and report row. |
| Promotion | Any caller could write `evaluated`. | A pass needs predictions reproduced from this bundle. A hybrid is not reproduced here, so it can fail but it cannot pass. |
| Bundle check | None. | `earthlab mlops-verify` runs 12 checks and writes nothing to the registry. |
| Readiness | None. | `earthlab mlops-accept` writes `DeploymentReadinessV1`. The schema cannot hold a production-ready claim. |
| Issue-time inputs | Modelled availability passed with a caveat. | An issue-time forecast needs a measured log for each input. Modelled availability blocks it. |
| Scientific labels | Hindcast and forecast shared one arm. | `issue_time_forecast`, `simulated_availability_hindcast` and `hindsight_diagnostic` are separate. Reanalysis blocks the first two. |

The NEA file has no available-at time. S1 and S2 are therefore simulated-availability hindcasts, and `families_run` now stops before any method if that check blocks. This does not change the E1 splits, the frozen test period or the benchmark.

## Reproduce

Run this for one bundle. It reads the registry and the run folder, and it writes only to `--out`.

```bash
uv run earthlab mlops-accept --registry ../earthlab-e1-runs/mlops-v1/registry --bundle <bundle sha256> --run ../earthlab-e1-runs/mlops-v1/regression --source data/nea/Historical1hrPM2.5.csv --out ../earthlab-e1-runs/acceptance-v1/s1-ridge
```

`mlops-verify` takes the same inputs without `--out`. Exit 2 means refused.

## Results on the saved real bundles

Source: the pinned NEA file, `2fb76e1c…`. Registry: `mlops-v1`, unchanged. A digest of the registry and run files matched before and after these runs.

| Bundle | Status | Outcome | Batch inference |
|---|---|---|---|
| s1-ridge `02d39d3e` | evaluated | verified_experimental | Real data, 43,818 issues |
| s1-trees `38e1bbc6` | evaluated | verified_experimental | Real data, 43,818 issues |
| s1-persistence, s1-climatology | rejected | refused | Not run |
| s2-logistic, s2-trees_classifier (two runs each) | rejected | refused | Not run |
| s2-frozen_gru_logistic `e53f6e42` | rejected | refused, hybrid unsupported | Not run |

For both verified bundles, the `mlops-predict` output matched the stored predictions with a largest difference of 0.0. The independent evaluator gave the same MAE from that output as the report: 4.650 for ridge and 4.747 for trees. The recomputed verdict also matched the report.

The S2 bundles have a second refusal: the old runs saved no prediction file for these rows. New runs save it. Their rejection stands, because the report row failed. Their predictions were not reproduced.

## Readiness of the two verified bundles

Both reports say `research`, with no human approval, and `production_ready` is false.

| Measure | Ridge | Trees | Persistence |
|---|---|---|---|
| MAE above 55 µg/m³ | 37.34 | 29.47 | 26.32 |
| Recall above 55 µg/m³ | 0.05 | 0.38 | 0.44 |
| Worse than persistence in elevated hours | Yes | Yes | Reference |

Do not rely on either model in elevated hours.

| Timing of one batch command | Ridge | Trees |
|---|---|---|
| Wall time, including process start | 4.685 s | 5.853 s |
| Peak resident memory | 439.3 MB | 404.0 MB |

These numbers are not clean. The command ran at low priority beside the benchmark, with the Muse server loaded and swap in use. The report records this condition.

## Limits

- The verifier proves agreement between saved files. The evaluator identity is a module name and a code digest. It is not a signature.
- The two S1 bundles reached `evaluated` through the earlier Boolean path. Their log is kept as it was. The verifier recomputes their verdict, and that recomputation is the evidence.
- Each bundle has one batch run on one machine. This shows reproducibility, not generalization.
- Real-data acceptance exists for regression only. No classifier passed, so the classification path has synthetic tests only.
- Hybrid inference stays unsupported until its encoder, classifier and preprocessing load as one verified bundle.
- No NEA logged availability exists, so the issue-time arm has synthetic tests only.

## Missing operational evidence

Every readiness report lists these items: prospective runs with logged availability, monitoring of drift and output quality, a rollback drill on a live path, load and failure tests on target hardware, and a named operator with an incident path.

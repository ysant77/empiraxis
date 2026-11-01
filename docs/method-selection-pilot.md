# Method-selection pilot

Status: **pilot, synthetic data only**. This is not autonomous training. No model chose,
fitted or approved a method in this pilot. No real scientific data enters it. The workflow
and the runtime do not call this package.

## Purpose

The pilot shows one typed record, `MethodDecisionV1`, on one toy problem. The record states
which methods were considered, what the data checks found, what the baseline is, how the
comparison ran, what is not resolved, and why the system selected or abstained.

## Parts

| File | Responsibility |
| --- | --- |
| `src/earthlab/method/contracts.py` | Proposal, plan and decision records, and their rules |
| `src/earthlab/method/toy.py` | The seeded synthetic series generator |
| `src/earthlab/method/evaluate.py` | Two allowlisted forecasters, the split and the scores |
| `src/earthlab/method/policy.py` | The fail-closed path from a proposal to a decision, the recompute and the human gate |
| `tests/fixtures/method/toy_cases_v1.json` | The two series and their registered plans |

## Decision rule

The rule is fixed before the run. The commit that adds the plan comes before the commit that
adds the evaluator, so the Git history shows the order.

1. The baseline is `last_value`: the next value equals the last value.
2. The challenger is `ar1_ols`: one lag, fitted by least squares on the train part only.
3. The split is chronological: 60% train, then a gap of 3 steps, then test.
4. The metric is one-step mean absolute error (MAE) on the test part.
5. The relative gain is `1 - challenger_mae / baseline_mae`.
6. The challenger is selected only if the gain is at least 0.10 **and** the lower bound of a
   90% moving-block bootstrap interval is above zero.
7. In all other cases, the simpler method stays.

A plan can raise the threshold. It cannot go below the floor of 0.05. The trusted caller
gives the registered plan digest, so a plan changed after a result is refused.

## Measured results

Label: `synthetic harness`. Each series has 240 values and 93 test samples.

| Series | Baseline MAE | Challenger MAE | Gain | 90% interval | Outcome |
| --- | --- | --- | --- | --- | --- |
| Mean-reverting, phi 0.3 | 1.1230 | 0.8967 | 0.2015 | 0.1406 to 0.2615 | `select_candidate`: `ar1_ols` |
| Random walk, phi 1.0 | 0.8249 | 0.8273 | -0.0030 | -0.0722 to 0.0689 | `keep_baseline`: `last_value` |

Both series come from a process that is known in advance. The first result shows that the
rule can select. The second shows that the rule can keep the simpler method. Neither result
says which method suits real data.

## Fail-closed behaviour

| Input | Result |
| --- | --- |
| Extra field: score, approval, code or an unknown key | `proposal_refused`; no measurement |
| Permission request for shell, network or training | `proposal_refused`; no measurement |
| Real data classification, random split, no gap or a low threshold | `proposal_refused`; no measurement |
| Unknown method, a false kind or a statistical baseline | `proposal_refused`; no measurement |
| Plan changed after registration | `plan_not_registered`; no measurement |
| Data changed after registration | `dataset_mismatch`; no measurement |
| Short, unordered, non-finite or constant data | `data_unsuitable`; no measurement |
| Zero baseline error | `evaluation_undefined` |

A refusal keeps fixed codes and known field names only. It does not keep proposer text.
Free text in a proposal does not change a score or an outcome.

ML, DL and pretrained candidates can appear in a proposal. The pilot records them as not
evaluated and adds a risk line. It does not train them.

## Human approval

Every decision has `human_approval.status = "pending"`, and the contract refuses any other
value. `method_gate` recomputes the scores from the data, then requires a
`HumanMethodApproval` for the exact decision digest. An approval clears review of this one
result. It does not approve a download, a paid call, training or a deployment.

## Limits

- Two synthetic series cannot show that the rule works in general.
- The rule compares one baseline and one challenger. It has no multiple-comparison control.
- The test part is used once for each series. There is no separate validation part, because
  neither method has a tuned setting.
- `method_gate` returns a record only. Nothing acts on it yet.
- The package has no link to `ExperimentArtifactV1`, which does not exist yet.

## Run the tests

```bash
UV_LOCKED=1 uv run --all-extras pytest tests/test_method_contracts.py tests/test_method_pilot.py tests/test_method_malicious.py --no-cov
```

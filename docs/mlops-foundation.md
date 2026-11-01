# MLOps foundation v1

This layer turns data into model artifacts that anyone can reproduce and audit. It does not aim for the largest model. The experiment harness keeps the lifecycle. This layer adds records, checks and a registry.

## What it contains

| Module | Job |
| --- | --- |
| `mlops/contracts.py` | Versioned records for schemas, features, bundles, trials and predictions. |
| `mlops/quality.py` | Data checks. It reports each problem and changes no value. |
| `mlops/preprocess.py` | Preprocessing fitted on the train span only. |
| `mlops/families.py` | The registered methods, their typed configs and their eligibility checks. |
| `mlops/trees.py` | A small tree ensemble in numpy. |
| `mlops/tuning.py` | A bounded search that selects on validation scores only. |
| `mlops/postprocess.py` | Calibration, alarm cut and input warnings. |
| `mlops/registry.py` | An offline registry with an append-only status log. |
| `mlops/serve.py` | Batch prediction from a registered bundle. |
| `harness/families_run.py` | Runs the registered methods on NEA data and scores them with the existing evaluators. |

## Status labels

Every result carries one label. Code assigns the label from recorded facts.

| Label | Meaning | How a bundle gets it |
| --- | --- | --- |
| `research` | The bundle is a candidate, evaluated or rejected. | Default. Serving it needs `--allow-research`. A rejected bundle never serves. |
| `validated_experimental` | The independent evaluator passed it and a human approved it. | A signed human record on the exact bundle digest. |
| `deployed_production` | Operational evidence exists. | Not supported. Code refuses this claim. |

A status is an event in the registry log. It is not a field in the bundle. Training alone never moves a bundle past `candidate`.

## Environment setup

Use Python 3.12 and `uv`. Do not add a dependency. The methods use numpy only. The code loads no pickle.

```bash
uv sync --all-extras
```

Set the operator key before a human approval. Keep it out of the shell history and out of the repository.

```bash
export EARTHLAB_OPERATOR_KEY="<operator key>"
```

## Run the registered methods

The command below fits S1 regression methods and scores them on validation years. It writes every bundle to the registry as a candidate.

```bash
uv run earthlab mlops-run regression --out runs/s1 --registry registry
```

Use `classification` for S2. The S1 methods are persistence, climatology, ridge and trees. The S2 methods are logistic and trees_classifier, next to the persistence alarm and the train rate. The evaluator's verdict moves a bundle to `evaluated` or `rejected`.

## Batch inference

The input is a CSV. The first column is the time. The other columns match the bundle's columns. The times must form a regular grid. A blank cell is a missing value.

```bash
uv run earthlab mlops-predict --registry registry --bundle <bundle sha256> --input rows.csv --output out.jsonl
```

The command writes one JSON line per issue. Each line holds the bundle digest, the status, the label, the values, the warnings and the source digest. The command stops with exit code 2 and a reason in these cases:

- The bundle is not registered, is rejected, or is not approved (without `--allow-research`).
- The input columns differ from the fitted columns.
- A feature is missing for any issue. The code never fills it silently.
- The feature record and its preprocessing disagree.
- The postprocessing steps do not fit the task.

## Model card example

```json
{
  "model_name": "s1-ridge",
  "method_id": "ridge",
  "family": "deterministic",
  "task": "regression",
  "config": {"alpha": 100.0},
  "output_names": ["north", "south", "east", "west", "central"],
  "postprocess": {"invert_scaling": true, "clip_nonnegative": true},
  "card": {
    "intended_use": "Research comparison of ridge on historical NEA PM2.5.",
    "limitations": [
      "Non-operational research result.",
      "Historical evaluation. Not a forecast of any future date.",
      "Not for health, safety or travel decisions."
    ],
    "not_for": ["Health, safety or hazard-warning decisions."]
  },
  "evaluation_sha256": "<digest of the evaluator report>",
  "code_revision": "<commit>"
}
```

The bundle also holds the weights digest, the feature record, the seed, the environment pins and the training metrics.

## S2 hybrid: frozen S1 encoder and a shallow head

The hybrid method is `frozen_gru_logistic`. It feeds the last hidden state of a frozen S1 GRU to a logistic head. The comparison list is fixed: the persistence alarm, logistic, trees_classifier and the frozen hybrid. The train rate stays as a majority-class reference.

### Chronology protocol

The S2 split is fixed. Fit the head on 2014 to 2018. Tune calibration and the alarm cut on 2019 to 2021. Score on 2022 to 2023. The sealed test period is never read.

The S1 trainer picks its best epoch with the validation MAE over 2019 to 2023. That span includes the scored years. An encoder from that run has seen the scored samples during selection. The protocol cannot make such an encoder clean, so code refuses it.

Code applies these rules before it computes any embedding. One failure refuses reuse, and the message lists every reason.

1. The architecture, the input channels, the preprocessing digest and the source digest equal what S2 builds. The preprocessing digest covers the exact `series`, `mask` and `calendar` arrays.
2. The encoder trained only on samples up to the classifier's train end.
3. The encoder's selection span does not overlap the scored span. Both spans run from the first issue to the last target.
4. The selection span is declared. Code reads it from the issue lists of the training job, not from a person.

A refused hybrid appears under `blocked` with its reasons. The other methods still run.

A clean encoder needs a new S1 run that selects its epoch on 2019 to 2021 only. Such a run is not part of this change. Its tune years overlap its selection span, so the cut and calibration are optimistic. The summary says so in `notes.selection`. The scored years stay clean.

The encoder trained on 2014 to 2018, and the head fits on the same years. The embeddings of the head's train samples can look better than later embeddings. The tune and scored years show the real effect.

### Encoder export and reuse

- The approved template `forecast/templates_export_encoder.py` runs in the isolated environment. It reads one state dict with tensor-only loading and writes the GRU weights to npz.
- The host applies the weights in numpy. No generated code runs on the host.
- The manifest records the architecture, sizes, window, digests, spans and code revision. The registry stores it as a record.
- A hybrid bundle names its encoder record. No other bundle may name one.
- `mlops-predict` refuses hybrid bundles. The path has no encoder inputs yet.

The numpy GRU is tested against a gate-by-gate reference. It is not tested against torch, because torch is absent from the test environment. Compare it with the exported model before you trust a result.

## Promotion and rollback

1. Code registers the bundle as `candidate`.
2. The independent evaluator writes a report. `harness.attest` recomputes the model row from the saved weights, preprocessing, predictions and source. The registry takes that typed record, checks it against the report, and moves the bundle to `evaluated` or `rejected`. No caller can pass a verdict.
3. A human signs a record that names the bundle digest. Only then does the bundle become `approved`.
4. To roll back, ask for the previous approved bundle: `Registry.latest_approved(name, skip=1)`. Serve its digest with `mlops-predict`.

The log is append-only. A rollback adds no event and deletes nothing.

## Deployment-readiness checklist

Answer each item with evidence. One "no" means the bundle stays `research` or `validated_experimental`.

- [ ] The data checks pass, or each issue has a written reason.
- [ ] The preprocessing fits on the train span only. The feature record shows the spans.
- [ ] The scored period never includes the sealed test period.
- [ ] The independent evaluator scored the bundle, and the report digest is in the bundle.
- [ ] The result beats the persistence reference with its lower limit above zero.
- [ ] A classifier beats the base rate and is not the majority class.
- [ ] Calibration and the alarm cut come from validation data.
- [ ] A signed human record names this bundle digest.
- [ ] The previous approved bundle is known and a rollback was tried.
- [ ] The environment pins and the code revision are in the bundle.
- [ ] The model card states the limits and what the model is not for.
- [ ] Operational evidence exists: monitoring, drift checks and an incident path. This item has no code path today.

## Limits

- No bundle can reach `deployed_production`. There is no code for operational evidence.
- The methods are small. Trees use at most 200 trees of depth 4. The only neural part is a frozen encoder. This layer trains no neural model.
- No hybrid has run yet. No encoder exists that passes the chronology rules.
- `mlops-run` has been tested on a synthetic file in the test suite. No number from the real NEA file is claimed here.
- The data checks on the NEA series report issues. The run saves them and does not stop on them.
- The persistence method fills a missing lag with the train mean. The `B0_persistence` baseline looks back six hours instead. The two can differ in hours with a gap.
- The scored years are validation years. The locked test decision is separate and is not made here.
- A tree output has no uncertainty estimate.
- Registry files are local. There is no remote store, no access control and no lock for two writers.

## Add a method

A new method is one `Method` entry in `mlops/families.py`. Give it an ID, a family, its tasks, a typed config, a fit function, a predict function and an eligibility check. Add its ID and config to `harness/families_run.py` to run it on NEA data.

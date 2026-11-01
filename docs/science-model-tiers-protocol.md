# Model tiers protocol, version 1

Status: recorded before any tier result exists. This adds to
`docs/science-data-forecast-protocol.md` and changes none of its rules.

## 1. Purpose

EarthLab does not compete with a large foundation model. It uses a costly model as a resource.
The question is: can an agent-managed pipeline turn a costly model into a small model that keeps
the skill, and can it show this with paired evidence?

The pipeline has three possible uses for a costly model, in order of cost:

1. Run it as an expensive tier for a small number of hard cases.
2. Fine-tune it on approved data.
3. Distil it into a small student, then run the student by default.

## 2. Rehearsal on PM2.5 data

The rehearsal uses the E1 data, splits, horizons, feature rules and evaluator.

- Teacher: a seed ensemble of larger GRU models. It is not Prithvi.
- Direct student: a small GRU trained on labels.
- Distilled student: the same size and seed, trained on labels and teacher values.
- Teacher values come only from train samples.

Decision rules, set now:

- Distillation helped only if the lower 95% limit of paired MAE skill, distilled against direct,
  is above zero.
- A model is adoptable only if it passes rule 9.1 of the forecast protocol on validation.
- If distillation did not help, the report says so.

All scores are on validation. Several models share that period, so a small validation gain can
come from selection. The test period stays sealed and needs a lock and a human decision.

## 3. Prithvi route

Prithvi-EO-2.0-300M-BurnScars reads six-band HLS imagery. It cannot read PM2.5 series, and it
cannot read the single-band MCD64A1 raster. It is a burned-area path only.

| Stage | Work | Pass condition |
|---|---|---|
| P0 | Approve the pinned weights and chips | Signed human approval; digests match |
| P1 | Reproduce an official test chip | Band order and output match the model card |
| P2 | Score the dNBR baseline on the same test chips | Burned-class IoU, precision, recall, area error |
| P3 | Fine-tune on the official split, if P1 and P2 pass | Better than dNBR on test chips |
| P4 | Distil a small U-Net from teacher masks | Paired IoU limit against a direct student |
| P5 | Transfer to Kalimantan | Needs independent reference masks |

Limits:

- The published scores are for US chips. Performance in Indonesia is not known.
- MCD64A1 is not pixel ground truth for P5.
- Each stage stops the route if it fails. The report then states where it stopped.

Costs: the weights are 1.30 GB and the chips are 2.65 GB. The training stack needs TerraTorch in
the isolated environment. Each large transfer is one signed human decision. A catalogue entry
grants nothing.

Known gap: the fetch code refuses redirects, and on 2026-11-01 the weights URL answered 302 to a
CDN host. An approved transfer fails closed today. An owner decision is needed before that rule
changes.

## 4. What this does not claim

The rehearsal shows the mechanism on small data. It is not a Prithvi result, and it says nothing
about burn-scar accuracy.

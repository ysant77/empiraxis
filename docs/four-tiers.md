# Four difficulty tiers

This file maps the existing evidence to four engineering tiers. No run was made for it. Each row names the run that holds the evidence, and whether a Meta model took part.

## Map

| Tier | Task | Published evidence | Other evidence | Meta model | Decision |
|---|---|---|---|---|---|
| Simple: deterministic | QA-aware burned area from MCD64A1; wind geometry checks | `examples/replay/sb05-september`: Muse called the burned-area tool, and the verifier checked the area | review-gate-v2 Part B, `burned-area-method` without the gate: harness run, 702.5 s, 4 model calls, `adopt_limited`, local | Muse Glimmer chose the tool, or the raster method | Report September 2015, hold back October 2015 |
| Medium: statistical | PM2.5 exceedance with persistence alarm and logistic regression | `examples/replay/scenario-muse-team-exceedance`: 17 model calls, 4 tool calls | Ridge and trees bundles, `docs/model-acceptance-v1.md` | Muse Glimmer as PM, Lead and two specialists | Keep the persistence alarm |
| Hard: neural and hybrid | GRU regression; frozen GRU encoder with a fitted logistic head | `scenario-s1-regression`, `scenario-s2-encoder-reuse` | `docs/distillation-results-v1.md` | None. Deterministic presets. | S1: adopt with limits. S2: keep the baseline. |
| Complex: heterogeneous | ERA5 wind and rain with FIRMS boxes; satellite suitability | `scenario-s3-transport`, `scenario-s4-resource-request` | Prithvi and HLS inventory, `docs/release-acceptance.md` | None in these runs | S3: abstain. S4: request resources. |

## The shared lifecycle

The harness lifecycle has these typed records:

1. `request.json`: the research request.
2. `problem.json`: the typed problem.
3. `profile.json`: measured data facts.
4. `suitability.json`: which strategies code allows.
5. `plan-1.json`: the plan.
6. `evaluation-plan-1.json`: independent scores.
7. `decision.json`: the decision, which waits for a person.

Each step is a `harness_transition` in the trace.

| Run | Tier | Full harness lifecycle |
|---|---|---|
| `scenario-muse-team-exceedance` | Medium | yes |
| `scenario-s1-regression` | Hard | yes |
| `scenario-s4-resource-request` | Complex | yes |
| Part B `burned-area-method`, local | Simple | yes |
| `sb05-september` | Simple | no: the investigation loop, with its own claim verifier |
| `scenario-s2-encoder-reuse` | Hard | no: the trace records packaging of saved job results |
| `scenario-s3-transport` | Complex | no: the trace records packaging of saved job results |

So one lifecycle is shown in each tier, but not by every published run. The simple tier's harness run is local, not published.

## What the tiers show

- A Meta model took part in the simple and medium tiers. The hard and complex runs are deterministic presets, and their pages say so.
- No tier shows a learned model that beats the simplest suitable method in every subgroup. That is a result, not a missing step.
- No deep learning ran in the complex tier. The data did not support it: the imagery did not cover the box, and no reference masks existed.

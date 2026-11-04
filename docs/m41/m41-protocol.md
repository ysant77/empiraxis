# M4.1 protocol: a council that assesses evidence (experiment m41-v1)

Status: frozen. This file, `config/assess/council.yaml`, `config/assess/answer-keys.yaml`,
`examples/assess/packages/` and `examples/assess/critic-cases.json` are committed before any
M4.1 model run. A later change goes in a dated "Amendments" section. The M4 protocol
(`docs/m4/m4-protocol.md`) and all M3 and M4 records stay unchanged.

## 1. Question

Does a council of different checkpoints, with typed specialist assessments and an optional
independent critic, make better scientific decisions on real evidence than a deterministic
pipeline or a single Muse Lead? What does each role add, and at what cost?

This is an engineering screen with small counts. It does not claim general accuracy.

## 2. What changed from M4

| M4 | M4.1 |
|---|---|
| Specialists call one fixed tool and write a note. | Specialists return typed assessments (`DataAssessmentV1`, `ModelAssessmentV1`) with findings that cite package ids. |
| Tool loop with `tool_choice: auto`. Qwen answered in text and the run failed. | One JSON object per call, constrained by the contract's schema (llama.cpp grammar), then parsed by the contract. One repair turn. |
| Temperature 1.0 for every seat. | Temperature 0.0 and seed 20261104 for the primary benchmark. A separate stochastic condition uses 1.0. |
| Training runs inside each attempt. | No training. Every arm reads the same frozen evidence package. |
| The critic only checks cited numbers after the evaluator. | The critic reviews the Lead's plan for faults of method. The Lead accepts or rebuts each finding once. |

## 3. Roles and bindings

| Role | Arm H, HC checkpoint | Output | Power |
|---|---|---|---|
| Data Specialist | Llama 3.2 3B Instruct | `DataAssessmentV1` | advisory |
| ML Specialist | Qwen3 4B Instruct 2507 | `ModelAssessmentV1` | advisory |
| Engineering Lead | Muse Glimmer 30B | `LeadPlanV1`, `RebuttalV1` | proposes a decision |
| Scientific Reviewer | set by the critic test (section 5) | `CritiqueV1` | advisory |
| Product Manager | Muse Glimmer 30B | `PMReviewV1` | forward, revise or abstain |
| Evaluator | code (`assess/checks.py`, `assess/policy.py`) | check reports, code rule | decides facts |
| Director | human | adoption | final |

Muse stays loaded. One small model at a time runs on a second port. Code reads the served file
from `/props` and compares it with `config/benchmark/checkpoints.yaml` before each role.
A role that fails is recorded. No other model replaces it.

## 4. Scenarios (real evidence, frozen packages)

| Package | Scenario | Source |
|---|---|---|
| `a-model-selection-m3` | A: retain the ridge, adopt a candidate for a limited purpose, or validate more | M3 run `829fed`, M4 run `40d596` |
| `b-nea-provenance` | B: the 17 NEA API and file disagreements | acquisition run `95e7a3` |
| `c-fire-weather-sufficiency` | C: does the 2015 evidence justify a fire and wind claim | `docs/evidence/haze-2015-ablation.json` |
| `d-multisource-design-m5` | D: which ERA5, FIRMS, IMERG, HLS, SMAP inputs fit an issue-time experiment | M5 branch commit `9d7ebf1`, read-only |

`scripts/m41_build_packages.py` builds them. Each source records the SHA-256 of its file.
No package is a fixture. The answer keys were written before any run. No model sees them.

## 5. Critic test

24 frozen cases on the four packages: 12 seeded faults (3 per package) and 12 clean plans.
Critics: rule critic (code), Muse second pass, Llama 3.2 3B, Qwen3 4B, Llama 3.1 8B.

Scoring by code:

- **Usable:** the critique parses (after at most one repair).
- **Detected:** a finding has the seeded fault class.
- **High finding on a clean case:** a false rejection.
- **Unsupported finding:** a finding that fails the code check (unknown id, wrong cited value,
  number not in the package, forbidden phrase).

Engineering gates for a model critic to be **on by default** (advisory):

| Gate | Threshold |
|---|---|
| Usable | at least 22 of 24 |
| Detected | at least 6 of 12, and more than the rule critic alone |
| High finding on clean | at most 3 of 12 |
| Unsupported findings | at most 20 percent of its findings |

**Critic for arm HC.** The non-Muse checkpoint that passes the usable and clean-case gates and
detects the most faults. Ties go to fewer unsupported findings. If none passes, arm HC uses the
non-Muse critic with the most detections and the report labels the critic experimental.
The critic never sets the decision. The code rule and the human do not read it.

## 6. Qwen preflight

The M4 failures (2 of 2) are kept. The new preflight separates the causes:

1. Server and checkpoint identity (`/props` file name and file SHA-256).
2. M4 protocol reproduction: a tool loop where the closing tool is optional (`tool_choice: auto`).
3. The same loop with the closing call forced (`tool_choice: required`).
4. The M4.1 protocol: schema-constrained `ModelAssessmentV1` on the four packages, two seeds.

Gate for the ML Specialist seat: at least 7 of 8 valid assessments in condition 4. Failures
stay in the denominator.

## 7. Council benchmark

Arms on all four packages, one run each, temperature 0.0, seed 20261104:

| Arm | Roles |
|---|---|
| F | code rule only |
| S | Muse Lead |
| T | Muse in all four roles |
| H | Llama data, Qwen ML, Muse Lead and PM |
| HC | H plus critic and one Lead response |

Extra conditions: **repeat** (H on A and D again at temperature 0.0, same seed) and
**stochastic** (HC on A twice at temperature 1.0).

### Primary metrics (per run, from code)

- **Decision correct:** the final decision is in the answer key's `acceptable` list.
- **Agrees with code rule:** the decision is in the code rule's allowed list.
- **Known faults raised:** key faults matched by a backed finding of any role (fault class and
  at least one key evidence id).
- **Unsupported content:** findings that fail the code check, plus final-plan checks that fail.
- **Excluded inputs:** every `must_exclude` source is absent from `inputs_used` when the
  decision proceeds or adopts.
- **Trace integrity:** the hash chain verifies.

### Secondary metrics

Model calls, tokens and wall time per role; model load time; repairs; failed roles; specialist
contribution labels (section 8); critic findings accepted and rebutted.

## 8. Specialist contribution labels (code)

For each specialist in each run: `valid_output`, `detected_known_fault`, `new_backed_concern`
(a backed finding whose class is not in the key), `unsupported_finding`, `redundant` (all its
backed findings repeat a class the code rule already flagged), and `decision_changed` (a finding
the Lead accepted whose action is reflected in the final excluded inputs or decision).

## 9. Disqualifiers

Broken trace chain; a served file that differs from the registry; a model output used without
a contract parse; any read of the sealed test period; any change to a package after its hash
was recorded.

## 10. Acceptance for M4.1 (from the owner brief)

A council result is reported as a benefit only if it is visible against arm F or arm S on the
same package. One run per cell gives counts, not rates with intervals. A role that adds nothing
is reported, with a proposal to remove it or call it only when needed.

## Amendments

### Amendment 1 (2026-11-04): findings-first critic contract

- **What happened.** In the critic test, Llama 3.2 3B and Qwen3 4B gave 24 of 24 usable
  answers with verdict `no_concern` and no findings on every case, faulty or clean.
- **Suspected cause.** `CritiqueV1` puts `verdict` before `findings`. Under grammar decoding a
  model without a reasoning phase writes the verdict first, before it has reviewed anything.
  Muse writes a reasoning text before the JSON, so the order matters less for Muse.
- **Change.** Add `CritiqueV2`: the same fields, with `findings` first and `verdict` last.
  Run it as a separate condition (`--contract v2`) for the small critics. V1 results stay in
  the record and in the report.
- **Use in arm HC.** `critic_contract` in `config/assess/council.yaml` selects the contract.
  The HC critic and its contract are chosen by the section 5 rule over all critic results
  (V1 and V2), before the first HC run. The choice is recorded in `critic-choice.json`.

### Amendment 2 (2026-11-04): package E from the M5 package

- **Why.** The brief asks M4 to consume the M5 package, not to read M5 files on its own.
  M5 published `scientific_evidence_package_v1.json` (version `m5-evidence-1`) at commit
  `feeeef9` after package D was frozen.
- **Change.** `assess/m5_adapter.py` reads that package and the Stage T result file it lists.
  The adapter refuses a file whose SHA-256 differs from the package. Package D stays as frozen.
- **Availability rule for package E.** M5 classes a source by its own rule. For a T+6 hourly
  experiment the adapter counts a source as issue-time valid only when M5 classes it so and its
  nominal latency is at most 24 hours. A source M5 gated out or did not assess is `unknown`.
  This rule is M4.1's, not M5's.
- **Version used.** Before any run on E, M5 froze its B and C protocols and published
  `m5-evidence-2` at commit `458f297`. Package E is built from `458f297`. Its sources and facts
  equal the `feeeef9` build; only the M5 version and package hash differ.
- **Runs.** Arms F, H and HC on package E, after the main matrix. The answer key for E is in
  `config/assess/answer-keys.yaml`, written before the first run on E.

### Amendment 3 (2026-11-04): owner role assignment and escalation to the human

Written before the first council run. The owner set these role targets.

| Role | Checkpoint |
|---|---|
| Product Manager | Muse Glimmer 30B |
| Engineering Lead | Muse Glimmer 30B |
| Data Specialist | Llama 3.2 3B Instruct |
| ML Specialist | Qwen3 4B Instruct 2507 |
| Scientific Critic (default, arm HC) | Muse Glimmer 30B, separate review role and prompt |
| Alternative Meta critic (arm HC8) | Llama 3.1 8B Instruct, only after it passes all section 5 gates |
| Numerical checks and enforcement | code |
| Final adoption | human director |

- **Independence.** A Muse critic runs on the Lead's checkpoint. It is a separate role, not an
  independent model. `council_formed` records `critic_independent_checkpoint`. A report claims
  an independent-model critique only for a run where that field is true.
- **Alternative critic.** Llama 3.1 8B runs as critic only if it passes all four section 5
  gates (V1 or V2 contract) on the same 24 cases as Muse. Membership in the Meta family is not
  a reason to pick a critic. All earlier critic results stay in the record and are counted,
  including the Llama and Qwen critics with zero detections and the M4 Qwen failures.
- **This replaces the section 5 rule for arm HC.** The section 5 gates still apply and are
  reported for every critic, Muse included. A Muse critic that fails a gate stays the default,
  and the report says that it failed.
- **Authority.** The critic raises findings with evidence ids. The Lead answers each one. Code
  checks numbers and mandatory constraints. No model approves an experiment, changes a number,
  skips a provenance check or overrides the human.
- **Escalation.** At the human gate, code lists unresolved material issues
  (`escalations` in `result.json` and the `human_gate` record): a failed role; a decision
  outside the code rule; a failed Lead or rebuttal plan check; a medium or high finding that the
  Lead did not accept; items the Lead marks unresolved; a PM action other than forward. The list
  does not change the decision. The human gate stays mandatory.
- **Order of runs.** Main matrix (F, S, H, HC, T on A to D), HC8 if it passes, package E
  (F, H, HC, and HC8 if it passes), repeat, stochastic.
- **Out of scope.** Dynamic routing is deferred. It will be tested later, on its own, against
  fixed routing and a simple cost-aware rule router.

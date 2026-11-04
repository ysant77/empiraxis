# M4.1 architecture: the assessment council

Code: `src/earthlab/assess/`. Config: `config/assess/`. Frozen inputs: `examples/assess/`.
Protocol: `docs/m41/m41-protocol.md`.

## 1. Flow of one run

```
evidence package (frozen, hashed)
  -> code rule m41-v1 (assess/policy.py)          recorded, never shown to a model
  -> Data Specialist  -> DataAssessmentV1         code checks each finding
  -> ML Specialist    -> ModelAssessmentV1        code checks each finding
  -> Engineering Lead -> LeadPlanV1               code checks plan and coverage
  -> Scientific Reviewer -> CritiqueV1            advisory; code checks each finding
  -> Engineering Lead -> RebuttalV1 (one round)   code checks plan and coverage
  -> Product Manager  -> PMReviewV1               forward, revise or abstain
  -> human gate (awaiting_human)                  the director decides
```

Each step writes hash-chained records to `trace.jsonl`: `run_started`, `role_binding`,
`council_formed`, `code_rule`, `model_switch`, `model_turn`, `role_output`, `checks`,
`run_failed` or `human_gate`. The result file holds every role output, every check report,
the code rule and whether the proposed decision agrees with it.

## 2. Authority

| Who | Can | Cannot |
|---|---|---|
| Code (checks, policy) | Validate refs, values, numbers, words, inputs; compute the code rule | Approve adoption |
| Specialists | Raise typed findings with evidence | Set a decision, change a number |
| Lead | Propose a decision and plan; accept or rebut findings | Change the code rule or a check |
| Reviewer | Raise advisory findings | Score, approve, set thresholds, change outputs |
| PM | Forward, ask for a revision, abstain | Approve adoption |
| Human director | Adopt or reject | |

A model output is used only after its contract parses it. Model text never becomes a tool call,
a command or a config change. The package text goes to a model as data inside the user message.
The system message holds only the role instruction.

## 3. Model serving

- Muse Glimmer 30B stays loaded on port 8080 (`reasoning_effort: low`).
- `SideServer` runs one small model at a time on port 8081. It loads the GGUF file named in
  `config/benchmark/checkpoints.yaml`, waits for `/health`, reads `/props`, and stops the run
  if the file name differs. Load time is a `model_switch` record.
- Every call sends `temperature` and `seed`. The primary benchmark uses 0.0 and 20261104.
  Temperature 0.0 does not promise identical output; the repeat condition measures it.
- Output is constrained by the contract's JSON schema (llama.cpp grammar). The contract then
  parses it. A contract fault gets one repair turn. A transport fault ends the role.

## 4. The M5 to M4 interface: `EvidencePackageV1`

M4.1 reads M5 evidence. It does not acquire, recompute or edit M5 data.

| Field | Meaning |
|---|---|
| `package_id`, `scenario` | Name and kind: `model_selection`, `provenance`, `sufficiency`, `design` |
| `question`, `study_area`, `interval`, `target` | The scientific question and its scope |
| `acceptance_criteria` | What a good answer must do; the PM checks them in order |
| `sources[]` | `id`, `dataset`, `role` (observation, estimate, reanalysis, derived, evaluation), `availability` (issue_time_valid, hindsight, unknown), `latency_hours`, `sha256`, `origin` |
| `facts[]` | `id`, `statement`, `value`, `unit`, `source`: every number a role may cite |
| `limitations`, `missing_inputs` | Known limits and inputs that are not yet validated |
| `allowed_decisions` | The decisions a run may propose |
| `fixture` | True only for a labelled fixture; all four packages here are real (false) |

Rules:

1. A package is built by a script from recorded files and is committed before use.
2. Each source records the SHA-256 of its file. M5 files are read from a pinned commit with
   `git show <commit>:<path>`; `origin` is `m5@<commit>:<path>`.
3. No absolute local path enters a package.
4. A value that no run produced does not enter a package. An input that is not yet validated
   goes in `missing_inputs`, not in `facts`.
5. A new M5 result needs a new package version. A package does not change after its hash is
   recorded in a run.

Package D (`d-multisource-design-m5`) is built from M5 commit `9d7ebf1`: Stage T results for
2019, rung I1 for 2015, and the HLS and SMAP quality checks.

## 5. Where the UI shows it

Control Room, section "Scientific council investigations (M4.1, recorded)"
(`src/earthlab/ui/assessment.py`). It reads `examples/assess/replay/<run>/` and shows the
checkpoint of each role from the trace, the specialist findings with their code checks, the
Lead's answers, the reviewer's findings and the Lead's response, the code rule, the final plan
and the human gate. It calls no model.

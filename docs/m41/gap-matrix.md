# M4 to M4.1 gap matrix

Base: branch `feat/m4-usable-council`, cut from the reviewed M4 head `1065cea`. The M4 commits,
the M3 run, the 17 M4 attempts, the 2015 ablation and the M4 protocol are unchanged.

The original heterogeneous-council specification did not reach the M4 session (see
`docs/m4/m4-protocol.md`, "Assumptions"). This matrix uses the owner's M4.1 brief of
2026-11-04 as the requirement. That is a limit of this audit.

Status words: **implemented**, **partial**, **absent**, **unsupported** (tried, and the
evidence says it does not work).

| Area | Requirement | M4 status | M4 evidence | M4.1 status | M4.1 change |
|---|---|---|---|---|---|
| Role bindings | Each role served by a recorded checkpoint, no silent substitution | implemented | `role_binding` and `council_formed` records (`harness/identity.py`) | implemented | Same records per role in `assess/council.py`; a failed role ends the run, no other model is called (`test_a_failed_specialist_is_not_replaced`) |
| Checkpoint check | Served file equals the registry | partial | `scripts/m4_preflight.py` ran by hand before a block | implemented | `assess/serving.py` reads `/props` before each role on the side server and before each run for Muse |
| Sequential serving | Load, unload and readiness, with measured cost | absent | One extra server, started by hand | implemented | `SideServer` loads one small model at a time and records `model_switch` seconds |
| Structured output | Typed, schema-checked role outputs | partial | Tool calls checked by code; free-text notes | implemented | Grammar-constrained JSON per contract; contract parse; one repair turn |
| Data Specialist | `DataAssessmentV1` with evidence-cited findings | absent | Called `prepare_data` and wrote a note | implemented | `DataAssessmentV1`; each finding cites package ids and values; code checks it |
| ML Specialist | `ModelAssessmentV1` | absent | Called `train_models` and wrote a note | implemented | `ModelAssessmentV1` with baseline, eligibility, split, findings, experiment |
| Lead handles specialists | Accept, reject or clarify each finding | absent | The Lead did not read specialist notes as findings | implemented | `LeadPlanV1.dispositions`; code checks that every finding has an answer and no answer names an unknown finding |
| PM | Checks question and criteria; cannot approve | partial | PM forwarded; Llama failed the PM check | implemented | `PMReviewV1` per criterion; forward, revise or abstain only |
| Qwen | Reliable ML Specialist output | unsupported (0 of 2) | `docs/m4/benchmark-report.md`, runs `1f6f19`, `2a939b` | implemented | Fault found: optional closing tool call. Schema output 8 of 8 (`docs/m41/qwen-diagnostic.md`) |
| Independent critic | Methodological review with findings, measured | partial | Number-check critic; Llama usable 1 of 3 live | see results | `CritiqueV1` on the Lead's plan; 24-case test; gates in the protocol |
| Bounded rebuttal | Lead accepts or rebuts once | absent | none | implemented | `RebuttalV1`; one round; code checks coverage of the reviewer findings |
| Critic power | Advisory only | implemented | The critic set no score or outcome | implemented | The critic output never enters the code rule; tests cover a failed critic and a forged value |
| Decision policy | Predeclared rubric with subgroup and uncertainty checks | partial | `code_outcome` from evaluator thresholds | implemented | `assess/policy.py` (m41-v1): subgroup, reused validation, issue-time inputs, quality |
| Reproducibility | Explicit temperature and seed | absent | Temperature 1.0 everywhere | implemented | Temperature 0.0, seed 20261104 in every call; a stochastic condition is separate |
| Evaluator authority | Code decides facts | implemented | Deterministic evaluator | implemented | Code checks references, values, numbers, words, inputs and decisions |
| Human gate | Final adoption by a person | implemented | `awaiting_human` | implemented | Every run ends at `human_gate`; no role can approve |
| Trace and replay | Hash chain, offline replay | implemented | `harness-replay`, 0 mismatches | implemented | Same `RunTrace`; the Control Room shows recorded investigations |
| Method review | Usable on the M3 question | unsupported in M3 | Amendment 1 (`unknown_method`) | not changed | The M4.1 critic replaces it for this purpose; the gate stays off by default |
| M5 interface | Read-only evidence package | absent | none | implemented | `EvidencePackageV1` package D built from M5 commit `9d7ebf1` by `git show` |
| Security | Injection, forged claims, unknown refs, identity | partial | Fail-closed adapter; identity check by hand | implemented | Tests: injected package text, forged cited value, unknown ids, wrong `/props` file, unknown roles |

## Not changed on purpose

- The M3 harness, the training path and the M4 matrix runner. M4.1 adds a separate module
  (`src/earthlab/assess/`) that reads frozen evidence. It does not train.
- The method-review gate (Amendment 1 of M4).
- The `qa_reviewer` family rule in `config/roles/bindings.yaml`. M4.1 records which checkpoint
  served the reviewer and measures it. It does not use the harness seat gate.

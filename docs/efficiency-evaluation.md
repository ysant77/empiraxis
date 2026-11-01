# Routing and prompt-efficiency evaluation harness

This harness measures. It does not claim a saving. Only paired live runs can show one, and
none has been run. Nothing in `src/earthlab/efficiency/` calls a model, reads a credential,
downloads a file or changes a workflow contract or a production prompt.

## Commands

```bash
uv run --all-extras python -m earthlab.efficiency profile --runs ~/Documents/meta-ai/earthlab-live-runs-v53
uv run --all-extras python -m earthlab.efficiency review
uv run --all-extras python -m earthlab.efficiency route "<question>" --case-id <case>
uv run --all-extras python -m earthlab.efficiency plan
```

Add `--json` to `profile` and `review` for machine output. Every command only reads and
prints.

## Phase 1: offline profiler

`profile` reads `manifest.jsonl` and, for each row, `result.json` and `trace.jsonl` in the
run folder. It never writes there.

Rules:

- A model call goes to the role named by the runtime's `role_invocation` brackets. If there
  is no bracket, it uses the `role` field of the turn. If there is neither, it is the
  engineer (the direct arm has one role).
- A value that no call recorded is `missing` (`None` in JSON), never zero. A sum covers only
  the calls that recorded the field. `calls_with_usage` and `calls_with_wall` give that
  count.
- Local compute (wall seconds of model calls) is kept apart from billed provider cost.
  Billed cost is not measured on these runs. The runtime's own price-table estimate is
  stored separately as `estimated_cost_usd`. Energy is not metered.
- Goal satisfaction compares the final status with the first word of the manifest's
  `expected` text (`verified` or `abstained`). It is `None` if that cannot be decided.
- A manifest row with no run folder, and a run folder with no manifest row, are listed as
  anomalies. The profiler does not guess a join.
- Stage overhead is the share of model tokens that the PM and the orchestrator spend, per
  run, when every call in the run recorded usage.

### Findings from the 19-run evidence set

The brief names 19 runs. The manifest at `earthlab-live-runs-v53` has **24 rows**:

- 23 rows have a trace and a result.
- 1 row (stage s3, WD-03, separate) has `run_id: null` and no `replay` record. A run folder
  `20261031T182749Z-cc7b15` is not in the manifest. Its start time is 2 seconds after that
  row. The profiler lists both and does not join them.
- The run set spans 4 source commits: 12 runs at `5b91554`, 5 at `a664698`, 4 at `811c1f0`
  and 3 at `805916d`.

Counts below use the 23 complete rows (direct 9, combined 8, separate 6). Medians cover runs
that recorded the field. These are descriptive. Cells hold one to four runs.

| Arm | Runs | Goal met | Role | Calls | Prompt tok | Completion tok | Model wall s |
|---|---|---|---|---|---|---|---|
| direct | 9 | 8 of 9 | engineer | 4 | 25,311 | 965 | 293 (all roles) |
| combined | 8 | 8 of 8 | PM | 2 | 1,536 | 1,362 | 296 |
| combined | 8 | 8 of 8 | engineer | 6 | 26,196 | 1,668 | 419 |
| separate | 6 | 6 of 6 | PM | 2 | 1,562 | 1,499 | 323 |
| separate | 6 | 6 of 6 | orchestrator | 1 | 800 | 302 | 62 |
| separate | 6 | 6 of 6 | engineer | 4 | 20,961 | 1,511 | 370 |

Notes:

- All 155 model turns recorded usage and wall time. No usage field was missing in this set.
- The one unmet goal is stage s1, WD-03, direct, at commit `805916d`. The causal question
  ended as `verified`, and the manifest expected an abstention. Later direct runs of WD-03
  abstained (2 of 2). The set cannot say why. The code changed between those runs.
- One separate run was not decidable (no artifacts), so "6 of 6" excludes it.
- Stage s3 alone (one commit, `5b91554`): median model wall is 226 s direct (4 runs),
  714 s combined (4 runs) and 704 s separate (3 runs with artifacts).
- The PM spends little on prompt tokens (about 1.5k) and much on completion tokens (about
  1.4k, mostly reasoning). In the s3 runs the PM took about 291 to 297 s of model time. The
  orchestrator took about 63 s. The engineer's tokens are mostly prompt. So in these runs
  the visible overhead of the PM and orchestrator is completion time, not prompt size. The
  set has too few runs to separate this from order and warm-up effects.
- Answer revisions: median 1 in direct and combined, 0 in separate.

### Uncontrolled factors

- **Run order.** Arms ran in sequence inside a stage. One run per cell cannot separate order
  from arm. `observed_conditions.start_order_by_stage` lists the order.
- **Guard warm-up.** Runs 4 of the set started with the guard not loaded
  (`s1/WD-02/direct`, `s2/WD-03/direct`, `s3/WD-01/direct`, `s4/WD-03/separate`). They carry
  load time that other runs do not. Three of the four are direct runs.
- **Hardware contention.** Other programs shared the machine, and a real experiment ran
  there. Only system wired memory and swap were sampled, on 17 of 24 rows. Process memory
  does not show model memory.
- **Code revision.** Four commits are mixed in the set.
- **Sampling.** Server defaults with a random seed.

## Phase 2: static prompt reviewer

`review` checks the production prompts as text. It outputs findings and candidate changes.
It does not rewrite a prompt and does not write a file. `Review.requires_approval` is
always true and `Review.rewrites_prompts` is always false.

| Rule | Check |
|---|---|
| R001 | The prompt speaks as the role the call serves. |
| R002 | Tools named in the text exist in the call's tool list. Offered tools that the text never names are `info`. |
| R003 | Required scientific constraints are stated, by role (no added value, half-open period, independent verifier, limitation instead of guessing, no causal claim, PM2.5 is not AQI, units and zone). |
| R004 | A prompt that reports findings requires finding IDs. |
| R005 | A tool prompt states a call budget and a permission boundary. A write tool needs an approval statement. |
| R006 | Conflicting limits for one unit, or one phrase told as both always and never. |
| R007 | A sentence repeated in one prompt or shared by several. Candidate: a shared hashed context. |
| R008 | Structured context inlined in each call. Candidate: an artifact reference. |
| R009 | Every format field is declared, so rendering cannot fail. |

Result on the four production prompts: no error. The `info` findings are five engineer tools
that the prompt text does not name (their schemas carry the description), one inlined case
catalogue in the PM prompt and one JSON record in the PM report prompt. These are candidates
for review only. The tool list for the engineer is a constant in `prompt_review.py`, and a
test checks that each name still exists in the source tree.

## Phase 3: router specification

The router is a pure function in `router.py`. It imports no model client. No model call
chooses a model: `routing_model_calls` is the constant 0 and a test keeps it so.

| Policy | Stages | Separate orchestrator call |
|---|---|---|
| A | PM, orchestrator, engineer, all Muse (the existing `separate` workflow) | yes |
| B | Smaller approved PM model, Muse orchestrator, Muse engineer | yes |
| C | PM, engineer. Code decides the next stage from the validated brief | no |

Policy C has the same call pattern as the existing `combined` topology. Its only new part is
a written, tested routing function. A live C-versus-`combined` run is not worth running unless
code replaces the `combined` path.

**Capability gates.** A candidate serves a role only if `Bindings.status(...).blockers(...)`
is empty: listed for the role, role implemented or opted in as experimental, provider
configured and enabled, preflight passed, licence checked and candidate enabled. The
bindings loader already refuses an enabled candidate without a licence check and a passed
preflight, so an unvalidated model cannot be enabled.

**Provider bindings.** Candidates bind in file order, first pass wins. B needs a PM
candidate that differs from the engineer candidate.

**Fallback.** B without an approved smaller PM falls back to A and records why. At the
recorded bindings, B always falls back, because the only small PM candidate is planned and
disabled. Any request with high complexity falls back to A. If a role has no candidate, the
decision lists refusals and `can_run` is false. There is no silent substitute.

**Complexity indicators** come from the text and a case ID that code already resolved. They
are: case registered, causal wording, forecast wording and number of named periods. Low
means a registered case, no causal or forecast wording and at most one period. Everything
else is high. These are string rules and are known to be coarse.

**Budget.** A decision carries an upper bound of model calls (1 PM brief, 1 orchestrator when
present, 12 engineer turns, 1 PM report; the 12 is the workflow's `max_turns`). A budget below
that bound is a refusal. A hosted provider needs a positive USD limit and a recorded price.
Local providers cost 0 USD, and their time is limited by `max_seconds`.

### Paired tasks and fixed acceptance criteria

`config/efficiency/paired_tasks.yaml` lists five paired tasks. They come from the visible
development suite (`WD-01`, `WD-02`, `WD-03`, `WD-04`, `WD-09`). The held-out set is not a
source, and the loader refuses it. The design is 5 pairs per task, a rotated policy order, one
unscored warm-up run, and fixed commit, weights, server build and guard policy. Hard criteria
H1 to H5 cover false verification, answer issues, gate compliance, correctness no worse than
A and missing fields. Adoption criteria P1 to P3 are fixed before any run. No run was made.

## Phase 4: compression

`compress.py` and `artifacts.py` give compact typed forms.

- `ArtifactStore` is write-once and content-addressed. A reference is a SHA-256 of the
  canonical JSON. A reference with no stored item raises `MissingArtifactError`. Changed
  bytes raise `ArtifactIntegrityError`.
- `CompactBriefV1` keeps route, case, intent, target quantity and the period inline. The
  question, each constraint and each clarification are references, and the provenance (request
  hash, topology, author) is a reference. A repeated constraint is stored once.
- `CompactEvidenceV1` keeps finding ID, quantity, value, unit, availability time,
  verification status, approval state and source hashes inline. The statement and each
  constraint are references. `available_at` must be timezone-aware.
- Decoding rebuilds the original record and compares it with `source_sha256`. A decoded
  record that differs raises an error.
- No step summarises text. A reference resolves to the exact original or fails.

These forms are not wired into any workflow. `inline_chars` is a size measure in characters.
It is not a token count and not a saving claim.

## Gates

```bash
UV_LOCKED=1 uv run --all-extras ruff check
UV_LOCKED=1 uv run --all-extras ruff format --check
UV_LOCKED=1 uv run --all-extras mypy src tests
UV_LOCKED=1 uv run --all-extras pytest
UV_LOCKED=1 uv run --all-extras python scripts/check_limits.py src tests scripts
```

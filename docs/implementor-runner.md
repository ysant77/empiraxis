# Trusted implementor runner and human patch approval (specification, not built)

Status: **planned**. Nothing in the repository runs a worker's code. The harness
(`earthlab.implement.harness`) asks a worker for a diff, screens it and records a trial.
The trial then stops at `acceptance.stage == "execution"` until a runner record exists.

The patch screen (`earthlab.implement.screen`) is a filter in front of human review. It
is **not a sandbox**: a pattern list and an import allowlist cannot prove code safe. The
runner below is the only place a worker's code may ever execute.

## What the runner must be

| Requirement | Why |
| --- | --- |
| A separate, disposable container or VM per trial, never the process that called the model | A worker's code must not reach model clients, keys or traces |
| No network (no default route, no DNS) | No exfiltration, no downloads |
| Read-only bind of a clean checkout at a pinned commit, plus one writable scratch copy of the task's `allowed_paths` only | The worker can create its target file and nothing else |
| No secrets in the environment; no provider keys, no `HOME` credentials | |
| CPU-only, at most 2 cores, 2 GB RAM, 120 s wall time, 64 processes, 100 MB scratch disk | Bounded resources; the dev tasks need a fraction of this |
| Fixed command allowlist: `python -I -m pytest -q -p no:cacheprovider <fixed_tests>` with the frozen acceptance file | No arbitrary commands, no installs |
| The acceptance file's SHA-256 is checked against `catalogue.ACCEPTANCE_SHA256` before the run | The tests a worker is scored on cannot change between workers |
| The patch's SHA-256 is checked against `ImplementationResultV1.artifact_sha256` before applying | The runner runs exactly what was screened and reviewed |
| The runner writes `ExecutionResultV1` from its own measurements: exit code, timeout, per-test outcomes, input manifest hash, wall time, peak RSS, hardware | Never from model text |
| The container is destroyed after the run; only the `ExecutionResultV1` record leaves | |

## Order of gates (enforced by `contracts.acceptance`)

1. **Proposal**: an `ImplementationResultV1` with status `proposed` for this task.
2. **Review**: no blocking `ReviewFindingV1` from the screen or any reviewer. A model
   reviewer can add a block; it can never lift a deterministic one.
3. **Execution**: a runner record for exactly this artifact hash, exit code 0, no
   timeout, and every fixed test passed.
4. **Human**: a `HumanPatchDecision` of `accept` for exactly this artifact hash.

Only then may a human open a pull request with the patch, on its own branch, where the
normal CI runs again. Nothing merges automatically.

## Human patch approval

- The reviewer sees the diff, the screen findings, the runner record and the task text.
  They do not see hidden model reasoning.
- An approval names one artifact hash. A changed patch needs a new approval.
- Approving a patch never approves a download, a paid call, training or a deployment.

## Fair comparison (Experiment B)

- Every worker gets the same `TaskSpec` text, interface, budget and frozen checks
  (`tests/test_implementor_acceptance.py`), and one revision after a blocked screen.
- One model is served at a time; record cold-start and warm timings separately.
- No fallback between models. A provider error is recorded as that worker's outcome.
- The deterministic reference (`earthlab.implement.reference`, arm R0) is the baseline.
  If it meets every check, a model worker has no advantage to claim on these tasks.
- These three development tasks are written by the developer. They are not a held-out
  set, and a small number of trials cannot show that one model family is better.

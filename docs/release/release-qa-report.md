# Release QA report

Date: 2026-11-04 (SGT). Checked commit: `35de956ff849f4c43d72ed047efc81f52873b585` (`origin/main`, M5 PR #118 merged).
Checkout: a clean worktree of that commit. No model server, GPU or network data download was used.

**Overall status: RED.** No portal submission exists and no receipt exists. Some gates below are open.

## Gates

| # | Gate | Result | Evidence |
|---|---|---|---|
| 1 | `uv sync --all-extras` | PASS | exit 0 |
| 2 | `ruff check .` | PASS | exit 0 |
| 3 | `ruff format --check .` | PASS | exit 0 |
| 4 | `mypy` (strict) | PASS | exit 0 |
| 5 | `scripts/check_limits.py src tests scripts` | PASS | exit 0 |
| 6 | `pytest` with the 85% coverage gate | PASS | 1,914 passed, 1 skipped, coverage 94.60% (gate 85%), 41 min 36 s on a loaded machine |
| 7 | GitHub CI on `35de956` (push to main) | PASS | run conclusion `success` |
| 8 | Offline replay of all 12 runs in `examples/replay/` | PASS | 12 of 12 exit 0 |
| 9 | Replay detects a changed file | PASS | one byte added to `decision.json` of S1: exit 1, "1 of 7 files CHANGED" |
| 10 | Replay of a missing run folder | PASS (exit 1), rough message | exits 1 with a Python traceback, not a short error line |
| 11 | UI smoke (replay mode) | PASS, one note | Streamlit started from the clean worktree. `?view=control&run=replay/scenario-m4-heterogeneous-council` shows trace intact (61 records), 13 model calls, and each seat with family, checkpoint file and SHA-256 prefix. S1 workspace renders. No browser console errors. Note: an unknown run (`run=replay/does-not-exist`) silently opens S1 and shows no message. |
| 12 | Source-to-screen ledger | PASS | `docs/release/source_to_screen.csv`: 31 claims, 0 mismatches against the committed artifacts |
| 13 | Secret scan, full history of `main` | PASS | gitleaks 8.30.1: 253 commits, no leaks. Regex scan: one fake test key only (`tests/test_events.py`). |
| 14 | Attribution trailers and authorship | PASS | 0 `Co-Authored-By` trailers. Authors: `ysant77` only (merge commits by GitHub). |
| 15 | Local developer guide files, `.agent/` and `.env` not tracked | PASS | not in `git ls-files`; all in `.gitignore` |
| 16 | Absolute local paths in tracked files | **FAIL** | `evals/results/heldout-v1/results.jsonl`: 45 lines hold a local home-folder path with the user name. Added in `9582251` (#31). It is in history. |
| 17 | Private project names | PASS | no hit in tracked files |
| 18 | Large binaries and weights | PASS | no weights. Largest files: receipts JSONL 3.6 MB, NEA CSV 3.1 MB, two MCD64A1 GeoTIFFs (small). |
| 19 | README accuracy | **FAIL (stale)** | see "README findings" |
| 20 | Licence statements agree | **FAIL** | see "Licence and visibility" |
| 21 | V1.1 fallback checksums | PASS | all four SHA-256 values in `video/README.md` (PR #116 head `1c30655`) match the local files |
| 22 | V1.1 fallback music rights | **FAIL** | V1.1 audio and credits frame use MusicGen (CC-BY-NC 4.0). The owner decided today: no music, or a verified licence. |
| 23 | Portal rules, deadline, edit policy | NOT RUN | the portal was not opened. Planning docs only: Nov 4 21:00 ET = Nov 5 10:00 SGT. |
| 24 | Portal submission and receipt | NOT RUN | owner action |
| 25 | M4.1 benchmark verdict | NOT RUN | PR #117 is draft at `4c08ba5`; Session A has not frozen the report |
| 26 | Video 2.0 | NOT RUN | Session C. Not reviewed here. |
| 27 | Hosted replay URL | NOT RUN | not published (`docs/submission.md`) |
| 28 | M5 commands that need raw data (`scripts/m5_run_ladder.py` and others) | NOT RUN | raw data is outside Git; the result files were checked instead (gate 12) |

## M5 wording finding (from the M5 audit)

- The merged evidence package labels FIRMS `fire_count_box_{a,b,c}` and IMERG rain features `issue_time_valid`. The FIRMS reason says "issue-time with +3 h". The data is the FIRMS MODIS standard-processing archive. The 3 h value is a nominal assumption, not a measured release time.
- README, portal text and film must say "nominal latency, assumed", not "issue-time valid". A later package version can add a third input class. The frozen M5 sources stay unchanged.
- M5-C onset audit (unmerged, `docs/m5-c-onset-audit-review` at `9180d6c9`): about 80% of events are continuations; 4 independent onsets; "insufficient independent onsets". M5-B has no result: ERA5 2017 to 2019 pressure-level files are missing.

## README findings (`README.md` at `35de956`)

1. The README has no section on M4 (heterogeneous council, PR #115) or M5 (multisource pilot, PR #118). The judges' main evidence is not on the front page.
2. "Known limitations" says "Team arms with mixed models did not run." The M4 replay `scenario-m4-heterogeneous-council` holds a run with Muse and Llama 3.2 3B. This sentence is now false.
3. "Known limitations" says "The critic is a second pass by the same model. It is not an independent reviewer." This is true for M3. In M4 the critic seat ran on Llama 3.2 3B. Say which run each sentence covers.
4. "What the Meta model did" lists Muse only. Llama 3.2 3B (M4 seats) is not named.
5. `docs/submission.md` is stale: release checklist dated 2026-11-03, "Repository visibility: Private", licence "Draft PR #91 proposes Apache-2.0", and the replay loop leaves out `scenario-m4-heterogeneous-council`.
6. Repository name, clone URL and setup commands are correct (`ysant77/empiraxis`, `uv sync --all-extras`, Streamlit command). No broken repository paths were found in README, `docs/submission.md` or `docs/demo-three-minute.md`.

The README is shared, so this report proposes text only. It does not change the README. A README update is a separate PR after the owner agrees.

## Licence and visibility

- GitHub API (2026-11-04): `ysant77/empiraxis` is **public**, licence detected as Apache-2.0. The session brief and the local guide say the repo is private until the owner makes it public. **Owner: confirm that the public state is intended.** If it is not, this is the first action.
- Because the repo is public, the absolute path in `evals/results/heldout-v1/results.jsonl` (gate 16) is already published. A fix in a new commit removes it from the tree but not from history. Do not rewrite history without an owner decision.
- `LICENSE` is Apache-2.0. `LICENSING.md` still says "draft licensing proposal", uses the old name "Axiom EarthLab", and says "The repository may remain private". The workspace guide says "MIT licence is planned". **Owner: choose one licence and update `LICENSING.md`.**

## Fallback recommendation

- **Code:** `35de956` (current `main`). CI is green on it, all 12 replays pass, the ledger matches. Use it unless #117 merges with green CI before the cutoff. The older `release/hackathon-2026` branch (`4e4a4f1`) has no M4 or M5; use it only if `main` breaks.
- **Video:** V1.1 picture is checksum-verified, but its audio has the CC-BY-NC MusicGen bed and its credits frame names it. Options, best first:
  1. Session C re-renders the credits frame without the music line, then muxes `voice.wav` only (Kokoro, Apache-2.0). Run the ASR word-match check again.
  2. Mux `silent.mp4` with `voice.wav` only, with no re-render. The credits then name music that is not there. Use only if option 1 cannot finish.
  3. Ship V1.1 unchanged only if the owner accepts CC-BY-NC for this non-commercial entry. This reverses today's decision.
- V1.1 shows M3 only. It does not show M4 or M5. That is acceptable for a fallback.

## Blockers (owner)

1. Confirm the public visibility of the repository is intended.
2. Choose the licence (Apache-2.0 in `LICENSE`, MIT in the guide) and fix `LICENSING.md`.
3. Decide on the absolute path in `evals/results/heldout-v1/results.jsonl` (redact in a new commit; history keeps it).
4. Pick the film: Video 2.0 or the voice-only V1.1. Do not ship the MusicGen bed.
5. Read the deadline and the edit policy on the portal itself.
6. Fill the `[M4.1 PENDING]` fields from Session A's frozen report.
7. Submit, and save the receipt. Until then the status stays RED.

## Commands

```bash
git worktree add <dir> 35de956ff849f4c43d72ed047efc81f52873b585
uv sync --all-extras
uv run ruff check . && uv run ruff format --check . && uv run mypy
uv run python scripts/check_limits.py src tests scripts
uv run pytest
for r in $(ls examples/replay | grep -v MANIFEST); do uv run earthlab --data-dir data/nea replay examples/replay/$r; done
gitleaks git --redact --no-banner --exit-code 1 --log-opts=origin/main .
```

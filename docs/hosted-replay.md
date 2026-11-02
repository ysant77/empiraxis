# Hosted replay

The hosted replay shows the recorded runs in the existing Streamlit app. It is a research prototype. It is not a forecast, not a health service and not a model service.

## What it can do

- Show the four scenarios and the recorded Muse team run on the three surfaces.
- Read only `examples/replay`. The app checks each run against `examples/replay/MANIFEST.json` and refuses a changed or missing file.

## What it cannot do

- Call a model, train, download, run a tool or start a process.
- Approve or deny a request. Replay has no approval queue.
- Read local data, run folders or keys.

## Entry and checks

| Item | Value |
|---|---|
| Entry file | `deploy/streamlit_app.py` |
| Dependencies | `deploy/requirements.txt`, pinned from `uv.lock` (Streamlit and the base packages only) |
| Python | 3.12 |
| Start command | `streamlit run deploy/streamlit_app.py` |
| Theme | `.streamlit/config.toml` |

At each page load, `earthlab.ui.hosted` refuses to start when:

- `EARTHLAB_UI_MODE` is set to a value other than `replay`.
- `EARTHLAB_REPLAY_DIR` names a folder other than `examples/replay`.
- An environment variable whose name ends in `KEY`, `TOKEN`, `SECRET`, `PASSWORD` or `CREDENTIALS` has a value. The message shows the name only.

Then it sets replay mode and runs `src/earthlab/ui/app.py`. Replay mode starts no metrics server and shows no live control.

Do not add secrets to the host. The app refuses to start if a credential has a value.

## Tests

- `tests/test_hosted_replay.py`:
  - The environment rules (9 cases).
  - An operator environment stops the app.
  - All 15 pages (3 surfaces by 5 runs), with network connections and child processes blocked. Each page is a replay with no action control.
- `tests/test_ui_surfaces.py`: a changed trace or result is refused.
- Manual check, 2026-11-02:
  - The entry started from an empty environment.
  - Five scenario pages loaded at 390 by 844 with no overflow, no error, no action button and no text input.
  - The first start found that Streamlit sets `MAPBOX_API_KEY` to an empty value. The rule now ignores empty values.

## Publish on Streamlit Community Cloud

Publishing is an owner action. It needs the owner's approval and the owner's account. A coding agent does not sign in or publish.

The host deploys a branch, not a commit. It redeploys when the branch changes. To pin the release, deploy from a release branch that points at the release commit.

### Before

1. Create a release branch at the release commit, for example `release/hackathon-2026`. Push it only after review, like any other branch.
2. Record the commit: `git rev-parse release/hackathon-2026`.

### Deploy

| Setting | Value |
|---|---|
| Sign-in | share.streamlit.io with the owner's GitHub account. Grant access to private repositories only if the repository is still private. |
| Repository | `ysant77/axiom-earthlab` |
| Branch | the release branch |
| Main file path | `deploy/streamlit_app.py` |
| Python version (Advanced settings) | 3.12 |
| Secrets (Advanced settings) | empty |
| Dependencies | `deploy/requirements.txt`. The host reads the entry file's folder first, so it does not use `uv.lock`. |
| Viewers | Invite named viewers while the repository is private. Make the app public only when the repository is public. |

### Check after deploy

Open each URL at desktop width and at phone width (390 px). Refresh each one.

- `?view=workspace&run=replay/scenario-s1-regression`
- `?view=lab&run=replay/scenario-s2-encoder-reuse`
- `?view=workspace&run=replay/scenario-s3-transport`
- `?view=control&run=replay/scenario-s4-resource-request`
- `?view=control&run=replay/scenario-muse-team-exceedance`

Each page must:

- show "Replay mode";
- show no error;
- have no run, approve, deny, train or download button;
- have no text input.

Then reboot the app from the host menu and open one URL again.

Record the URL, the commit and the date in `docs/submission.md`.

### Rollback

1. Point the release branch at the earlier release commit, through a reviewed change.
2. Reboot the app.
3. If the host fails, show the local replay and the recorded video. The local replay needs no network.

## Publication audit, 2026-11-02

The repository audit covered main at `a8a99d8`.

| Check | Result |
|---|---|
| Secrets in Git history | `gitleaks git` on 202 commits: no leaks. CI also scans the full history. |
| Weights, archives, pickles or environment files | None tracked. |
| Large files | `data/nea/Historical1hrPM2.5.csv`, 3.2 MB, under the Singapore Open Data Licence (`data/nea/DATA_CARD.md`). |
| Held-out v1 | `evals/results/heldout-v1/results.jsonl` holds scores and verified claims, but no question text. The question file stays outside the repository. |
| Machine paths | The held-out results hold 45 `run_dir` values with the owner's local home folder. Three docs name `~/Documents/meta-ai/...` folders. This is a frozen record, so it is not changed. |
| Private network address | `config/providers.yaml` has a sample LAN address with a comment to replace it. |
| Licence file | None. The owner chooses the licence before the repository is public. |

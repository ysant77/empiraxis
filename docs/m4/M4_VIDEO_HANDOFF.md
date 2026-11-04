# M4 video handoff

For the session that makes Video V2. Read this before you show M4. V1 shows M3 only and stays frozen.

## What M4 shows

- **One workflow, different checkpoints in different seats.** The recorded run is `scenario-m4-heterogeneous-council`. Meta Muse Glimmer 30B served the PM and the Lead. Meta Llama 3.2 3B Instruct served the data specialist, the ML specialist and an advisory critic.
- **Every seat names its checkpoint in the hash-chained trace.** A `role_binding` record gives the file name and SHA-256. A `council_formed` record says how many distinct checkpoints took part.
- **Code still decides.** Trusted tools train and reload the models. Separate code scores every model. The critic is advisory and sets no score, outcome or approval. A person decides last.

## What to open

Start the UI in replay mode (no model runs):

```bash
uv run --extra ui streamlit run src/earthlab/ui/app.py --server.address 127.0.0.1
```

| Page | Address query | What it shows |
|---|---|---|
| Research Workspace | `?view=workspace&run=replay/scenario-m4-heterogeneous-council` | Question, seats and checkpoints, critic state, model comparison, decision, limits. |
| Control Room | `?view=control&run=replay/scenario-m4-heterogeneous-council` | "Who took part" table with family, checkpoint file and SHA-256 for each seat. Stages. Critic note. |

The run has 61 trace records, head `c759977e`. Status: awaiting a human decision. The replay is a redacted copy. Model text and reasoning are removed.

## Numbers you may state

From run `20261103T140243Z-40d596` (primary scenario, arm T-L):

- 13 model calls on 2 checkpoints: Muse 8 (PM 2, Lead 6), Llama 3.2 3B 5 (data 2, ML 2, critic 1).
- Recommendation: adopt with limits, `candidate-1` (a GRU). MAE 4.575 µg/m³ against 4.680 for the lagged ridge and 5.465 for persistence. Above 55 µg/m³ it is worse than persistence (29.104 against 26.324). The code rule gives the same outcome.
- Critic verdict: no concern. Source: independent model.
- Wall time 1,846 s, mostly Muse.

Across the matrix (details in `docs/m4/benchmark-report.md`): 17 attempts, 8 reached the human gate, 3 of them with two checkpoints. The deterministic path took 23 s.

## What you must not say

- Do not say M3 had several models. M3 was four roles on one checkpoint. Never show Llama or Qwen in an M3 scene.
- Do not say the council is better, faster or more accurate. The data does not show it. The runs differ mostly in the Lead's sampled choices.
- Do not say Llama or Qwen "plan" or "reason" about the science. The specialists call fixed tools and write a note. The critic is weak: the independent critic gave one "no concern" and two unusable answers in three live runs.
- Do not say Qwen took part in a completed run. It failed in 2 of 2 attempts and is not in the replay.
- Do not say the independent critic found an error. The two live findings came from a Muse second pass, in other runs.
- Do not claim causes of haze, forecasts, health advice or approval by a model.

## Honest framing that is true

- "Muse plans. A small Llama model runs the specialist steps and reviews. Code checks every number. A person approves."
- "The trace names the file and hash of each model that took part."
- "Small models were unreliable in these seats. The system recorded each failure."
- "A model critic can catch a wrong sentence, such as a false 'lowest RMSE'. Code checks the numbers it cites."

## Real or replay

- The M4 page is a recorded replay of a real local run (Mac, llama.cpp). It makes no model call now.
- To show a live run, the owner must start both servers. This is slow: a Muse call takes minutes. Use the replay.

## Other recorded runs

Raw folders are in `~/Documents/meta-ai/m4-runs/` (not in the repo). To add another run to the replay list, use `scripts/add_team_regression_replay.py` with a new key and name. The two Muse runs with a critic finding are `20261103T152431Z-8e9959` (S-M) and `20261103T155207Z-9f4613` (T-M).

## Limits to keep on screen

- Validation years 2019 to 2023 were used in earlier experiments. The score is not independent.
- The sealed test period was not read.
- One run. No statistical claim.
- Research prototype. Not a forecast. Not health advice.

## Review status

Not reviewed by the main session. Not reviewed by the owner. V2 waits for both.

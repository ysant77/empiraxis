# Reproduce the evidence

`docs/evidence/live-runs.json` lists 19 live local runs: 17 command-line runs and 2 runs from the
operator interface. Each row has the Git SHA, model identity, guard digest, scenario, outcome,
timing and replay result. "NOT_RECORDED" means that the run did not store the value. Runs at
different commits are listed as they ran, and were not rerun.

`wall_seconds` is the measured wall time for the 17 command-line runs. For the 2 interface runs it
is the role time that the run recorded.

## Replay without a model

```bash
uv sync --all-extras
uv run earthlab --data-dir data/nea replay examples/replay/live-september-verified
uv run earthlab --data-dir data/nea replay examples/replay/live-october-abstained
```

Expected for September: area verdicts 2/2, month checks 1/1, input hashes match.
Expected for October: area verdicts 0/0, month checks 1/1, input hashes match.

## Run one live investigation

This needs the local model server and the guard. See "Run the Meta model locally" in the README.

```bash
uv run earthlab --data-dir data/nea workflow "How much area burned in the Kalimantan study box in October 2015?" --topology combined --provider local-glimmer --guard local-llama-guard --reasoning low --max-turns 12
```

A model run can differ between attempts. The verifier decides each number, so verified values
must stay the same.

## Limits

The evidence is from one Mac. The questions are development questions, not a held-out set. The
stage s3 matrix has one run per cell. Energy was not measured.

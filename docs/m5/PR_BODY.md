## Summary

This branch adds the M5 multisource environment pilot. It audits the data, freezes a protocol,
runs a small issue-time ladder on real data, and records what is not usable.

- Status matrix for every dataset at seven completion levels, with evidence.
- Source and licence register. Coverage inventory for 2015 to 2026 from catalogue metadata.
- Typed contracts for products, receipts (SHA-256, byte cap, authority), availability and QA masks.
- Capped Earthdata downloader. The token comes from the environment and is never logged.
- Readers: SMAP L3, HLS L30 (Fmask, NBR), IMERG layout (synthetic test only).
- Frozen protocol `m5-protocol-1` with a hash-check test. Amendments are in a separate file.
- Ladder R0 to R3 with stage P (2015, 2016) and stage T (train 2015 to 2018, score 2019).
- Daily association test (Experiment A) with a circular-shift null.
- Layer catalogue for a viewer, with explicit state and reason for each layer.

## Findings

- The published 2015 ablation reproduces exactly (30.76, 32.10, 36.73, 41.75).
- FIRMS features and trees gave no supported gain. On the 2019 held-out season they lowered the elevated-hour error
  by 39% and raised the all-hours error by 13%. This is exploratory.
- SMAP is unusable over Kalimantan (0 of 78 retrieved cell-passes have recommended quality).
- HLS has 2.7% clear land on both dates of the pilot pair, and high aerosol on more than 96% of pixels.
- Rung I1 (IMERG Early, 2015, Stage P): MAE 36.11 against 34.11 (R2) and 32.10 (R1). No gain; paired skill vs R2 -0.059 (-0.131, -0.005).
- IMERG pilot ran on four days; ERA5 and IMERG agree on mean rain, differ in timing for one corridor (not a validation).
- Experiment A cannot reach `supported_association` by design (Amendment 1).

## Not in this PR

Raw data (kept outside Git), the sealed NEA period, M3 evidence, a viewer, a neural model, ERA5 for 2016 (queued), IMERG beyond 2015.

## Checks

```
uv run ruff check . && uv run ruff format --check . && uv run mypy
uv run python scripts/check_limits.py src tests scripts && uv run pytest
```

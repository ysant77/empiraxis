## Summary

This branch adds the M5 multisource environment pilot. It audits the data, freezes a protocol,
runs a small issue-time ladder on real data, and records what is not usable.

- Status matrix for every dataset at seven completion levels, with evidence.
- Source and licence register. Coverage inventory for 2015 to 2026 from catalogue metadata.
- Typed contracts for products, receipts (SHA-256, byte cap, authority), availability and QA masks.
- Capped Earthdata downloader. The token comes from the environment and is never logged.
- Readers: SMAP L3, HLS L30 (Fmask, NBR), IMERG layout (synthetic test only; later checked on real files).
- Frozen protocol `m5-protocol-1` with a hash-check test. Amendments are in a separate file.
- Ladder R0 to R3 with stage P (2015, 2016) and stage T (train 2015 to 2018, score 2019).
- Daily association test (Experiment A) with a circular-shift null.
- Layer catalogue for a viewer, with explicit state and reason for each layer.
- Frozen protocols `m5-protocol-b-1` (M5-B) and `m5-protocol-c-1` (M5-C), with a hash check and an append-only amendments file.
- Event-rate count, M5-B and M5-C runners, and a versioned evidence package for M4 (current: `m5-evidence-4`).

## Findings

- The published 2015 ablation reproduces exactly (30.76, 32.10, 36.73, 41.75).
- FIRMS features and trees gave no supported gain. On the 2019 held-out season they lowered the elevated-hour error
  by 39% and raised the all-hours error by 13%. This is exploratory.
- SMAP is unusable over Kalimantan (0 of 78 retrieved cell-passes have recommended quality).
- HLS has 2.7% clear land on both dates of the pilot pair, and high aerosol on more than 96% of pixels.
- Rung H1 (ERA5, hindsight): 2015 MAE 41.75 vs 34.11 (R2); 2016 7.57 vs 7.39. No gain.
- Rung I1 (IMERG Early, 2015, Stage P): MAE 36.11 against 34.11 (R2) and 32.10 (R1). No gain; paired skill vs R2 -0.059 (-0.131, -0.005).
- IMERG pilot ran on four days; ERA5 and IMERG agree on mean rain, differ in timing for one corridor (not a validation).
- Experiment A, 2015 and 2016, 32 tests per season: none supported. Smallest shift-null p is 0.031 (2015, box B, lags 1 to 2) and 0.0625 (2016).
- Experiment A cannot reach `supported_association` by design (Amendment 1).

## M5-C: severe-event prediction (2019, held out)

- Headline: the skill comes from the PM2.5 lags (C2 Brier skill 0.425). The FIRMS increment is not supported:
  the C3 label `useful_signal` (skill 0.474, interval 0.267 to 0.643) fails the 24 h FIRMS delay check and the season-rank check.
- C1 (0/1 persistence) 0.142 and C4 (trees) 0.419: both intervals include 0.
- The 2019 season holds one episode (1,386 issues, 349 events). The interval is over weeks, not over independent episodes.
- No operational claim. No causal claim.
- Abstention bands 0.1 to 0.9 and 0.3 to 0.7 are post hoc and exploratory (Amendment C3). The owner asked for them before the run;
  the run came first. This is recorded as a deviation in the report. The rows are in `m5_c_v1_post_hoc_bands.json`
  and do not enter the label or the headline. The primary result `m5_c_v1.json` is unchanged.

## M5-B: regional transport consistency

- Status: BLOCKED. The protocol is frozen, and the runner and tests are in this PR. The run needs ERA5 for 2017 to 2019.
  The Copernicus queue had not delivered those files at push time. No M5-B number exists.

## Owner review corrections (2026-11-04)

- Strict JSON: `m5_c_v1.json` (nine NaN tokens) is unchanged. `m5_c_v1.strict_v1.json` is the valid-JSON export with null and a reason for each missing value.
  All M5 writers reject NaN and Infinity. A test parses every published `docs/m5` and `config/m5` JSON file strictly.
- Coverage-aware event labels (Amendment C4): a negative needs complete window coverage. No saved 2015 to 2019 score changes (rerun: 0 differences).
- Evidence package `m5-evidence-4` (new version). `m5-evidence-2` at commit `458f297` is untouched.
- Limits: latencies are nominal, 2019 is a reused test season, no causal attribution.

## Not in this PR

Raw data (kept outside Git), the sealed NEA period, M3 evidence, a viewer, a neural model, IMERG beyond 2015, a MAIAC reader.

## Checks

```
uv run ruff check . && uv run ruff format --check . && uv run mypy
uv run python scripts/check_limits.py src tests scripts && uv run pytest
```

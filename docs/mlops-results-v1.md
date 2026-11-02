# MLOps Foundation v1, measured results

Status: research results. These are historical validation scores, not forecasts. The sealed
test period was not read. Nothing here is approved: a bundle stays `evaluated` or `rejected`
until a signed human record decides it. S1 and S2 share one dataset.

Artifacts stay outside the repository in `earthlab-e1-runs/mlops-v1`. Data quality passed:
85,487 rows, no duplicate stamps, coverage 0.9999 in each region.

## S1: PM2.5 regression at T+6 h

Scored on the validation years, 2019 to 2023, by the existing evaluator.

| Method | Family | MAE | Skill (95% limits) | MAE above 55 ug/m3 | Recall above 55 | Status |
|---|---|---|---|---|---|---|
| Persistence | deterministic | 5.465 | 0 (reference) | 26.32 | 0.44 | rejected: no skill over itself |
| Climatology | deterministic | 6.134 | -0.127 (-0.170 to -0.086) | 58.08 | 0.00 | rejected |
| Ridge, 12 lags | deterministic | 4.650 | 0.148 (0.138 to 0.158) | 37.34 | 0.05 | evaluated |
| Trees, 40 at depth 3 | traditional ML | 4.747 | 0.130 (0.116 to 0.142) | 29.47 | 0.38 | evaluated |

Finding: both learned methods improve aggregate MAE and both are worse than persistence above
55 ug/m3. Ridge has the best aggregate score and the worst elevated-hour score, with a recall
of 0.05. The registry status `evaluated` does not carry this limit, so a reviewer must read the
subgroup row. Trees trade 0.10 of aggregate MAE for a much smaller elevated-hour loss.

## S2: threshold classification at T+6 h, frozen encoder reuse

Above 35 ug/m3, an experimental threshold, not AQI or PSI and not a haze label. Fit 2014 to
2018, tune 2019 to 2021, score 2022 to 2023. Base rate 0.0095 over 87,570 scored cells.

| Method | F1 | Precision | Recall | PR area | ECE | F1 gain over persistence (95% limits) | Status |
|---|---|---|---|---|---|---|---|
| Persistence alarm | 0.306 | 0.306 | 0.306 | 0.079 | 0.013 | reference | baseline |
| Train rate | 0.000 | none | 0.000 | 0.006 | 0.051 | -0.44 to -0.12 | majority class |
| Logistic | 0.162 | 0.503 | 0.097 | 0.200 | 0.003 | -0.24 to -0.06 | rejected |
| Trees | 0.157 | 0.476 | 0.094 | 0.171 | 0.003 | -0.20 to -0.09 | rejected |
| Frozen GRU + logistic | 0.255 | 0.425 | 0.182 | 0.200 | 0.003 | -0.17 to -0.00 | rejected |

Finding: reuse helped and was still not enough. The frozen encoder raises F1 over logistic and
has better calibration and PR area than the persistence alarm. Its F1 gain interval does not
clear zero, so the rule keeps the persistence alarm. The simplest method wins on the
pre-registered rule.

Encoder facts: a new S1 GRU, selected on 2019 to 2021 only, because the earlier S1 runs selected
on years that S2 scores and code refuses those. Training took 24.6 s, and the digest is
`4978e860`. Cut and calibration are optimistic, because the encoder was selected on the tune
years. The scored years stay clean. The numpy GRU matches torch to 2.6e-7 on 53 real windows.

## Not done

Bounded tuning has tests but no real search run. `mlops-predict` now has a run on real data, in `docs/model-acceptance-v1.md`. At this report it had tests but no run on a real
bundle. No bundle has a human decision.

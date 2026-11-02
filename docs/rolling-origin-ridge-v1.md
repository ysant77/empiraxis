# Rolling-origin selection of the ridge penalty

The B4 lagged-ridge baseline selects its penalty on validation MAE, then reports MAE on the same validation rows. This favours ridge.

This run selects the penalty on the train years only. It shows how much the validation selection changed the B4 score. The frozen B4 result does not change.

## Design

| Item | Value |
|---|---|
| Model | Ridge on 24 hourly lags per region, one model at T+6 h |
| Candidates | The B4 grid: 1, 10, 100, 1000, 10000. Set before the run. |
| Folds | Expanding window. Score 2016, 2017 and 2018. Each fold trains on the train years before its fold year. |
| Edge rule | A train issue whose target reaches the fold year is left out. |
| Scaling | Fitted on each fold's train rows |
| Rows used | Train split only, 2014-04-01 to 2018-12-31. No validation or test row enters a fold. |
| Search code | `earthlab.mlops.tuning.search`, label `rolling_origin_train` |
| Budget | 300 s and 8 GB. Used: 0.5 s. |

Random K-fold would mix future rows into training, so it was not used.

## Result

T+6 h MAE in µg/m³, mean over the five regions:

| Penalty | 2016 | 2017 | 2018 | Mean |
|---|---|---|---|---|
| 1 | 6.724 | 6.136 | 5.461 | 6.107 |
| 10 | 6.721 | 6.135 | 5.460 | 6.105 |
| 100 | 6.687 | 6.125 | 5.457 | 6.090 |
| 1000 | 6.534 | 6.070 | 5.437 | 6.014 |
| **10000** | 6.438 | 6.014 | 5.419 | **5.957** |
| Persistence | 7.775 | 7.362 | 6.786 | 7.308 |

The train folds select penalty 10000. Ridge beats persistence in every fold.

B4 selected penalty 1000 on validation, with a validation MAE of 4.680. With penalty 10000, the validation MAE is 4.697.

So the validation selection improved the B4 score by 0.017 µg/m³. This changes no decision:

- In S1, the GRU scored 4.588 and persistence 5.465.
- The ridge MAE lies between them with either penalty.

## Limits

- 10000 is the largest value in the grid, so the best penalty may be larger. The grid was not widened after the result.
- The 4.697 is not an independent score. Many models were already scored on these validation years.
- The test period stays sealed. No unused period exists for an independent ridge score.
- One horizon, one lag count and one source file.

## Reproduce

```bash
uv run python scripts/run_rolling_origin.py
```

The record is `docs/evidence/rolling-origin-ridge-v1.json`.

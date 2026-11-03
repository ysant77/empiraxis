# Prospective verification, 3 November 2026

Five T+6 h PM2.5 predictions were issued from published NEA data, then scored against values that NEA published after the predictions. This is a record of five values. It is not evidence of forecast skill, and the ledger is not a forecast service.

## Setup

- **Activation:** the owner signed the ledger at 2026-11-03 02:45:10 UTC. It expires at 2026-11-04 08:45:10 UTC. Limit: 20 predictions.
- **Method:** `persistence-latest-published`. Each prediction is the last published hourly value for its region. Method SHA-256 `3a1075d8dbb8…`.
- **Input:** NEA hour 10:00 SGT (02:00 UTC), published 10:30:36 SGT. Response SHA-256 `a4c38f37e886…`.
- **Issued:** 2026-11-03 02:45:14 UTC, 5 h 15 min before the target hour.
- **Target:** hour 16:00 SGT (08:00 UTC), 6 h after the input hour.
- **Check:** `scripts/verify_ledger.py` at commit `c537de0`, the head of #108, which is now on main. It ran at 08:40:49 UTC. It captured the published day into the append-only log, then appended one verification per prediction. It changed no prediction.
- **Availability rule (#108):** a value counts only if NEA published it after its hour, and the check retrieved it before the check time.

## Results

All values are in µg/m³. Times are UTC.

| Prediction | Region | Predicted | Observed | Published | Retrieved | Absolute error | State |
|---|---|---|---|---|---|---|---|
| `20261103T08Z-central-h6` | central | 31 | 28 | 08:30:37 | 08:40:49 | 3 | scored |
| `20261103T08Z-east-h6` | east | 20 | 15 | 08:30:37 | 08:40:49 | 5 | scored |
| `20261103T08Z-north-h6` | north | 32 | 26 | 08:30:37 | 08:40:49 | 6 | scored |
| `20261103T08Z-south-h6` | south | 28 | 13 | 08:30:37 | 08:40:49 | 15 | scored |
| `20261103T08Z-west-h6` | west | 42 | 35 | 08:30:37 | 08:40:49 | 7 | scored |

- **Counts:** 5 scored, 0 pending, 0 observation missing, 0 digest mismatch.
- **MAE over the scored predictions only:** 7.2 µg/m³, n = 5.
- **Direction:** every prediction was higher than the observed value. PM2.5 fell between 10:00 and 16:00 SGT in all five regions.
- **Corrections:** NEA published no correction for these values at the check time. A later correction would be appended as a new row and would not change this record.

## Digests

The record digest covers the prediction record only. The source digest is the SHA-256 of the NEA HTTP response body. The log keeps the digest, not the body.

| Prediction | Record SHA-256 |
|---|---|
| central | `606c970de57f83efda129f77410bd51aeeb28a9f7d2735930d2f7a83978ad6e3` |
| east | `cb4c6d321fa066689a41839f5ddebc8b144cbba06ff25ae8206b1a338c2d2b8c` |
| north | `43b35db4bdc871a86ffa37b2cde0b4a4658400503249910e2e1f2293eaf0ac1c` |
| south | `7d5a66f002b5d086c943becbe5d67752e480f7dfc31c9592dca85cb54db1bcb6` |
| west | `8760b12950a3fcd9e1e67b1dac4811d66b332462f1452834df934bba40dd83cc` |

- **Observed source, all five:** `e65be4bda9cd8e4ad72c39c64b8118b8f171f54453cdc914c950f965c57953e7`, one response for hour 16:00 SGT.
- **Ledger files at the check:**
  - `predictions.jsonl`: `95c11c45ea4cbe96307e375025be2c46d46b9ec94e785c7c512a12c8e800c3b2`
  - `verifications.jsonl`: `841d17dea29339cc78bc61792c7666d1861633b4c58ed9df5028db5bcbe1c543`

The ledger and the capture log are outside the repository, because they are append-only operator records.

## Limits

- **Five values from one hour:** the five regions share one weather situation, so they are not five independent tests.
- **No comparison:** the record has no second method to compare with.
- **Skill:** the record cannot show forecast skill, or the absence of it. A useful test needs many issue times over several weeks.
- **Publication:** NEA does not label these values as final. They can be revised later.

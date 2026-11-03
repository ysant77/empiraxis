# Prospective prediction ledger (EXPERIMENTAL)

Status: implemented and tested. The owner activated it on 2026-11-03 for 20 predictions within 30 hours. Five predictions were issued at 02:00 UTC for 08:00 UTC.

The ledger issues research predictions before the observation exists, then scores them when NEA publishes the value. It is separate from the public replay app and from every historical evaluation. It is not a forecast service, a health warning or evidence of haze-forecast skill.

## Rules in the code (`earthlab.forecast.ledger`)

- **Off by default.** Issuing needs `activation.json` in the ledger folder, signed with the operator key, and the key in the environment. An unsigned, expired or wrongly signed activation keeps the ledger off. The activation also sets a prediction limit.
- **Method:** persistence. The prediction is the newest regional PM2.5 value that NEA had published before the issue time. A value not yet published is not used.
- **Target:** the issue hour plus 6 h, per region, in µg/m³. There is one prediction for each target.
- **Each prediction records:**
  - the issue time;
  - the input value's observation time, publication time and raw-response digest;
  - the method digest;
  - its own record digest.
- **Predictions are append-only.** Verification never changes them.
- **Issue time:** the issue time must be the system clock, within 2 minutes. Backdated and future-dated issues are refused.
- **Inputs:** each must have been published and retrieved before the issue time.
- **Batch quota:** a batch that would pass the activation's limit is refused whole.
- **Digest check:** before scoring, each prediction's digest is recomputed. A changed record is recorded as `digest_mismatch`, not scored.
- **Pending and missing:** an absent observation is `pending`, which is never written, until 24 h after the target. Only then is it recorded as missing. Repeated verification adds nothing new.
- **Day capture:** the day capture follows the source's pagination token, up to 30 pages.
- **Scoring:** verification uses the first published value for the same region and hour, and records its digest and the absolute error. A later correction is counted, not used. 
- `summary()` reports the number of predictions, scored predictions and missing observations.

## To activate (owner only)

Choose the limit and the expiry. Sign the activation in your own shell, with the operator key loaded. Then capture NEA data and issue. A few predictions on a clean day show nothing about haze events.

## To score

`uv run python scripts/verify_ledger.py <ledger folder> <capture log>` needs no key. It captures each target day's published PM2.5 by date, so the time of the check does not matter. Then it appends one verification per due prediction.

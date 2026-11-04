# M5-C onset audit (post hoc, exploratory)

Status: post hoc and exploratory. The M5-C protocol (`m5-protocol-c-1`), the primary result
(`docs/m5/results/m5_c_v1.json`) and the headline do not change.

## Question

Does M5-C predict the start of independent haze episodes, or does its skill come mainly from
episodes that are already in progress at the issue time?

## Definitions (written before the computation)

- **Issues.** The 2019 issues that M5-C scored. The coverage rule of Amendment C4 applies
  (`event_c.event_labels`).
- **Event.** The frozen M5-C label: any region-hour above 55 ug/m3 in (T+12 h, T+24 h].
- **State at issue T.** Only the 24 lag hours that M5-C sees (T-2 h back to T-25 h) are used.
  - *Ongoing*: at least one observed region-hour above 55 ug/m3 in those hours.
  - *Onset-eligible*: no observed region-hour above 55 ug/m3, and at least 20 of the 24 hours
    have an observation in at least one region.
  - *Unclear*: no observed exceedance, with fewer than 20 observed hours.
- **Onset event.** An onset-eligible issue with label 1. **Continuation event.** An ongoing issue
  with label 1.
- **Exceedance episode.** A run of hours with any region above 55 ug/m3. Runs less than 24 h
  apart merge into one episode.
- **Independent onsets.** The number of distinct episodes whose first exceedance hour is in the
  event window of at least one onset-eligible issue.
- **Threshold, declared before the computation.** A skill estimate on onsets alone needs at
  least 10 independent onset episodes. With fewer, the result is "insufficient independent
  onsets".

M5-C did not save its predictions. This audit fits no model and trains no model. It uses
observations only: counts and base rates.

## Result

Script: `scripts/m5_c_onset_audit.py`. Output: `docs/m5/onset-audit/m5_c_onset_audit.json` (outside the frozen `docs/m5/results/`).
NEA file SHA-256: `2fb76e1c4e4208e92f49670602e303c86e21eaa3704651633323e50f51015de4`.

| State at issue | Issues | Events | Event rate |
|---|---|---|---|
| Ongoing | 418 | 279 | 0.667 |
| Onset-eligible | 968 | 70 | 0.072 |
| Unclear | 0 | 0 | - |
| All scored | 1,386 | 349 | 0.252 |

- 279 of the 349 events (80%) are continuation events. They follow an exceedance that the model
  already sees in its lag window.
- The 2019 season has 5 exceedance episodes under the 24 h merge rule: 9 to 10 Sep (41 h),
  12 to 19 Sep (164 h), 20 to 24 Sep (96 h), 26 Sep (1 h) and 28 Sep (1 h).
- 4 of these episodes start inside the event window of an onset-eligible issue.
- **Verdict: insufficient independent onsets** (4, below the declared 10).

## What this means

- Most M5-C events are continuations. A model that uses PM2.5 lags can score well on them.
  This agrees with the M5 report: the skill comes from the PM2.5 lags.
- Four independent onsets are too few to estimate skill for onset prediction. This audit does
  not show that M5-C predicts onsets. It also does not show that M5-C cannot predict them.
- The predictions were not saved, so the audit does not split the Brier skill by state. A split
  needs the saved predictions of the frozen run. A new protocol needs more haze seasons with
  independent onsets.

## Limits

- Post hoc. The definitions were written after the primary result was known.
- The 20-hour observation rule and the 24 h merge rule are choices of this audit. No
  sensitivity test was run on them.
- No causal attribution. No operational forecast.

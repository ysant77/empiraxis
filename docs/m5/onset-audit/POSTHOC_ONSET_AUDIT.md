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
- The 20-hour observation rule and the 24 h merge rule are choices of this audit. The review
  revision below tests them.
- No causal attribution. No operational forecast.

## Review revision (2026-11-04, audit 2)

The definitions above are unchanged. The review added checks. The script is now audit 2
(`m5-c-onset-audit-2`). The primary numbers equal audit 1: same state counts, same 4 onsets.
The output adds the NEA file digest, a sensitivity grid and the week structure.
Tests: `tests/test_m5_onset_audit.py` (merge boundary, lag window edge, coverage rule, onset
versus continuation, and a fresh run that must equal the committed file).

### What "independent onset" means

It means two exceedances are separated by fewer than 24 hours of merge distance: fewer than
24 hours without an exceedance lie between them. It does not mean meteorologically independent.
All 2019 episodes lie in one September haze period. Whether they share a fire regime was not tested.

### Why M5 says one episode and this audit says five

M5 counts days with an event label. It starts a new episode only after a gap of more than one day.
The event window reaches back to T+13 h, so label days run together over gaps of 35 to 50 hours.
This audit counts hourly exceedances. Both counts are correct for their definitions. The M5 report
keeps "one episode" for the scored labels. The exceedance episodes are:

| Start | Span (h) | Exceedance hours | Counted as onset |
|---|---|---|---|
| 9 Sep | 41 | 16 | yes |
| 12 Sep | 164 | 101 | yes |
| 20 Sep | 96 | 65 | no |
| 26 Sep | 1 | 1 | yes |
| 28 Sep | 1 | 1 | yes |

The 20 Sep episode begins 35 hours after the previous one ends. That exceedance is inside the 24
lag hours of every issue that could predict it, so those issues are "ongoing". The audit treats
it as a continuation, not an onset. Two of the four counted onsets are single-hour exceedances.

### Sensitivity (not a selection)

Independent onsets under 24 settings (merge 12, 24, 48, 72 h; coverage rule 16, 20, 24 hours;
minimum exceedance hours 1 and 6). The range is 1 to 5. No setting reaches the declared 10.

| Merge gap (h) | Min 1 exceedance hour | Min 6 exceedance hours |
|---|---|---|
| 12 | 5 | 2 |
| 24 (primary) | 4 | 2 |
| 48 | 2 | 1 |
| 72 | 1 | 1 |

The coverage rule has no effect in 2019: all 968 non-ongoing issues have at least 24 observed
lag hours. The verdict "insufficient independent onsets" holds under every tested setting.

### Why a week bootstrap does not estimate generalisation across episodes

- The 1,386 scored issues cover 9 ISO weeks. Events fall in 4 of them: week 36 has 21, week 37 has
  132, week 38 has 145 and week 39 has 51. All 349 events belong to one connected label period.
- The M5-C bootstrap resamples these weeks. It shows how the score changes when the weeks of one
  episode get different weights. It holds the episode, the season, the station network and the fire
  regime fixed.
- Consecutive hourly issues share 11 of their 12 target hours, so hours are not independent. Weeks
  fix that for hours. They do not turn the weeks of one episode into draws from many episodes.
- The interval therefore covers week-to-week variation inside one episode. It does not cover
  episode-to-episode variation in size, duration or source, variation between years, or the choice
  of 2019. The season 2019 was also the Stage T test season, so it was reused.
- An onset-only bootstrap would resample at most 4 units (1 to 5 across settings). That is too few.

### Saved predictions and re-creation

- **Saved predictions: NO.** `scripts/m5_run_c.py` writes aggregates only. No file with per-issue
  probabilities exists in the repository or in the local data folders.
- **Could they be re-created?** Yes, in principle. M5-C has fixed folds and seed 7. A full rerun
  on 2026-11-04 reproduced every number of the primary record (0 differences). A dump of the C2
  and C3 probabilities would therefore be exact. A predictions-only path would skip the bootstrap.
- **Not done here.** The brief forbids a new fit. Even with predictions, 4 onsets cannot support a
  skill estimate for onset prediction. A state-split Brier table would be descriptive only. It
  needs its own ID and the owner's approval first.

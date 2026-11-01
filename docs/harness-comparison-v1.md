# Harness comparison v1, measured results

Status: research results on validation data. The rounds ran at commit `4f5fe92e` with 22 saved
runs (two rounds, fixed, single and team arms). Every run replays with no mismatch. Generated
by `earthlab harness-compare` on saved records, with the billed-cost fix applied to the report.

Reader notes:

- S1 and S2 share one dataset. These are not independent domain demonstrations.
- Two repeats per cell show no statistical difference. They show failure modes and costs.
- Where the simpler workflow reached the same outcome, the simpler workflow is preferable.
- The team arm failed 3 of 8 runs because a specialist did the work and then did not call
  `submit_note`. Results stand as recorded. A later benchmark tests the fix.
- The team arm ended `burned-area-segmentation` by PM abstention, so no resource request was
  written in that arm. The fixed arm wrote one. The single arm did not run that scenario.
- A model changed the plan from the preset in the counts shown, and not in every scenario.

## burned-area-method

### Scientific result

| Measure | fixed | single | team |
|---|---|---|---|
| runs | 2 | 2 | 2 |
| reached decision gate | 2 | 2 | 0 |
| ended in refusal or abstention | 0 | 0 | 0 |
| failed | 0 | 0 | 2 |
| acceptance passed | 2 | 2 | 0 |
| outcomes | {'adopt_limited raster_deterministic': 2} | {'adopt_limited raster_deterministic': 2} | {'failed': 2} |
| strategies | {'deterministic': 2} | {'deterministic': 2} | {'deterministic': 2} |
| agrees with code rule | 2 | 2 | 0 |

### Engineering cost

| Measure | fixed | single | team |
|---|---|---|---|
| wall seconds | 0.2 (0.2 to 0.2) | 576.45 (525 to 627.9) | 587.4 (543.8 to 631) |
| training seconds | 0 (0 to 0) | 0 (0 to 0) | 0 (0 to 0) |
| peak training rss mb | 0 (0 to 0) | 0 (0 to 0) | 0 (0 to 0) |
| energy | not measured | not measured | not measured |

### Agent cost

| Measure | fixed | single | team |
|---|---|---|---|
| model calls | 0 (0 to 0) | 4 (4 to 4) | 5.5 (5 to 6) |
| prompt tokens | 0 (0 to 0) | 3466.5 (3466 to 3467) | 4337.5 (3951 to 4724) |
| completion tokens | 0 (0 to 0) | 2500.5 (2376 to 2625) | 2456.5 (2290 to 2623) |
| inference seconds | 0 (0 to 0) | 576.1 (524.7 to 627.5) | 587.1 (543.4 to 630.8) |
| plan changed by model | 0 | 0 | 0 |
| retries | 0.0 | 0.0 | 0.0 |
| provider faults | 0.0 | 0.0 | 0.0 |
| rejected tool calls | 0.0 | 0.0 | 0.0 |
| human interventions | 0.0 | 0.0 | 0.0 |
| billed usd | not measured | not measured | not measured |

## burned-area-segmentation

### Scientific result

| Measure | fixed | team |
|---|---|---|
| runs | 2 | 2 |
| reached decision gate | 2 | 0 |
| ended in refusal or abstention | 0 | 2 |
| failed | 0 | 0 |
| acceptance passed | 2 | 0 |
| outcomes | {'request_resource': 2} | {'abstained': 2} |
| strategies | {'abstain_or_request': 2} | {'None': 2} |
| agrees with code rule | 2 | 0 |

### Engineering cost

| Measure | fixed | team |
|---|---|---|
| wall seconds | 0.1 (0.1 to 0.1) | 133.9 (131.8 to 136) |
| training seconds | 0 (0 to 0) | 0 (0 to 0) |
| peak training rss mb | 0 (0 to 0) | 0 (0 to 0) |
| energy | not measured | not measured |

### Agent cost

| Measure | fixed | team |
|---|---|---|
| model calls | 0 (0 to 0) | 1 (1 to 1) |
| prompt tokens | 0 (0 to 0) | 604 (604 to 604) |
| completion tokens | 0 (0 to 0) | 586 (578 to 594) |
| inference seconds | 0 (0 to 0) | 133.9 (131.8 to 136) |
| plan changed by model | 0 | 0 |
| retries | 0.0 | 0.0 |
| provider faults | 0.0 | 0.0 |
| rejected tool calls | 0.0 | 0.0 |
| human interventions | 0.0 | 0.0 |
| billed usd | not measured | not measured |

## pm25-exceedance

### Scientific result

| Measure | fixed | single | team |
|---|---|---|---|
| runs | 2 | 2 | 2 |
| reached decision gate | 2 | 2 | 1 |
| ended in refusal or abstention | 0 | 0 | 0 |
| failed | 0 | 0 | 1 |
| acceptance passed | 2 | 2 | 1 |
| outcomes | {'retain_baseline persistence_alarm': 2} | {'retain_baseline persistence_alarm': 2} | {'failed': 1, 'retain_baseline persistence_alarm': 1} |
| strategies | {'statistical': 2} | {'statistical': 2} | {'statistical': 2} |
| agrees with code rule | 2 | 2 | 1 |

### Engineering cost

| Measure | fixed | single | team |
|---|---|---|---|
| wall seconds | 1.45 (1.1 to 1.8) | 1010.9 (981.1 to 1040.7) | 1917.55 (1218.1 to 2617) |
| training seconds | 0 (0 to 0) | 0 (0 to 0) | 0 (0 to 0) |
| peak training rss mb | 0 (0 to 0) | 0 (0 to 0) | 0 (0 to 0) |
| energy | not measured | not measured | not measured |

### Agent cost

| Measure | fixed | single | team |
|---|---|---|---|
| model calls | 0 (0 to 0) | 5.5 (5 to 6) | 12.5 (7 to 18) |
| prompt tokens | 0 (0 to 0) | 6224.5 (5816 to 6633) | 12356.5 (5586 to 19127) |
| completion tokens | 0 (0 to 0) | 3777.5 (3722 to 3833) | 7992.5 (4909 to 11076) |
| inference seconds | 0 (0 to 0) | 1008.9 (978.5 to 1039.3) | 1915.45 (1216.8 to 2614.1) |
| plan changed by model | 0 | 2 | 0 |
| retries | 0.0 | 0.0 | 0.0 |
| provider faults | 0.0 | 0.0 | 0.0 |
| rejected tool calls | 0.0 | 0.0 | 0.0 |
| human interventions | 0.0 | 0.0 | 0.0 |
| billed usd | not measured | not measured | not measured |

## pm25-regression

### Scientific result

| Measure | fixed | single | team |
|---|---|---|---|
| runs | 2 | 2 | 2 |
| reached decision gate | 2 | 2 | 2 |
| ended in refusal or abstention | 0 | 0 | 0 |
| failed | 0 | 0 | 0 |
| acceptance passed | 2 | 2 | 2 |
| outcomes | {'adopt_limited candidate-1': 2} | {'retain_baseline B0_persistence': 2} | {'retain_baseline B4_lagged_ridge': 1, 'retain_baseline B0_persistence': 1} |
| strategies | {'small_neural': 2} | {'statistical': 2} | {'statistical': 2} |
| agrees with code rule | 2 | 2 | 2 |

### Engineering cost

| Measure | fixed | single | team |
|---|---|---|---|
| wall seconds | 21.25 (20.9 to 21.6) | 653.2 (636.7 to 669.7) | 2078.45 (1875 to 2281.9) |
| training seconds | 19.3 (18.9 to 19.7) | 0 (0 to 0) | 0 (0 to 0) |
| peak training rss mb | 341.8 (341.2 to 342.4) | 0 (0 to 0) | 0 (0 to 0) |
| energy | not measured | not measured | not measured |

### Agent cost

| Measure | fixed | single | team |
|---|---|---|---|
| model calls | 0 (0 to 0) | 4 (4 to 4) | 10 (10 to 10) |
| prompt tokens | 0 (0 to 0) | 5139.5 (5127 to 5152) | 10316 (10033 to 10599) |
| completion tokens | 0 (0 to 0) | 2531 (2465 to 2597) | 8009.5 (7672 to 8347) |
| inference seconds | 0 (0 to 0) | 651.35 (634.9 to 667.8) | 2076.5 (1873.1 to 2279.9) |
| plan changed by model | 0 | 2 | 2 |
| retries | 0.0 | 0.0 | 0.0 |
| provider faults | 0.0 | 0.0 | 0.0 |
| rejected tool calls | 0.0 | 0.0 | 0.0 |
| human interventions | 0.0 | 0.0 | 0.0 |
| billed usd | not measured | not measured | not measured |


# Benchmark matrix results, Phase 2 (2026-11-01 to 2026-11-02)

Protocol: `docs/benchmark-matrix-protocol.md`. Raw runs, manifests and logs are in
`~/Documents/meta-ai/earthlab-matrix-runs/decisions-v1/` (outside the repo).
The sample is very small: 1 to 3 runs per cell. This report gives counts. It gives no p-values.
Timings are single runs on one shared Mac. They are not clean (see section 8).

## 1. Answer

1. **Best system:** no model arm is best. The deterministic pipeline (arm F) had verified goal
   completion (VGC, protocol section 4.1) in 4 of 4 runs and took 0.1 to 23 s. No model arm had a
   higher share than F. The deterministic pipeline is enough for the tested scenarios.
2. **Prompt fix:** the round-1 defect was real. Baseline team arm `T-M-base` failed 3 of 3 confirm
   runs ("used its turns without submit_note"). Variant `note-close-v1` had VGC in 3 of 3, in the
   same session. Three pairs are consistent with a fix. They do not give an effect size.
3. **The team is slow.** `T-M-win` took 1159 to 2159 s per run. F took 0.2 and 3.1 s on the same
   two tickets, with the same outcomes. The baseline times are not a fair cost control: those runs
   stopped early. See section 4.
4. **Small models** passed preflight except Llama 3.1 8B. They ran only in the unranked fallback,
   with VGC in 0 of 6 runs.
5. **Limits on these results:** paired coverage is incomplete. Only two tickets ran in F, `S-M` and
   the team, and `confirm` covers two tickets. Team arms with mixed models did not run. Wall times
   are contaminated by swap pressure and, early on, a peer test run (section 8).

## 2. What ran

| Stage | Runs | Not clean | Pin |
|---|---|---|---|
| preflight (3 small models, Muse down) | 3 models | 1 failed (Llama 3.1 8B) | 686d859 config, then 2344199 |
| screen-muse | 14 | 0 | 686d859 |
| tune-prompt (DSPy, Qwen3 4B) | 1 | 1 attempt stopped, then ran | 43123aa |
| screen-mixed, screen-tuned | 0 | not run | see section 5 |
| fallback-single | 6 | 0 | 43123aa |
| confirm | 6 | 3 (all `T-M-base`) | 43123aa |

Order was serial, one model server at a time. Muse was stopped once (after `screen-muse`) and
restarted once (before `confirm`). See section 8.

## 3. screen-muse (Muse only, 14 runs)

| Scenario | F | S-M | T-M-v1 | T-M-v2 |
|---|---|---|---|---|
| burned-area-method | VGC | VGC | VGC | VGC |
| burned-area-segmentation | VGC (request_resource) | **miss** (adopt_limited) | safe stop | safe stop |
| pm25-exceedance | VGC | VGC | VGC | VGC |
| pm25-regression | VGC (adopt_limited) | VGC (retain_baseline) | not run | not run |

- `T-M-v1` and `T-M-v2` both passed 2 of 3 scenarios. Both abstained on segmentation after one model call.
  Tie. The protocol names `note-close-v1` the winner (fewer calls and tokens).
- The reminder in `note-close-reminder-v1` added 4 to 5 calls and about 3,000 to 4,000 prompt tokens per run and no extra passes.
- Wall time of the runs that reached the gate: S-M 576 to 1195 s, T-M-v1 1565 to 1582 s, T-M-v2 1682 to 1751 s, F 0.1 to 23 s. The two safe stops took 181 and 235 s.
- On segmentation, `S-M` changed the plan to the deterministic method and recommended `adopt_limited`. Its acceptance checks passed and its outcome matched its own `code_outcome`. But section 4.1 rule 5 requires `request_resource` for this decision, so the run is a miss.
- On regression, `S-M` and F chose different plans, so their code outcomes differ. VGC compares each run with its own plan. It does not say which plan is right. F's `adopt_limited` selects a trained candidate with above-55 MAE 28.77 against 26.32 for persistence. The code rule allows this as limited use, so R2 does not apply. That rule is exploratory.

## 4. confirm (winner `note-close-v1` against `T-M-base`, 6 runs)

| Scenario | T-M-base (baseline prompt) | T-M-win (`note-close-v1`) |
|---|---|---|
| burned-area-method, 2 pairs | failed, failed (746 s, 793 s) | VGC, VGC (1159 s, 1298 s) |
| pm25-exceedance, 1 pair | failed (1031 s) | VGC (2159 s) |

Failure text, baseline: `data_specialist used its turns without submit_note` (2 runs) and
`ml_engineer used its turns without submit_note` (1 run). Exit code 2 for each. This is the round-1 failure.
With the fix, `T-M-win` made 10 to 17 model calls and 8,263 to 18,478 prompt tokens per run.
The three pairs are consistent with the prompt fix. They do not support "a team beats F".

Prompt digests of `T-M-win` equal those of `T-M-v1`, across pins 686d859 and 43123aa. So the prompt
text did not change between screen and confirm. Those two commits changed provider and role
configuration, tests and the optimizer lock.

Baseline wall time is not a cost control for the fix. Each baseline run stopped at a specialist, so
the later roles never ran. In the burned-area pairs, `data_specialist` used 3 calls and 349 to
491 s at baseline, and 2 calls and 143 to 179 s with the fix.

Median of the 2 burned-area pairs, and the 1 exceedance pair, per role:

| Role | Calls, base | Calls, fix | Prompt + completion tokens, base | Prompt + completion tokens, fix |
|---|---|---|---|---|
| product_manager, burned area | 1 | 3 | 1,416 | 4,688 |
| geospatial_engineer, burned area | 1 | 3 | 1,602 | 4,488 |
| data_specialist, burned area | 3 | 2 | 4,330 | 2,472 |
| ml_engineer, burned area | not reached | 2 | not reached | 2,451 |
| product_manager, exceedance | 1 | 3 | 1,167 | 5,871 |
| geospatial_engineer, exceedance | 1 | 6 | 1,856 | 11,186 |
| data_specialist, exceedance | 2 | 4 | 2,577 | 5,083 |
| ml_engineer, exceedance | 3 (stopped) | 4 | 4,581 | 5,384 |

## 4a. VGC by arm, from the raw runs

The main session recomputed these five rules from each `result.json` and ran
`earthlab harness-replay` on all 26 saved runs.

| Arm | Workflow | VGC | Safe stop | Other misses | Median wall s (reached gate) | Ranked |
|---|---|---|---|---|---|---|
| F | deterministic | 4 of 4 | 0 | 0 | 1.7 | yes |
| S-M | single agent | 3 of 4 | 0 | 1 | 683 | yes |
| T-M-v1 (screen) | team | 2 of 3 | 1 | 0 | 1574 | yes |
| T-M-v2 (screen) | team | 2 of 3 | 1 | 0 | 1717 | yes |
| T-M-win (confirm, same prompts as T-M-v1) | team | 3 of 3 | 0 | 0 | 1298 | yes |
| T-M-base (confirm) | team | 0 of 3 | 0 | 3 failed | none | yes |
| S-q4 (fallback) | single agent | 0 of 3 | 0 | 3 | 28.9 | no |
| S-l3 (fallback) | single agent | 0 of 3 | 0 | 3 | 6.5 | no |

The arms ran different tickets, so the shares are not a like-for-like score. On the two tickets
that F, S-M and the team all ran, every arm that reached the gate gave the same outcome. The
order of median wall time was F, single agent, team.

## 5. Mixed arms, tuned arm, DSPy

- **Memory probe, `screen-mixed`:** not run as a joint test. The owner ruled that small models
  do not run beside Muse. The sum of the measured figures fails the 28.0 GB limit: Muse alone
  had system wired memory of about 21.0 GB, and Qwen3 4B alone needed 8.3 GB (29.3 GB).
  Swap was already at 17.8 of 18.4 GB with Muse alone. So the protocol fallback ran. This is an
  inferred result, not a measured joint peak.
- **`fallback-single` (arms S-q4, S-l3, unranked, Lead gate waived):** 6 runs, 0 crashes, 0 VGC.
  Acceptance checks do not measure the recommendation, so they passed in 5 runs. But each
  recommendation that reached the gate was `abstain` and differed from `code_outcome`. Llama 3.2 3B
  also stopped by itself on pm25-exceedance. Wall time 3.0 to 30 s. The small models did not do the
  work. This is no evidence that a small model can lead.
- **R1 disqualifier, S-l3:** in 2 runs Llama 3.2 3B recommended `abstain` where `code_outcome` was
  `request_resource`. Section 4.2 orders `abstain` as more permissive. S-l3 is unranked, so the
  ranking does not change. S-q4 recommended `abstain` where code allowed more, which is not R1.
- **DSPy (MIPROv2, Qwen3 4B, 12 synthetic tickets):** first attempt stopped at the search step
  because `optuna` was missing from the lock. Fixed in 43123aa (hashed lock, `optuna==4.5.0`). The
  second run finished in about 15 minutes. Candidate text, in full: "You are the {role}. Call {tool},
  then submit_note." Held-out score (4 tickets): default prompt 1.0, `note-close-v1` 0.0, candidate 1.0.
  The default already scored 1.0, so the tuning shows no gain. **Negative result.**
- **`T-sp4-tuned` skipped.** No person reviewed the candidate. The text drops the safety wording
  of the reviewed variants. The protocol rule says to run the arm only if that wording is unchanged.
  The arm stays refused.

## 6. Preflight of small models (Muse down, port 8081)

| Model | JSON schema | Tool loop | Peak wired memory | Enabled |
|---|---|---|---|---|
| Llama 3.2 3B Instruct Q4_K_M | pass | pass (prepare_data, submit_note) | 7.25 GB | yes, specialist roles |
| Qwen3 4B Instruct 2507 Q4_K_M | pass | pass | 8.29 GB | yes, specialist roles |
| Llama 3.1 8B Instruct Q4_K_M | pass | **fail** | 10.15 GB | no |

Llama 3.1 8B wrote a stray `;` before its second tool call. The server rejected it with HTTP 500.
Temperature 0, so a retry would repeat it. **Negative result.** The reserve arm `T-sp8` stays blocked.
The preflight tested specialist roles only. The PM seat (arm `T-pm3`) was not tested and not run.
A first preflight script bug (health check returned early) gave one spurious 503 for Llama 3.1; the
rerun with a fixed script gave the HTTP 500 result above.

## 7. Failures, all of them

1. `T-M-base`: 3 of 3 confirm runs failed (section 4). Expected, it is the control.
2. Llama 3.1 8B preflight failure (section 6).
3. `T-M-v1`, `T-M-v2`: 2 abstentions on segmentation (section 3). Abstention here is a safe stop, not a pass.
4. Llama 3.2 3B abstained on pm25-exceedance (section 5).
5. DSPy first attempt: missing `optuna` in the lock. Fixed.
6. Six tests assumed the old binding state (only Muse enabled, Llama blocked for several reasons). Updated to the new state in 2344199.
7. `tests/test_board_surfaces.py::test_three_sessions_show_one_run_identity` failed with "Address already in use"
   while another session held a port. It passed when run alone on the free machine, so it is a port clash and not related to this work.
8. Compare report showed the unranked fallback arms as ranked (the `ranked` flag was not read from the manifest). Fixed in c8869ed, with a test.
9. My own request to stop the shared Muse server was denied by the permission rules. The main session stopped and restarted Muse with the owner's approval.
10. `S-M` on burned-area-segmentation is a VGC miss (section 3).
11. `S-l3` has an R1 disqualifier in 2 runs (section 5).
12. The first version of this report used acceptance checks in place of VGC, and it gave a wrong F time. The main session corrected both after a check against the raw runs.

## 8. Conditions that affect timing

- Swap, Muse loaded: 16.4 to 17.9 GB used of 18.4 GB, about 0.06 GB free pages. During `confirm`: 14.2 of 15.4 GB.
  With Muse down: 8.1 of 9.2 GB. Swap pressure slows Muse. Do not treat wall times as a hardware benchmark.
- The first preflight (before Phase 2 start) and the first early `screen-muse` timings are not clean: a peer pytest run was still active.
- Muse events (`logs/server-events.log`): a stop attempt by this session was denied; Muse ran through `screen-muse`;
  the main session stopped Muse for the small-model blocks; it restarted Muse at 02:27 SGT with the same command and flags before `confirm`.
- Energy was not measured. Cost was not billed (local models only).

## 9. What this does not show

- It does not show that a model team can do better than F. It shows a team needs the prompt fix to finish at all.
- It does not show Llama 3.2 3B or Qwen3 4B as specialists inside a team. Those arms (`T-sp4`, `T-pm3`) did not run.
- Counts are 1 to 3 per cell. No interval or test was computed.
- Disqualifier checks: all 26 replays passed and all hash chains are intact (S3). `no_feature_file_reaches_test` is true wherever it is recorded (S2). Each role used the provider that its arm names (S4). R1 appears only in S-l3. R2 does not apply to any run.
- S1 was a keyword scan of recommendations and model text. The matches were disclaimers such as "no cause, forecast or advice" and ordinary words such as "because". A person did not read all model text.
- It does not make `note-close-v1` a repo default. On these counts it meets the promotion conditions: no disqualifier, all specialists closed, and VGC not below the control in the 3 pairs. Promotion needs its own pull request. Three pairs show consistency with a fix. They do not show an effect size.

## 10. Decision for the owner

- Ship the deterministic pipeline as the default for the tested scenarios. Keep the model team as an optional, slower mode with prompt `note-close-v1`.
- Decide whether to review the DSPy candidate. The measured gain is zero, so the advice is not to.
- Decide whether to spend time on `T-sp4` and `T-pm3`. They need a swap-free machine or a smaller Muse setup.

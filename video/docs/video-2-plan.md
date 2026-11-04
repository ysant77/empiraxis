# Video 2.0 plan (parked)

Status: plan only. **Do not render until the owner approves this plan.** Fill every value from
the files named here, after the runs are complete. Do not use a value from this document; it
has none.

## 1. Story

V1.1 showed one model in four roles, a deterministic code rule and a human gate. V2.0 shows
the next step: a council of different checkpoints that reviews real multisource evidence and
hands an honest decision to a human.

1. **Question.** Can wind, rainfall and regional fires help predict Singapore haze? (V1.1 scene.)
2. **2015 result.** Adding weather and fire inputs made 2015 predictions worse. (V1.1 scene.)
3. **M5: what the data can support.** Which sources are usable at issue time; which failed
   quality checks; what the held-out 2019 season shows.
4. **M5 to M4: the evidence package.** M5 writes one hashed package. The council reads only
   that package.
5. **M4.1: the council.** Each role with its checkpoint. Specialist findings with evidence ids.
   The Lead's accept, reject or clarify. The critic's findings and the Lead's response. The
   code rule. The escalations to the human.
6. **Comparison.** Council arms against the code rule only (F) and a single Muse Lead (S), on
   the same packages. Benefits only where they are visible against F or S.
7. **Human gate.** Pending. The director decides.
8. **Close and credits.**

## 2. Sources, by scene

The M4.1 and M5 files are on their feature branches until they merge. Use the merged commit.

| Scene | Values to show | Source file |
|---|---|---|
| 3 | Source availability classes and latencies | M5 `docs/m5/evidence/scientific_evidence_package_v1.json` |
| 3 | SMAP and HLS quality results | M5 `docs/m5/qa/smap_qa.json`, `docs/m5/qa/hls_qa.json` |
| 3 | 2019 held-out MAE by rung | M5 `docs/m5/results/m5_ladder_stage_t.json` |
| 3 | M5-C skill and its checks | M5 `docs/m5/results/m5_c_v1.json`, report section 2c |
| 4 | Package hash and the adapter's availability rule | `examples/assess/packages/e-m5-handoff.json`, `docs/m41/m41-protocol.md` Amendment 2 |
| 5 | Role, checkpoint, findings, responses, escalations | `examples/assess/replay/<HC run on package e>/trace.jsonl` and `result.json` |
| 6 | Decisions, faults raised, unsupported content, cost per arm | `docs/m41/` benchmark report and its evidence JSON |
| 6 | Critic test (24 cases) | `docs/m41/` benchmark report, critic section |
| 7 | Human gate state | the same replay `result.json` |

## 3. Labels that must appear

- M5-C: "EXPLORATORY · ONE SEASON · ONE EPISODE · NO OPERATIONAL CLAIM". The skill comes from
  the PM2.5 lags; the fire increment is not supported. Post-hoc bands are labelled post hoc.
- Council: "RECORDED REPLAY · NOT LIVE". Each card names its checkpoint.
- A Muse critic: "SEPARATE REVIEW ROLE · SAME CHECKPOINT AS THE LEAD · NOT AN INDEPENDENT MODEL".
- A role that failed in a run is shown as failed. No other model is shown in its place.
- The M4 Qwen failures and the critic results with zero detections are part of the record.
  Show them if the comparison scene shows the critic.
- Human gate: "HUMAN DECISION PENDING".

## 4. Work items

1. Read the merged M4.1 report and M5 report. Write `fact-check-v2.md` with every on-screen
   value and its file, before any design work.
2. Add the new scenes to `build_data.py`, `index.html`, `app.js` and `tools/vo.json`.
3. Keep the V1.1 scenes 1 and 2 as they are, or shorten them.
4. Target runtime: under 3:00.
5. Render stills, check them against the fact check, then render the film.
6. Run `finish.py`. Write `acceptance-check-v2.md` with runtime, loudness, word match and the
   honesty checks of section 3.
7. Record the SHA-256 of each output in `video/README.md`.

# Final 20-milestone matrix, 3 November 2026

This matrix assesses each of the 20 original milestones again, after the runs of 3 November. A merged PR does not move a status by itself. A status moves only with an executed record.

Status labels:

- **bounded:** shown on real evidence, inside the stated limits.
- **partial:** some of the capability ran, but a stated part did not, or gave no benefit.
- **future:** not built in this repository.

No row reaches the full original scope.

Run identifiers:

| Run | What it is | Record |
|---|---|---|
| `20261103T035551Z-95e7a3` | Muse family run with a signed NEA acquisition. No neural model: the Lead chose statistical. | `docs/muse-family-comparison-run.md` |
| `20261103T061204Z-829fed` | Muse method comparison. Tuned ridge and a TCN, both trained and reloaded. | `docs/muse-method-comparison-run.md`; replay M3 |
| Ledger `earthlab-ledger` | 5 prospective predictions, issued 2026-11-03 02:45 UTC, scored 08:40 UTC | `docs/prospective-verification.md` |
| 2015 ablation v2 | B0 to B3, corrected after review | `docs/haze-2015-ablation-results.md` |
| Prithvi Level A | One pretrained forward pass on one published chip | `docs/prithvi-level-a.md` |

## Matrix

| # | Intended capability | Implemented code | Real executed evidence | Independent verification | Scientific limits | Hackathon status | Post-hackathon work |
|---|---|---|---|---|---|---|---|
| 1 | Reusable engineering organization across projects | None | None | None | n/a | future | Extract a core; run a second domain |
| 2 | Human Director: signed approvals, bounded autonomy | `ResourceDesk` (HMAC approvals), signed ledger activation | Owner signed `nea-pm25-qa-1` (used in run 95e7a3), the Prithvi weights and chips, and the ledger activation | Tests refuse forged, expired, edited and wrong-key approvals | Both team runs end at a pending human decision; no decision is signed yet | bounded | An approve control in the UI, with the key outside the browser |
| 3 | PM: typed requirements and acceptance | `review_scope`, `forward_decision` seats | Muse PM scoped and forwarded in both runs of 3 November | Typed contracts; code refused two over-length PM notes | The PM note in run 829fed leaves out that B4 is also worse than persistence above 55 µg/m³ | bounded | Unseen requests; a check of the note against the report |
| 4 | Engineering Lead: defensible method choices | `choose_strategy`, `choose_method`, `review_results`, `recommend` | Run 829fed: strategy `statistical`, TCN 96 h configuration, finish, `retain_baseline` (B4) | Code gates on every choice; decision matches the evaluator | The Lead wrote a false reason, "TCN trains fast vs GRU". The code's own table gives 50 s per epoch for a TCN and 4 s for a GRU at window 48. | bounded | A fact check of the Lead's reasons against measured costs |
| 5 | Compact specialist team | Data and ML specialist seats | Both runs: specialists called `prepare_data` and `train_models` | Trace and delegation tests | No software or QA seat ran live | bounded | More seats only with a measured benefit |
| 6 | Durable run harness | Lifecycle, hash-chained trace, budgets | Run 829fed: 52 records, 12 model calls, 2,223 s, inside every declared limit | `harness-replay`: 0 mismatches for 95e7a3 and 829fed | One process at a time | bounded | Recovery across processes |
| 7 | Secure real tools | Fixed allowlisted tools; URLs built by code; acquisition limits per chunk (#109) | The signed acquisition built its URLs in code and stayed inside the limits | Tests for over-limit last day, pagination and time; adversarial suite 35 of 35 attacks refused | No general code or shell execution, by design | bounded | n/a |
| 8 | Independent scientific design critique | Code evaluator and decision rule; optional same-model critic | Both runs: the evaluator report and a recorded Lead response (`finish`) | Seeded faults 7 of 7 found by code rules (earlier work) | The same-model critic added no detection and stays off. No run of 3 November had a defect that called for a revision. | partial | An independent critic with measured detection |
| 9 | Provenance and data quality | Input hashes, capture log, comparison with the source file | Signed capture of 3 days: 333 region-hours match, **17 differ** on 2023-11-15 | The receipt records every difference; the source file was not changed | The cause of the 17 differences is unknown | bounded | Ask NEA about revisions; capture more dates |
| 10 | Heterogeneous environmental modeling | 2015 ablation: PM2.5, ERA5 wind and rain, FIRMS | Ablation v2: no feature group gave a gain (B3 vs B2 skill -0.137, interval -0.209 to -0.070) | Leak tests per feature group; frozen protocol with Amendment 1 | Two months; ERA5 is hindsight data; shared box context | bounded | Several haze seasons; a predeclared design |
| 11 | Data suitability, abstention, approved acquisition | Suitability checks; `acquire_step` with signed approval | Run 95e7a3: Muse asked for 3 days; the signed request ran; 14,865 bytes | Receipt, desk record, limit tests | One small acquisition | bounded | Acquisition of other products |
| 12 | Data engineering: train-only transforms | Workbench features and scalers | Run 829fed: features `3b4b0e36cfae`, scalers on train years only | `no_feature_file_reaches_test` acceptance check: true | One tabular source | bounded | n/a |
| 13 | Method selection | Strategy checks and decision rule | Six cases, including run 829fed: a neural model trained and lost, so the baseline stays | Scenario replays | Thresholds such as the elevated-hour rule are exploratory | bounded | Thresholds set before data |
| 14 | Classical, hybrid and neural experiments | Ridge, trees, GRU, TCN, frozen-GRU hybrid | Run 829fed: tuned ridge and TCN trained in one run on the same rows (TCN MAE 4.711, ridge 4.697, B4 4.680) | Evaluator scores; reload differences 0.0 | One seed and one configuration; reused validation years; the TCN chose its epoch on them | bounded | Several seeds; an unused evaluation period |
| 15 | Reuse, transfer, distillation, pretrained satellite | Frozen encoder; distillation; Prithvi Level A | Prithvi: one chip, IoU 0.912. Distillation: no adopted gain. | Prithvi hash checks; distillation recomputed | One chip from the publisher's test split is a reproduction, not a transfer result | partial | Independent labels; Level B |
| 16 | Tracking, tuning, registry | Rolling-origin search; registry; reload checks | Run 829fed: 5 penalties, 3 folds, in the run; `tuning_verified` and `inference_verified` records | Reload difference 0.0 for both families | The chosen penalty is at the edge of the grid | bounded | A wider grid |
| 17 | Independent evaluation | Evaluator; sealed test; prospective ledger | Validation scores for every model. Prospective: 5 of 5 predictions scored at 08:40 UTC, MAE 7.2 µg/m³ (n = 5) | Leakage tests; adversarial suite; ledger availability check (#108) | Validation years reused; at most 5 prospective values | bounded | A longer prospective record |
| 18 | Routing, prompt and cost optimization | Profiler, prompt rules, router function | 48 saved runs compared | `docs/comparative-evidence-report.md` | No change gave a repeated gain; nothing promoted | partial | Deferred, by decision |
| 19 | Responsive UI | Workspace, Lab, Control Room | M3 added to the Workspace and Lab | UI tests; replay tests | No usability study | bounded | Usability study |
| 20 | Deployment readiness | Bundles; hosted replay entry; ledger | 5 predictions issued from published data; all 5 scored against later published values, 0 pending | Ledger digests; availability check | Not a forecast service; no monitoring | bounded | Monitoring; a longer record |

Counts: 16 bounded, 3 partial (8, 15, 18), 1 future (1). These counts are the same as before 3 November. The new runs add evidence inside rows that were already bounded. They do not complete any row.

## What did not change

- **#8:** no new evidence shows a critic that finds faults code does not find.
- **#15:** one chip does not show validated transfer.
- **#18:** routing and prompt optimization stay deferred.
- **#1:** the cross-project organization stays future work.

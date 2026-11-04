# M4 critic report: the advisory model critic

Code: `src/earthlab/harness/decision_critic.py` (the critic), `src/earthlab/harness/critic_eval.py` (the seeded-fault test). Evidence: `docs/m4/evidence/critic-*.json`, `docs/m4/evidence/m4-attempts.json`.

## 1. What the critic is

- **A fifth, optional seat.** After the evaluator scores the models and the Lead recommends, the critic reads the evaluator's numbers and the recommendation. It can raise up to three findings.
- **Each finding cites evaluator numbers.** A finding names a kind, a claim, one to three evidence fields with exact values, and one measurement that would prove it wrong.
- **Code checks every cited value** against the evaluator's report (tolerance 0.5 percent). Code refuses a critique with a value that is not in the report, a decimal number in the text that no evaluator number rounds to, a mention of the sealed or held-out period, praise, a cause claim, or advice. The model gets one correction. After two failed attempts the critique is `unusable`, and the run goes on.
- **It is advisory.** It sets no score, outcome, claim or approval. The deterministic evaluator, the code rule (`code_outcome`), the safety gate and the human approval do not read it.
- **Its source is recorded.** `independent_model` when the critic's provider and model differ from the Lead's. `same_model_second_pass` when they are the same.
- **Gate.** The critic uses the `qa_reviewer` seat. That seat allows Meta families only. Qwen is therefore not allowed as a critic.

Code checks the numbers a finding cites. It does not check that the sentence draws the right conclusion from them. A reader must do that.

## 2. Seeded-fault test (10 labelled cases, one real report)

The cases use the recorded M3 report. Five recommendations are contradicted by the numbers (faults F1 to F5). Five are supported (C1 to C5). The labels were written before any critic ran. See `docs/m4/m4-protocol.md`.

| Critic model | Usable answers | Faults detected | Clean cases with a backed finding | Backed findings | Answers refused by code | Server errors | Model calls |
|---|---|---|---|---|---|---|---|
| Muse Glimmer 30B | 10 of 10 | 3 of 5 | 5 of 5 | 16 | 0 | 0 | 10 |
| Qwen3 4B Instruct 2507 | 10 of 10 | 1 of 5 | 2 of 5 | 8 | 0 | 0 | 10 |
| Llama 3.2 3B Instruct | 4 of 10 | 0 of 5 | 0 of 5 | 0 | 9 | 0 | 16 |
| Llama 3.1 8B Instruct | 2 of 10 | 0 of 5 | 0 of 5 | 0 | 8 | 4 | 14 |

Error rates, from the table:

| Rate | Muse | Qwen3 4B | Llama 3.2 3B | Llama 3.1 8B |
|---|---|---|---|---|
| Unusable or unavailable critique | 0 percent | 0 percent | 60 percent (6 of 10) | 80 percent (8 of 10) |
| Refused answers per model call | 0 percent | 0 percent | 56 percent (9 of 16) | 57 percent (8 of 14) |
| Fault missed (of 5 faults) | 40 percent | 80 percent | 100 percent | 100 percent |

- **Detected** means a backed finding cites a field that shows the seeded fault. A backed finding on another field does not count.
- **Muse missed F3 and F4.** Both are claims about elevated hours (MAE above 55 µg/m³). On these it gave findings on other fields.
- **Clean cases with a backed finding is a concern rate, not an error rate.** The evidence has real limits, so a critic can raise a true point on a good recommendation. Muse raised one on all five clean cases. Read its findings before you treat that as noise. Qwen raised one on two.
- **Why Llama failed.** The refusal reasons are schema faults: the model echoed the tool schema (`$defs: Extra inputs are not permitted`) or wrote `findings` as a string. Llama 3.1 8B also had four HTTP 500 errors from the server. The decisions-v1 report records the same fault for Llama 3.1 8B in a tool loop.
- **A usable answer is not a good one.** Llama 3.2 3B was usable on four cases and said "no concern" on all four, including a faulty case (F1, F4).
- All model calls used temperature 1.0, the harness setting.

## 3. Live critic records in the M4 runs

| Run | Critic | Source | State | Verdict | Backed findings |
|---|---|---|---|---|---|
| S-M primary `8e9959` | Muse | same model | usable | concerns | 1 |
| T-M primary `9f4613` | Muse | same model | usable | concerns | 1 |
| T-M secondary `35ab8b` | Muse | same model | usable | no concern | 0 |
| T-L primary `40d596` | Llama 3.2 3B | independent | usable | no concern | 0 |
| T-Mc primary `c32be1` | Llama 3.2 3B | independent | unusable | - | 0 |
| T-L secondary `e7c3a6` | Llama 3.2 3B | independent | unusable | - | 0 |

Totals: 6 critic records. 3 usable with the same model, of which 2 had a finding. 3 with the independent Llama critic, of which 1 was usable and none had a finding.

### The two findings

Both findings are in runs where the critic was a second pass of the Lead's checkpoint. They are not independent.

- **S-M, run `8e9959`.** The Lead's reason says B4 has the "lowest MAE 4.68 and RMSE 6.385 among evaluated models". The critic cites `B4_lagged_ridge.rmse` 6.385 and `candidate-ridge-cv.rmse` 6.381. The tuned ridge has the lower RMSE by 0.004 µg/m³. The Lead's claim is false in a small way. The MAE claim is true.
- **T-M, run `9f4613`.** The Lead's reason says candidate-1 has the "lowest MAE 4.572 and RMSE 6.383". The critic cites `candidate-1.rmse` 6.383 and `candidate-ridge-cv.rmse` 6.381. The tuned ridge is lower by 0.002 µg/m³. The MAE claim is true.

I checked both against the saved evaluator reports. Both are real. The size is tiny, and the choice of model does not change. The wording of each finding repeats the Lead's claim, and the evidence contradicts it. A reader must see that. This is the same kind of fault as in M3 (an unverified claim in agent text).

## 4. Findings of the critic design

1. Code can check numbers. It cannot check that a finding is relevant or complete. The check removes invented numbers. It does not make the critic right.
2. An independent critic needs a model that can follow a schema. The two Meta checkpoints allowed for this seat did not, in this harness at temperature 1.0.
3. A same-model critic can catch a factual slip in the Lead's text. That is a second pass, and it shares the Lead's blind spots.
4. Qwen3 4B followed the schema best of the small models but is barred from the seat by the Meta-only supervising rule. This report does not change that rule.

## 5. Limits

- 10 synthetic recommendations on one real report. Five clean cases are alike (all keep the lagged ridge).
- 6 live records. No rate has an interval.
- The method-review critic (before the work) did not run in any counted run. Amendment 1 turned it off after it refused the first run.
- The critic never saw the sealed period.

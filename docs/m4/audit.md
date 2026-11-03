# M4 audit: provider bindings, role routing and benchmark infrastructure

Base: `release/hackathon-2026` at `4e4a4f1`. Scope: `src/earthlab/` and `config/`. Method: read the code, then run the tests that cover it. No recorded evidence changed.

## Findings

| # | Area | Finding | Effect | Action in M4 |
|---|---|---|---|---|
| A1 | Role routing | `Seats.role` builds one client per role from `role_clients`, with the Lead client as default. | Per-role models already work for PM, Lead and the two specialists. | Keep. |
| A2 | Role routing | The method critic (`method_critic`) had no entry in the arm spec. It always fell back to the Lead client. | The critic could never be an independent model in a matrix run. The record would say `same_model_second_pass`. | Add `critic`, `method_review` and `decision_critic` to `ArmSpec`. |
| A3 | Matrix runner | `matrix_run.one_run` never passed `method_review`. | No matrix arm could use the critic. | Pass the arm's flags and the checkpoint registry. |
| A4 | Trace | A trace shows `served_model` (an alias) and no file name or hash. Provider names are only in `result.json`. | A reader cannot prove which checkpoint served a seat from the chain. | Add `role_binding` and `council_formed` records before the first model call. |
| A5 | Bindings | `qa_reviewer` was `planned`, so no candidate could serve it. | A critic seat could not pass the gate. | Make it `experimental`. Add the candidate role only after a critic preflight passes. |
| A6 | Event adapter | The adapter fails closed on an unknown event or actor. A `method_critic` actor and the new records would break replay. | The UI would show an error for any heterogeneous run. | Map the new records. Map `method_critic` to `qa_reviewer`. |
| A7 | UI | The evidence table said "N Muse Glimmer calls" for every model run. The critic note said every critic is a same-model pass. | The page would credit Muse for Llama or Qwen work. | Read the checkpoints from the trace. Write the critic source from the record. |
| A8 | Memory | The decisions-v1 report ruled that small models do not run beside Muse. The measured sum failed the 28 GB limit. Swap was 17.8 of 18.4 GB with Muse alone. | `T-sp4` and `T-pm3` never ran. | The owner now allows one extra server at a time. Run them, and record swap. |
| A9 | Gates | The Lead gate allows Muse only. | A non-Muse Lead stays blocked. This is intended. | No change. |
| A10 | Prior result | In decisions-v1, small models ran only as unranked single agents, with 0 of 6 runs reaching verified goal completion. No small model ran inside a team. | Nothing in the repo shows a mixed team. | Run mixed teams (M4). |

## Not changed

- The deterministic verifier, the evaluator, the safety gate, the approval flow and the sealed test period.
- Any recorded trace, result or replay of M1 to M3.
- The Lead gate.

## Limits of this audit

- It reads code and tests. It does not prove the absence of other faults.
- The full test suite runs in CI. See the final report for what ran locally.

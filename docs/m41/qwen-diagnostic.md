# Qwen3 4B diagnostic (ML Specialist seat)

Evidence: `docs/m41/evidence/qwen-preflight.json`. Script: `scripts/m41_qwen_preflight.py`.
The M4 failures stay in `docs/m4/evidence/m4-attempts.json` (runs `1f6f19` and `2a939b`).

## 1. What failed in M4

In run `1f6f19` Qwen called `prepare_data` correctly in turn 1. In turn 2 it wrote a correct
plain-text summary of the tool result and did not call `submit_note`. The harness sent
`tool_choice: auto`, so a text answer was allowed. The run stopped with
"data_specialist stopped without submit_note". The reminder prompt (run `2a939b`) did not
change this.

## 2. Causes tested

| Cause | Test | Result |
|---|---|---|
| Server or checkpoint identity | `/props` file name and file SHA-256 | Match. `3605803b...`, load 4.3 s |
| Chat template or tool-call format | Turn 1 tool call in the M4 run | Works. The first call was correct in M4 and here |
| Optional closing call (protocol) | Tool loop, closing turn `tool_choice: auto`, 4 packages | 2 of 4 called `submit_note`. The M4 fault class reproduces |
| Forced closing call | Same loop, closing turn `tool_choice: required` | 3 of 4 |
| Schema output (M4.1 protocol) | `ModelAssessmentV1`, grammar-constrained, 4 packages x 2 seeds | 8 of 8 valid on the first attempt, no repair |
| Budget or timeout | All calls finished under the limits | Not a cause |
| Memory or switching | One small model beside Muse | Not a cause in these runs |

## 3. Conclusion

- The M4 failure was a protocol fault: the closing step was optional, and a small model often
  stops after it has the data. It was not a template, parser or checkpoint fault.
- A forced closing call reduces the fault but did not remove it in this test (3 of 4; one
  answer was still text).
- Schema-constrained output removes the format fault for this role: 8 of 8. The seat passes
  the gate of protocol m41-v1 (at least 7 of 8).
- **Valid is not correct.** In one tool-loop answer Qwen wrote that ERA5 and FIRMS inputs
  improve the prediction. The package shows the opposite. The council benchmark scores what
  Qwen's findings say, not only their format.

## 4. Limits

8 schema calls and 8 tool-loop calls. Temperature 0.0. One machine. No claim about other
prompts or other packages.

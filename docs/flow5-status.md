# Flow 5: where the integrated run stops

Flow 5 asks for one continuous Muse-directed run:

1. Question and criteria.
2. Dataset discovery.
3. Authorized acquisition.
4. Validation and features.
5. Method choice.
6. The experiment.
7. Critique and revision.
8. Decision.

The run stops at step 3 for PM2.5 with wind and rain. The verified parts are shown separately below. They are not one continuous run.

## Stopping point: step 3, acquisition of NEA wind and rain history

| Blocker | Evidence |
|---|---|
| The harness has no acquisition stage. A Muse seat cannot request new data inside a run. | `earthlab.harness.lifecycle`: requested, scoped, profiled, planned, executing, evaluated, reviewed, forwarded |
| The request contract cannot express dated history. NEA history needs `?date=` and paging. `ResourceRequestV1` refuses a URL with a query, so that secrets never sit in a URL. | Tested 2026-11-03: the dated URL is refused; the undated URL is accepted, but it returns only the latest values. |
| History does not cover the train years. | The archive had wind data for 2018-06-01, but none for 2016-03-01 ("Data not found"). |
| No spatial rule exists. Wind and rain come from 16 and 88 stations. PM2.5 comes from 5 regions. | `docs/live-data-and-forecast-inputs.md` |

Lifting the first two blockers needs two changes:

- a new harness stage;
- a contract change for allowlisted query parameters.

Both are architecture work, so they are not done on the freeze day. Even with them, the coverage gap and the missing spatial rule would lead to refusal.

## The verified parts, each shown on its own

| Flow 5 step | Verified part | Evidence |
|---|---|---|
| 1, 5, 6, 7, 8 on PM2.5 | Muse team run M2. Muse chose the statistical strategy, code ran the tools and scored, code refused `adopt_limited`, and Muse retained persistence. | `docs/muse-team-regression-run.md`, replay `scenario-muse-team-regression` |
| 2 | NEA catalogue with units, periods, places and times | `docs/live-data-and-forecast-inputs.md` |
| 3 | One real, bounded capture of the latest NEA values: 141 values with digests | `earthlab.acquire.nea_live` |
| 3, permission | Resource requests that stop at a person: the Prithvi weights and HLS chips, endorsed by Muse as Lead and PM | Request store; S4 replay |
| 6, tuning | Rolling-origin ridge search on the train years | `docs/rolling-origin-ridge-v1.md` |
| 6, registry | Ridge and trees bundles with verified saved-bundle inference | `docs/model-acceptance-v1.md` |
| 7, deterministic critique | Adversarial suite: 35 of 35 attacks refused, 20 of 20 controls allowed | `docs/adversarial-qa-v1.md` |

The same-model critic stays off.

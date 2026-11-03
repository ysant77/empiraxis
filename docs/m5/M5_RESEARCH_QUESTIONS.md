# M5 research questions (registered 2026-11-03, owner addendum)

The text of each question is verbatim from the owner. The frozen protocol `m5-protocol-1` is not
edited. This file registers the questions beside it. Amendment 3 in `M5_PROTOCOL_V1_AMENDMENTS.md`
links them.

## M5-A: Multisource PM2.5 prediction (primary, first)

Can historical wind speed/direction, rainfall, regional fire activity, satellite imagery and soil moisture improve Singapore's six-hour-ahead PM2.5 predictions beyond PM2.5-only baselines, especially during severe haze episodes?

- **Served by:** protocol `m5-protocol-1`, Experiment B (issue-time ladder) and Experiment A (hindsight association).
- **State:** pilot run. No supported gain. Imagery and soil moisture failed their data gates. Rain (IMERG) is pending.

## M5-B: Regional transport consistency (later stage)

Which upwind fire regions show atmospheric transport conditions and temporal associations consistent with subsequent PM2.5 increases in Singapore? Can we distinguish suggestive evidence from unsupported source attribution?

- **Needs:** its own protocol and validation. Not started.
- **Link to the pilot:** the exploratory Experiment A pairs for source box B are a starting point only.
- **Limit:** no source attribution. Allowed words: "temporal association", "consistent with".

## M5-C: Severe-event prediction and uncertainty (later stage)

Can we predict severe Singapore PM2.5 episodes 12–24 hours ahead using genuinely issue-time-available inputs, with calibrated uncertainty and appropriate abstention when evidence is insufficient?

- **Needs:** its own protocol, issue-time-valid inputs only (no ERA5), calibration and abstention rules. Not started.
- **Limit:** no operational forecast claim.

## Separation rule

The 2015 negative ablation (persistence 30.76, ridge 32.10, + ERA5 36.73, + FIRMS 41.75 µg/m³) is a
published, separate finding. M5 results are reported in their own tables and never mixed with it
or with the M3 numbers.

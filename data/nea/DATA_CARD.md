# Data card: NEA Historical 1-hr PM2.5

| Field | Value |
| --- | --- |
| Publisher | National Environment Agency (NEA), Singapore |
| Source | https://data.gov.sg/datasets/d_6c0d5fc34838b12472475fdb73c0af29/view |
| Licence | Singapore Open Data Licence v1.0 (https://data.gov.sg/open-data-licence) |
| File | `Historical1hrPM2.5.csv`, 3,150,004 bytes |
| SHA-256 | `2fb76e1c4e4208e92f49670602e303c86e21eaa3704651633323e50f51015de4` |
| Retrieved | 2026-10-27 04:01 UTC through the data.gov.sg download API |
| Coverage | 2014-04-01 01:00 to 2026-10-01 00:00, Singapore time |
| Unit | ug/m3, 1-hour PM2.5 concentration |
| Spatial support | Five reporting regions. Not station coordinates. |

## Attribution

Contains information from Historical 1-hr PM2.5 accessed on 27 October 2026 from data.gov.sg, which is made available under the terms of the Singapore Open Data Licence version 1.0.

## Known issues in this file (found by `earthlab qa` and the loader)

| Issue | Count | Handling |
| --- | --- | --- |
| Rows not in time order | present | Sorted after load; each case recorded. |
| Duplicate hour labels | 4 | First row kept; each duplicate recorded, conflicts flagged. |
| Alternate time label `2016-04-04 010:00:00` | 1 | Parsed as 10:00 on 4 April 2016; recorded. |
| Hours missing from the full 2014–2026 range | yes | Never filled. Reported as gaps per window. |
| Non-numeric or negative values | 0 | Would be treated as missing. |

The September–October 2015 window has all 1,464 hours for all five regions.

## Time labels

Labels are Singapore local civil time (UTC+08:00, no daylight saving). The source does not state whether a label marks the start or the end of the hour. EarthLab keeps the published label and does not shift it.

## What the data cannot show

- The data cannot show the cause of a PM2.5 value. Fire attribution needs hotspot, meteorology and transport evidence.
- The data cannot give values at a point. Each value is a regional aggregate.
- PM2.5 values are not PSI or AQI values.

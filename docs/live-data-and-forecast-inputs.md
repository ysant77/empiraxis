# Live data catalogue and forecast-input review

Status: experimental. This is a data foundation for a future prospective study. It is not a forecast service.

## NEA real-time products

Source: api-open.data.gov.sg, Singapore Open Data Licence. Code: `earthlab.acquire.nea_live`. The table comes from the live responses on 2026-11-03.

| Product | Places | Unit as published | Period | Times in the response |
|---|---|---|---|---|
| `pm25` | 5 regions, with label coordinates | µg/m³ (no unit field; the product states PM2.5 one-hourly) | 1 h mean | `timestamp` and `updatedTimestamp`. The 00:00 value was published at 00:30:45. |
| `wind-speed` | 16 stations | knots | 1 min mean | `timestamp` only |
| `wind-direction` | 16 stations | degrees, wind from | 1 min mean | `timestamp` only |
| `rainfall` | 88 stations | mm | 5 min total | `timestamp` only |
| `relative-humidity` | 16 stations | percent | 1 min mean | `timestamp` only |

Every captured value has:

- the product, the station or region, and its coordinates;
- the observation time;
- the publication time, when the source gives one;
- the retrieval time;
- the value, unit and period;
- the URL and the SHA-256 of the raw response.

Rules in the code:

- Units stay as published. Wind speed stays in knots, and rainfall stays a five-minute total.
- Station values are not joined to the five PM2.5 regions. A spatial rule must be written first.
- The log is append-only. A changed value for the same product, place and time is added as a correction. The first value stays.
- One request per product, at least 2 s apart, with no retries.

Only PM2.5 states a publication time. For the station products, the retrieval time is the latest time at which the value was known to be available.

### Capture made

On 2026-11-03 at 00:45 SGT, one capture of the five products stored 141 values:

- 5 PM2.5 values;
- 16 values each for wind speed, wind direction and humidity;
- 88 rainfall values.

The log is outside the repository at `earthlab-live-capture/nea-live.jsonl`. No scheduled capture exists.

```bash
uv run python scripts/capture_nea_live.py <log outside the repository>
```

## Forecast inputs at a 6-hour issue time

A forecast input must be available at the issue time. A reanalysis is not.

Items marked "not verified" were not checked against the provider in this session. Check them before any use.

| Candidate | Class | Quantity and relevance | Availability at issue time | Access and licence | Decision now |
|---|---|---|---|---|---|
| NEA station wind, rain, humidity | Observation | Local ventilation and wet removal | Yes, minutes after the hour (measured above) | Open, no key | First choice. A spatial join rule is needed first. |
| ECMWF IFS open data | Issued forecast | 10 m and 850 hPa wind, precipitation | Yes, after each run is published. Latency not verified. | Open data; licence terms not verified | Candidate. Its archive of past runs is short, so a hindcast needs another source. |
| CAMS global composition forecast | Issued forecast | Aerosol optical depth, PM2.5 near the surface | Yes, after each run. Latency not verified. | Atmosphere Data Store account | Candidate. It needs owner approval for the account. |
| ERA5 | Reanalysis | Wind and rain | No: published with a delay of days | Copernicus | Hindsight only, as in S3. Never a forecast input. |
| Soil moisture (SMAP, ERA5-Land) | Observation or reanalysis | Peat dryness, a slow fire-risk signal | Days of delay | Varies | Not now. It changes over weeks, not 6 h, and the delay is longer than the horizon. |
| MAIAC aerosol optical depth | Satellite retrieval | Smoke column | About one day of delay; cloud gaps (not verified) | NASA Earthdata | Not now: it fails the 6 h availability check. |
| HLS imagery | Satellite reflectance | Burn scars | Days of delay, cloud gaps | NASA | Not a 6 h input. Burned-area work only, as in S4. |
| Hyperspectral (EMIT) | Satellite | Not needed | Sparse | NASA | Refused: no stated need, and HLS is not hyperspectral. |

The complex scenario may decide that none of the extra products helps. That is a valid result.

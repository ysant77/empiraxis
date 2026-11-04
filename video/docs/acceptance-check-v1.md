# Empiraxis Video V1 — factual and visual acceptance check

| Item | Value |
|---|---|
| File | `Empiraxis_Video_V1.mp4` |
| Format | 1920×1080, 30 fps, H.264 + AAC |
| Runtime | 2:34.6 |
| Loudness | −15.6 LUFS integrated (target −15), LRA 2.8 LU |
| Release shown | `4e4a4f1` (`release/hackathon-2026`). The release was not changed. |
| Checksums | `V1_SHA256SUMS.txt` |

## On-screen numbers and their sources

| On screen | Value | Source | Status |
|---|---|---|---|
| FIRMS detections | 84,224 (4,902 + 37,544 + 41,778), 25 Aug – 31 Oct 2015 | FIRMS MODIS manifests and CSVs, 3 study boxes | ✓ |
| Haze peak | 471 µg/m³, 19 Oct 2015, highest of 5 regions | NEA PM2.5 file, hour index 1175 | ✓ |
| Question card | 5 regions · 109,584 rows · 2014–2023 | M3 `result.json` | ✓ |
| Model calls and tokens | count up to 12 and 22,516 | sum of `model_turn` usage in `trace.jsonl` (14,428 + 8,088) | ✓ |
| Refused proposals | 2 refused (#12, #46) | `proposal_reviewed` records | ✓ |
| Popovers #14, #16, #33 | recorded proposal text, verbatim | `trace.jsonl` | ✓ |
| MAE, all hours | 4.680 / 4.697 / 4.711 / 5.465 | M3 `result.json` | ✓ |
| MAE, above 55 µg/m³ | 30.25 / 30.58 / 32.43 / 26.32 | M3 `result.json` | ✓ |
| Reload checks | 0.0 / 0.0; TCN over 43,818 rows, hash ✓ | trace #33 `inference_verified` | ✓ |
| TCN | 10,287 parameters · 8 epochs · 180 s | M3 `result.json` | ✓ |
| Skill | 0.142 [0.132, 0.151] | M3 `result.json` | ✓ |
| Recommendation | retain_baseline → B4 lagged ridge; the reason is quoted from the trace | trace #42 | ✓ |
| Acquisition | 333 / 350 match; 17 disagree, all on 15 Nov 2023; 14,865 bytes | run 95e7a3 receipt and capture log | ✓ |
| Hash chain | real prefixes; head 6740b801 | `trace.jsonl` | ✓ |
| Predictions | 5 regions · MAE 7.2 · n = 5 · "not evidence of forecast skill" | prediction ledger, `docs/prospective-verification.md` | ✓ |

## Honesty and labelling checks

- ✓ The four roles are labelled "FOUR ROLES · ONE LOCAL MODEL — not four independent models".
- ✓ Llama and Qwen do not appear as M3 participants. Llama Guard 3 is credited only for investigation mode.
- ✓ Labels on screen:
  - "RECORDED REPLAY · NOT LIVE";
  - "HISTORICAL VALIDATION 2019–2023 · REUSED YEARS";
  - "MODEL PROPOSAL" against "CODE EXECUTION".
- ✓ The human gate shows "Human decision pending". The film claims no approval.
- ✓ The globe is labelled as context only. There are no smoke trajectories and no source attribution. The basemap is labelled "modern composite, not 2015 imagery".
- ✓ Negative results (REJECT / ABSTAIN / REQUEST) are crops of real decision panels.
- ✓ The release was not changed. The film made no model calls and did no training. All film numbers come from recorded artifacts.

## Audio and captions

- **Narration:** Kokoro v1.0 (Apache-2.0), voice `af_heart`, rendered locally.
- **ASR check of the final mix:** faster-whisper. Word match is 0.92. All differences are number formatting ("350" against "three hundred and fifty") or minor ASR errors. No wrong word was found.
- **Music:** Meta MusicGen-medium, generated locally. The weights are CC-BY-NC 4.0, which allows non-commercial use only. The credits name it.
- **Captions:** the video has no burned-in subtitles. `Empiraxis_Video_V1.srt` is an optional sidecar file that uses display spellings (PM2.5, NEA, 471 µg/m³).

## Visual check

- `contact_sheet.png` and `stills/` are 16 frames taken from the final MP4. They show no clipped text, no overlapping wires and no layout overflow.

## Known limits

- Runtime is 2:35, which is under the 3:00 limit.
- The music licence is non-commercial. If the use becomes commercial, replace the music.

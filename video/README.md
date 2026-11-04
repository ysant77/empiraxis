# Video production kit

This folder holds everything that is needed to rebuild the Empiraxis film and to make the next
version. Any developer or agent can use it. It needs no access to the original machine.

The film is a **recorded replay**. It calls no model, trains nothing and changes no evidence.
Every number on screen comes from a file that a real run wrote.

## 1. Rules (read first)

1. Show only numbers that a recorded run produced. Write the source file of each number in the
   fact-check document before you render.
2. Label every scene with what it is: "RECORDED REPLAY · NOT LIVE", "HISTORICAL VALIDATION",
   "EXPLORATORY", "PROPOSED · NOT RUN".
3. Do not claim a cause of haze from PM2.5. Use "temporal association" or "consistent with".
4. Do not claim an operational forecast or health advice.
5. Name the checkpoint of each role. If one model fills several roles, say so on screen
   ("FOUR ROLES · ONE LOCAL MODEL"). A critic on the Lead's checkpoint is not independent.
6. Show the human gate as pending. The film never shows an approval that did not happen.
7. Credit every model, voice, music model and data source in the closing credits.
8. Do not render a new version until the owner approves the plan for it.

## 2. Layout

| Path | What it is |
|---|---|
| `replay/index.html`, `app.js`, `style.css` | The replay page. MapLibre GL 5.6.1 globe, plain JS. |
| `replay/data.js` | Bundled recorded data (built by `build_data.py`, SHA-256 prefix `314f17e885f4`). |
| `replay/timeline.js` | Scene and narration times (built by `tools/timeline.py`). |
| `replay/img/` | Crops of the real Control Room and decision panels at release `4e4a4f1`. |
| `replay/inputs/` | Small derived inputs: the 2015 haze curve and the NEA acquisition grid. |
| `tools/` | Narration, timing, frame capture, music, mix, captions and the ASR check. |
| `tools/vo.json` | Narration lines, by scene. Spoken spellings ("P M two point five"). |
| `docs/` | V1 plan, V1 acceptance check, V1.1 fact check, V1.1 narration, the next-version plan. |
| `work/` | Generated audio, stills, music and films. Not in Git. Set `VIDEO_WORK` to move it. |

## 3. Setup

- Python 3.12. Packages for the tools (not part of the main project):
  `pip install playwright kokoro-onnx soundfile numpy pillow faster-whisper`
  and `python -m playwright install chromium`. For music: `torch transformers scipy`.
- `ffmpeg` on the path.
- Kokoro v1.0 model files `kokoro-v1.0.onnx` and `voices-v1.0.bin` in `work/models/`
  (from the kokoro-onnx project releases, Apache-2.0).
- A TrueType font for burned captions: set `CAPTION_FONT`.

## 4. Build the film

Run these from the repository root.

```bash
python video/tools/tts.py af_heart 1.0
```

```bash
python video/tools/timeline.py
```

```bash
python -m http.server 8710 --bind 127.0.0.1 -d video/replay
```

Open `http://127.0.0.1:8710/index.html` to scrub the replay. Then, in a second shell:

```bash
python video/tools/render.py --at 16 49 62.9
```

```bash
python video/tools/render.py video/work/out/silent.mp4
```

```bash
python video/tools/music.py intro 70
```

```bash
python video/tools/music.py main 140
```

```bash
python video/tools/mix.py video/work/out/silent.mp4 video/work/out/film.mp4
```

```bash
python video/tools/finish.py video/work/out/film.mp4 video/work/out/film.srt
```

```bash
python video/tools/burn.py video/work/out/film.mp4 video/work/out/film.srt video/work/out/film_captioned.mp4
```

`finish.py` prints the word match between the script and a speech-recognition transcript of the
final mix. V1.1 scored 0.92. Read every difference it prints.

## 5. Rebuild the data bundle

`data.js` is committed. To rebuild it, you need the recorded inputs:

```bash
python video/replay/build_data.py --release REL --firms FIRMS --ledger LEDGER --run RUN
```

- `REL`: a checkout at release `4e4a4f1`.
- `FIRMS`: `runs/haze-2015/firms` from the 2015 ablation (NASA FIRMS MODIS standard product).
- `LEDGER`: the prediction ledger folder.
- `RUN`: the M3 run folder `20261103T061204Z-829fed`.

The script prints the SHA-256 prefix. It must be `314f17e885f4` for the same inputs.

## 6. How a scene works

`app.js` draws one frame for a time `t` (`frame(t)`), and `window.seek(t)` is the capture entry
point. `TL.scenes` gives each scene's start and end, and `TL.lines` gives each narration line.
To add a scene:

1. Add its lines to `tools/vo.json` with a new scene id.
2. Add the id to `PRE` in `tools/timeline.py`.
3. Add its HTML block to `index.html` and its drawing code to `frame(t)` in `app.js`.
4. Add any new data to `build_data.py`, from a recorded file only.
5. Run `tts.py`, `timeline.py`, then capture stills and check them.

## 7. Released versions (films are not in Git)

| File | SHA-256 |
|---|---|
| `Empiraxis_Video_V1.mp4` (2:34.6) | `2ae8620500095d10efd84f72757194aa5231eda53d9be3f3933ee1b2cf86893f` |
| `Empiraxis_V1_1.mp4` (2:49.2) | `ee2b7d815d962d5b8774cccac0a371d4796eb804c9e0d5cc8a313e184545a147` |
| `Empiraxis_V1_1_captioned.mp4` | `224dc534936518050ec682c4e94f3802ca0ae007dee050e114bcc67d6e2dae30` |
| `Empiraxis_V1_1.srt` | `4466c238da5f4f446656fd36ae0569423e0749e559f7170126d4e3d066bea1fd` |

The committed `tools/vo.json`, `tools/vo_timings.json`, `tools/timeline.json` and
`replay/timeline.js` are the V1.1 versions.

## 8. Next version

See `docs/video-2-plan.md`. It is a plan only. It waits for owner approval.

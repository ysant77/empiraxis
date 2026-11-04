"""Render the narration lines in vo.json with Kokoro v1.0 (Apache-2.0), locally.

Usage: python video/tools/tts.py VOICE SPEED   (V1.1 used: af_heart 1.0)
Needs: kokoro-onnx, soundfile, numpy, and the model files in $VIDEO_WORK/models/.
Writes: $VIDEO_WORK/audio/NN.wav and video/tools/vo_timings.json.
"""

from __future__ import annotations

import sys
from collections import Counter

import numpy as np
import soundfile as sf
from common import WORK, load, save
from kokoro_onnx import Kokoro


def trim(a: np.ndarray, sr: int) -> np.ndarray:
    idx = np.where(np.abs(a) > 0.01)[0]
    return a[max(idx[0] - int(0.03 * sr), 0) : idx[-1] + int(0.08 * sr)]


def main() -> None:
    voice, speed = sys.argv[1], float(sys.argv[2])
    k = Kokoro(str(WORK / "models/kokoro-v1.0.onnx"), str(WORK / "models/voices-v1.0.bin"))
    (WORK / "audio").mkdir(parents=True, exist_ok=True)
    out = []
    for i, (scene, text) in enumerate(load("vo.json")):
        a, sr = k.create(text, voice=voice, speed=speed, lang="en-us")
        a = trim(a, sr)
        rel = f"audio/{i:02d}.wav"
        sf.write(WORK / rel, a, sr)
        out.append({"scene": scene, "wav": rel, "dur": round(len(a) / sr, 3), "text": text})
    save("vo_timings.json", out)
    per_scene: Counter[str] = Counter()
    for o in out:
        per_scene[o["scene"]] += o["dur"]
    print({k: round(v, 1) for k, v in per_scene.items()}, "total", round(per_scene.total(), 1))


if __name__ == "__main__":
    main()

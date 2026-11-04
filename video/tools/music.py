"""Generate a music bed locally with Meta MusicGen-medium (weights CC-BY-NC 4.0).

Usage: python video/tools/music.py intro|main SECONDS [SEED]   (default seed 7)
Needs: torch, transformers, scipy. Writes $VIDEO_WORK/music/NAME.wav.
Long beds are built in 30 s steps; each step continues from the last 10 s of audio.
The output is not deterministic across machines. Listen to it before use.
"""

from __future__ import annotations

import sys
import time

import numpy as np
import scipy.io.wavfile as wv
import torch
from common import WORK
from transformers import AutoProcessor, MusicgenForConditionalGeneration

MODEL = "facebook/musicgen-medium"
PROMPTS = {
    "intro": "dark cinematic ambient documentary intro, slow evolving warm synth pads, deep sub "
    "bass drone, soft ticking clock pulse, gradual tension build, no vocals, high quality",
    "main": "modern uplifting tech startup product launch background music, warm analog synth "
    "arpeggio, soft punchy electronic drums, deep bass, steady 100 bpm, inspiring and "
    "confident, clean mix, no vocals, high quality",
}


def main() -> None:
    name, total = sys.argv[1], float(sys.argv[2])
    torch.manual_seed(int(sys.argv[3]) if len(sys.argv) > 3 else 7)
    dev = "mps" if torch.backends.mps.is_available() else "cpu"
    proc = AutoProcessor.from_pretrained(MODEL)
    model = MusicgenForConditionalGeneration.from_pretrained(MODEL).to(dev)
    sr = model.config.audio_encoder.sampling_rate

    def gen(secs: float, audio: np.ndarray | None = None) -> np.ndarray:
        kw: dict = {"text": [PROMPTS[name]], "padding": True, "return_tensors": "pt"}
        if audio is not None:
            kw.update(audio=[audio], sampling_rate=sr)
        inp = {k: v.to(dev) for k, v in proc(**kw).items()}
        out = model.generate(
            **inp, do_sample=True, guidance_scale=3.0, max_new_tokens=int(secs * 50)
        )
        return out[0, 0].float().cpu().numpy()

    t0 = time.time()
    a = gen(min(30, total))
    while len(a) / sr < total - 0.5:
        ctx = a[-int(10 * sr) :]
        nxt = gen(min(30, total - len(a) / sr + 10), audio=ctx)
        a = np.concatenate([a, nxt[len(ctx) :]])
        print("seconds", round(len(a) / sr, 1), flush=True)
    a = a / max(1e-6, np.abs(a).max()) * 0.9
    (WORK / "music").mkdir(parents=True, exist_ok=True)
    wv.write(WORK / f"music/{name}.wav", sr, (a * 32767).astype(np.int16))
    print(name, round(len(a) / sr, 1), "s in", round(time.time() - t0), "s on", dev)


if __name__ == "__main__":
    main()

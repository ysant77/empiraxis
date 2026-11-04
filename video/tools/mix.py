"""Mix narration and music under the silent film. Music ducks under the voice.

Usage: python video/tools/mix.py SILENT.mp4 OUT.mp4
Needs: $VIDEO_WORK/music/intro.wav and main.wav (V1.1: Meta MusicGen-medium, local, CC-BY-NC
weights), and the narration from tts.py. Loudness: -15 LUFS, true peak -1.5 dBTP.
"""

from __future__ import annotations

import shutil
import subprocess
import sys

import numpy as np
import soundfile as sf
from common import WORK, load

SR = 48000
FILTER = (
    "[1:a]volume=0.62[m];[2:a]asplit[v][sc];"
    "[m][sc]sidechaincompress=threshold=0.015:ratio=10:attack=30:release=600:makeup=1[md];"
    "[v][md]amix=inputs=2:normalize=0:duration=longest,loudnorm=I=-15:TP=-1.5:LRA=9[a]"
)


def read(path: str) -> np.ndarray:
    a, r = sf.read(path, dtype="float32")
    if a.ndim > 1:
        a = a.mean(1)
    if r != SR:
        a = np.interp(np.arange(0, len(a), r / SR), np.arange(len(a)), a).astype(np.float32)
    return a


def ramp(n: int, up: bool = True) -> np.ndarray:
    return np.linspace(0, 1, n) if up else np.linspace(1, 0, n)


def music_bed(tl: dict, n: int) -> np.ndarray:
    """Ambient intro (looped with a 4 s crossfade), then the main bed from the logo reveal."""
    intro, main = read(str(WORK / "music/intro.wav")), read(str(WORK / "music/main.wav"))
    cf, seg = 4 * SR, intro[6 * SR :]
    while len(intro) < 60 * SR:
        w = ramp(cf)
        intro = np.concatenate([intro[:-cf], intro[-cf:] * (1 - w) + seg[:cf] * w, seg[cf:]])
    music = np.zeros(n, np.float32)
    product = next(s for s in tl["scenes"] if s["id"] == "product")["start"]
    xi = int((product + 0.15) * SR)
    head = intro[: xi + int(1.2 * SR)].copy()
    head[-int(1.2 * SR) :] *= ramp(int(1.2 * SR), up=False)
    head[: int(1.5 * SR)] *= ramp(int(1.5 * SR))
    music[: len(head)] += head
    body = main[: n - xi].copy()
    body[: int(0.08 * SR)] *= ramp(int(0.08 * SR))
    music[xi : xi + len(body)] += body
    end, fade = int(tl["total"] * SR), 3 * SR
    music[end - fade : end] *= ramp(fade, up=False)
    music[end:] = 0
    return music


def main() -> None:
    tl = load("timeline.json")
    voice = np.zeros(int((tl["total"] + 1) * SR), np.float32)
    for line in tl["lines"]:
        a = read(str(WORK / line["wav"]))
        i = int(line["start"] * SR)
        voice[i : i + len(a)] += a
    (WORK / "out").mkdir(parents=True, exist_ok=True)
    sf.write(WORK / "out/voice.wav", voice, SR)
    sf.write(WORK / "out/music.wav", music_bed(tl, len(voice)) * 0.8, SR)
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    cmd = [ffmpeg, "-v", "error", "-y", "-i", sys.argv[1], "-i", str(WORK / "out/music.wav")]
    cmd += ["-i", str(WORK / "out/voice.wav"), "-filter_complex", FILTER, "-map", "0:v"]
    cmd += ["-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "256k", "-ar", "48000"]
    cmd += ["-t", f"{tl['total']:.3f}", "-movflags", "+faststart", sys.argv[2]]
    subprocess.run(cmd, check=True)  # noqa: S603 - fixed ffmpeg command
    print("mixed", sys.argv[2])


if __name__ == "__main__":
    main()

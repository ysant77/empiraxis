"""Write the SRT captions and check the final narration with speech recognition.

Usage: python video/tools/finish.py FILM.mp4 OUT.srt
Needs: faster-whisper (model small.en, CPU), soundfile, ffmpeg.
Prints the word match ratio against the script and every difference. Read the differences.
"""

from __future__ import annotations

import difflib
import re
import shutil
import subprocess
import sys

import soundfile as sf
from common import WORK, load
from faster_whisper import WhisperModel

# Spoken form in the narration -> written form in the captions.
SPOKEN = [
    ("Empi-raxis", "Empiraxis"),
    ("P M two point five", "PM2.5"),
    ("N E A", "NEA"),
    ("four hundred and seventy-one micrograms", "471 µg/m³"),
    ("twenty fifteen", "2015"),
    ("more than eighty thousand", "more than 80,000"),
    ("ten thousand", "10,000"),
    ("forty-three thousand", "43,818"),
    ("Seventeen of three hundred and fifty", "17 of 350"),
    ("M L", "ML"),
]


def written(s: str) -> str:
    for a, b in SPOKEN:
        s = s.replace(a, b)
    return s


def stamp(x: float) -> str:
    ms = round(x * 1000)
    return f"{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02},{ms % 1000:03}"


def words(s: str) -> list[str]:
    return re.sub(r"[^a-z0-9 ]", " ", s.lower()).split()


def main() -> None:
    film, srt = sys.argv[1], sys.argv[2]
    lines = load("timeline.json")["lines"]
    with open(srt, "w") as f:
        for k, ln in enumerate(lines, 1):
            span = f"{stamp(ln['start'])} --> {stamp(ln['start'] + ln['dur'])}"
            f.write(f"{k}\n{span}\n{written(ln['text'])}\n\n")
    wav = WORK / "out/asr.wav"
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    cmd = [ffmpeg, "-v", "error", "-y", "-i", film, "-ac", "1", "-ar", "16000", str(wav)]
    subprocess.run(cmd, check=True)  # noqa: S603 - fixed ffmpeg command
    audio, _ = sf.read(wav, dtype="float32")
    segs, _ = WhisperModel("small.en", device="cpu", compute_type="int8").transcribe(
        audio, beam_size=5
    )
    hyp = words(" ".join(s.text for s in segs))
    ref = words(" ".join(ln["text"] for ln in lines).replace("Empi-raxis", "Empiraxis"))
    sm = difflib.SequenceMatcher(None, ref, hyp)
    print("word match ratio", round(sm.ratio(), 3), "script words", len(ref))
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op != "equal":
            print(op, " ".join(ref[i1:i2]), "->", " ".join(hyp[j1:j2]))


if __name__ == "__main__":
    main()

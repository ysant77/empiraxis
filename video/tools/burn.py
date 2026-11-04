"""Burn SRT captions into a copy of the film (Pillow images and an ffmpeg overlay; no libass).

Usage: python video/tools/burn.py FILM.mp4 CAPTIONS.srt OUT.mp4
Font: $CAPTION_FONT (V1.1 used Avenir Next on macOS). Any TrueType font works.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

from common import WORK
from PIL import Image, ImageDraw, ImageFont

FONT = ImageFont.truetype(
    os.environ.get("CAPTION_FONT", "/System/Library/Fonts/Avenir Next.ttc"), 40, index=0
)
W, H, LINE, MAX_W = 1920, 1080, 58, 1500


def secs(x: str) -> float:
    h, m, s = x.replace(",", ".").split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def captions(path: str) -> list[tuple[float, float, str]]:
    out = []
    with open(path) as f:
        for blk in f.read().strip().split("\n\n"):
            ln = blk.split("\n")
            a, b = ln[1].split(" --> ")
            out.append((secs(a), secs(b), " ".join(ln[2:])))
    return out


def wrap(text: str) -> list[str]:
    lines, cur = [], ""
    for word in text.split():
        nxt = (cur + " " + word).strip()
        if FONT.getlength(nxt) > MAX_W and cur:
            lines.append(cur)
            cur = word
        else:
            cur = nxt
    return [*lines, cur]


def card(text: str, path: str) -> int:
    lines = wrap(text)
    h = LINE * len(lines) + 28
    im = Image.new("RGBA", (W, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    wmax = max(FONT.getlength(x) for x in lines)
    d.rounded_rectangle([(W - wmax) / 2 - 24, 0, (W + wmax) / 2 + 24, h], 12, fill=(0, 0, 0, 190))
    for k, x in enumerate(lines):
        d.text(((W - FONT.getlength(x)) / 2, 12 + LINE * k), x, font=FONT, fill=(255,) * 4)
    im.save(path)
    return h


def main() -> None:
    film, srt, out = sys.argv[1:4]
    (WORK / "out").mkdir(parents=True, exist_ok=True)
    inputs, filters = [], []
    for i, (a, b, text) in enumerate(captions(srt)):
        path = str(WORK / f"out/cap_{i:02d}.png")
        h = card(text, path)
        inputs += ["-i", path]
        prev = "[0:v]" if i == 0 else f"[v{i}]"
        when = f"enable='between(t,{a:.3f},{b:.3f})'"
        filters.append(f"{prev}[{i + 1}:v]overlay=0:{H - h - 40}:{when}[v{i + 1}]")
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    cmd = [ffmpeg, "-v", "error", "-y", "-i", film, *inputs, "-filter_complex", ";".join(filters)]
    cmd += ["-map", f"[v{len(filters)}]", "-map", "0:a", "-c:v", "libx264", "-crf", "17"]
    cmd += ["-preset", "medium", "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart"]
    subprocess.run([*cmd, out], check=True)  # noqa: S603 - fixed ffmpeg command
    print("burned", out, len(filters))


if __name__ == "__main__":
    main()

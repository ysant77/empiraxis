"""Capture the replay page frame by frame with Playwright and encode it with ffmpeg.

Serve video/replay first:  python -m http.server 8710 --bind 127.0.0.1 -d video/replay
Stills:  python video/tools/render.py --at 16 49 62.9   -> $VIDEO_WORK/stills/s_T.png
Film:    python video/tools/render.py OUT.mp4 [START END]   (silent, 1920x1080, 30 fps)
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from typing import Any

from common import FPS, URL, WORK, load
from playwright.sync_api import sync_playwright

GPU = ["--use-angle=metal", "--enable-gpu", "--ignore-gpu-blocklist"]


def stills(pg: Any, times: list[str]) -> None:
    (WORK / "stills").mkdir(parents=True, exist_ok=True)
    for t in times:
        pg.evaluate(f"seek({float(t)})")
        pg.wait_for_timeout(150)
        pg.screenshot(path=str(WORK / f"stills/s_{t}.png"))


def film(pg: Any, out: str, start: float, end: float, errs: list[str]) -> None:
    ffmpeg = shutil.which("ffmpeg") or "ffmpeg"
    enc = [ffmpeg, "-v", "error", "-y", "-f", "image2pipe", "-framerate", str(FPS), "-c:v", "png"]
    enc += ["-i", "-", "-c:v", "libx264", "-preset", "medium", "-crf", "15", "-pix_fmt", "yuv420p"]
    ff = subprocess.Popen([*enc, out], stdin=subprocess.PIPE)  # noqa: S603 - fixed ffmpeg command
    assert ff.stdin is not None
    for i in range(int(start * FPS), int(end * FPS)):
        pg.evaluate(f"seek({i / FPS})")
        ff.stdin.write(pg.screenshot(type="png"))
        if i % 900 == 0:
            print("frame", i, errs[:2], flush=True)
    ff.stdin.close()
    ff.wait()


def main() -> None:
    total = load("timeline.json")["total"]
    with sync_playwright() as p:
        browser = p.chromium.launch(args=GPU, headless=True)
        pg = browser.new_page(viewport={"width": 1920, "height": 1080})
        errs: list[str] = []
        pg.on("pageerror", lambda e: errs.append(str(e)))
        pg.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        pg.goto(URL)
        pg.wait_for_timeout(4000)
        if sys.argv[1] == "--at":
            stills(pg, sys.argv[2:])
        else:
            start = float(sys.argv[2]) if len(sys.argv) > 2 else 0.0
            end = float(sys.argv[3]) if len(sys.argv) > 3 else total
            film(pg, sys.argv[1], start, end, errs)
        browser.close()
        print("page errors", errs[:5])


if __name__ == "__main__":
    main()

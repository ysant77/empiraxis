"""Lay out scenes and narration lines in time from vo_timings.json.

Usage: python video/tools/timeline.py
Writes: video/tools/timeline.json and video/replay/timeline.js (read by the replay page).
"""

from __future__ import annotations

import json
from typing import Any

from common import REPLAY, load, save

# Seconds of picture before the first line of a scene, and between lines inside a scene.
PRE = {
    "earth": 3.0, "question": 0.6, "ablation": 0.9, "problem": 0.9, "product": 1.0,
    "council": 1.2, "train": 1.0, "evidence": 1.0, "gate": 0.7, "data": 0.8, "no": 0.7,
    "proof": 0.7, "next": 0.8, "close": 1.6,
}  # fmt: skip
GAP = {"council": 0.6, "earth": 0.6, "evidence": 0.55, "train": 0.6}
CREDITS = 6.5


def build(vo: list[dict[str, Any]]) -> dict[str, Any]:
    t, lines, scenes, cur = 0.0, [], [], None
    for i, v in enumerate(vo):
        if v["scene"] != cur:
            if scenes:
                scenes[-1]["end"] = round(t, 3)
            scenes.append({"id": v["scene"], "start": round(t, 3)})
            t += PRE[v["scene"]]
            cur = v["scene"]
        elif i:
            t += GAP.get(cur, 0.45)
        lines.append({"i": i, "scene": cur, "start": round(t, 3), **v})
        t += v["dur"]
    t += 0.8
    scenes[-1]["end"] = round(t, 3)
    scenes.append({"id": "credits", "start": round(t, 3), "end": round(t + CREDITS, 3)})
    return {"total": round(t + CREDITS, 3), "scenes": scenes, "lines": lines}


def main() -> None:
    tl = build(load("vo_timings.json"))
    save("timeline.json", tl)
    (REPLAY / "timeline.js").write_text("window.TL = " + json.dumps(tl) + ";\n")
    for s in tl["scenes"]:
        print(s["id"], s["start"], s["end"])
    print("total", tl["total"])


if __name__ == "__main__":
    main()

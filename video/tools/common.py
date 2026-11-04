"""Shared paths for the video tools. Generated audio, frames and films go to the work folder."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

TOOLS = Path(__file__).resolve().parent
REPLAY = TOOLS.parent / "replay"
WORK = Path(os.environ.get("VIDEO_WORK", TOOLS.parent / "work"))
FPS = 30
URL = os.environ.get("REPLAY_URL", "http://127.0.0.1:8710/index.html?capture=1")


def load(name: str) -> Any:
    return json.loads((TOOLS / name).read_text())


def save(name: str, data: Any) -> None:
    (TOOLS / name).write_text(json.dumps(data, indent=1) + "\n")

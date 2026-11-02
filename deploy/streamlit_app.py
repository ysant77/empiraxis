"""Hosted replay entry. Deploy this file; it serves recorded runs only."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from earthlab.ui import hosted  # noqa: E402

hosted.start(ROOT)

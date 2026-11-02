"""Hosted replay: the public entry to the recorded runs. It refuses any operator setting.

The hosted app has no live run, no approval queue, no metrics server and no model provider.
It starts only when the environment holds no operator mode, no replay-folder override and no
credential. It then runs the normal app, which reads only the manifest-checked replay folder.
"""

from __future__ import annotations

import os
import re
import runpy
from collections.abc import Mapping
from pathlib import Path

import streamlit as st

REPLAY = "examples/replay"
APP = Path("src/earthlab/ui/app.py")
_CREDENTIAL = re.compile(r"(?:KEY|TOKEN|SECRET|PASSWORD|CREDENTIALS?)$")
_FIXED = {"EARTHLAB_UI_MODE": ("", "replay"), "EARTHLAB_REPLAY_DIR": ("", REPLAY)}


def refusals(environ: Mapping[str, str]) -> list[str]:
    """Why the hosted app may not start. Names only: a value is never shown."""
    found = [
        f"{name} must be unset or {allowed[1]!r}"
        for name, allowed in _FIXED.items()
        if environ.get(name, "") not in allowed
    ]
    # Streamlit sets MAPBOX_API_KEY to "" itself; an empty name holds no credential.
    found += [f"{name} is set; a hosted replay holds no credential" for name, value in
              sorted(environ.items()) if value and _CREDENTIAL.search(name.upper())]  # fmt: skip
    return found


def start(root: Path) -> None:
    """Check the environment, pin replay mode, then run the app from the repository root."""
    found = refusals(os.environ)
    if found:
        st.error("This hosted replay refuses to start: " + "; ".join(found))
        st.stop()
    os.chdir(root)
    os.environ["EARTHLAB_UI_MODE"] = "replay"
    os.environ["EARTHLAB_REPLAY_DIR"] = REPLAY
    runpy.run_path(str(root / APP), run_name="__main__")

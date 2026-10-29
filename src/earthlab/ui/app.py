"""Streamlit app with three surfaces: Research Workspace, Control Room, Engineering Lab.

Replay mode (the default) reads recorded artifacts only and calls no model.
Run with:  uv run --extra ui streamlit run src/earthlab/ui/app.py
Local operator with live investigation:  EARTHLAB_UI_MODE=operator uv run ...
"""

from __future__ import annotations

from collections.abc import Callable

import streamlit as st

from earthlab.ui import common, control_room, engineering_lab, research

ROUTES: dict[str, tuple[str, Callable[[], None]]] = {
    "workspace": ("EarthLab Research Workspace", research.render),
    "control": ("Axiom Control Room", control_room.render),
    "lab": ("Geospatial Engineering Lab", engineering_lab.render),
}


def _route() -> str:
    keys = list(ROUTES)
    wanted = st.query_params.get("view", "workspace")
    index = keys.index(wanted) if wanted in keys else 0
    picked: str = st.sidebar.radio(
        "Surface", keys, index=index, format_func=lambda k: ROUTES[k][0], key="route"
    )
    st.query_params["view"] = picked
    return picked


def main() -> None:
    st.set_page_config(page_title="Axiom EarthLab", layout="wide")
    st.title("Axiom EarthLab")
    st.caption(
        "Evidence-first investigation of the 2015 haze and Kalimantan burned area with a Meta "
        "open-weight model. Research prototype: not health advice, not a forecast."
    )
    route = _route()
    st.sidebar.toggle("Single-column layout (phones)", key="compact")
    if common.ui_mode() == "replay":
        st.sidebar.caption(common.REPLAY_NOTE)
    else:
        common.metrics()
        st.sidebar.caption(
            f"Prometheus metrics: http://127.0.0.1:{common.METRICS_PORT}/metrics (local only)"
        )
    ROUTES[route][1]()


main()

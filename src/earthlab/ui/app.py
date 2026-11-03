"""Streamlit app with three surfaces: Research Workspace, Control Room, Engineering Lab.

Replay mode (the default) reads recorded artifacts only and calls no model.
Run with:  uv run --extra ui streamlit run src/earthlab/ui/app.py
Local operator with live investigation:  EARTHLAB_UI_MODE=operator uv run ...
"""

from __future__ import annotations

from collections.abc import Callable

import streamlit as st

from earthlab.ui import board_view, common, control_room, engineering_lab, nav, research, theme

SURFACES: dict[str, str] = {
    "workspace": "Research Workspace",
    "lab": "Engineering Lab",
    "control": "Control Room",
}
ROUTES: dict[str, Callable[[str | None], None]] = {
    "workspace": research.render,
    "lab": engineering_lab.render,
    "control": control_room.render,
}


def _mode() -> None:
    if common.ui_mode() == "replay":
        st.caption(f"**{common.REPLAY_NOTE}**")
    else:
        common.metrics()
        st.caption(
            f"**Local operator mode.** Metrics: http://127.0.0.1:{common.METRICS_PORT}/metrics"
        )


def main() -> None:
    st.set_page_config(
        page_title="Empiraxis", layout="wide", initial_sidebar_state="collapsed"
    )
    theme.apply()
    st.title("Empiraxis")
    st.write(
        "Human-supervised geospatial engineering: the system can train, reuse, reject a model "
        "or ask for evidence. Research prototype: not health advice, not a forecast."
    )
    _mode()
    route = nav.surface(SURFACES)
    label = nav.current_label()
    nav.scenario(label)
    board_view.banner()
    ROUTES[route](label)


main()

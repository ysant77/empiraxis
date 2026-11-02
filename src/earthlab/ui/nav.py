"""The surface and the scenario, held in the URL so a link, refresh or back step keeps them."""

from __future__ import annotations

import streamlit as st

from earthlab.ui import common, scenarios

SURFACE_KEY = "surface"
SCENARIO_KEY = "scenario"
DEFAULT_SCENARIO = "S1"


def surface(names: dict[str, str]) -> str:
    """The surface control. The URL wins, so the back button moves the control too."""
    wanted = st.query_params.get("view", "workspace")
    current = wanted if wanted in names else "workspace"
    st.session_state[SURFACE_KEY] = current
    st.segmented_control(
        "Surface",
        list(names),
        format_func=lambda key: names[key],
        key=SURFACE_KEY,
        label_visibility="collapsed",
        on_change=_surface_changed,
        width="stretch",
    )
    st.query_params["view"] = current
    return current


def _surface_changed() -> None:
    picked = st.session_state.get(SURFACE_KEY)
    if picked:
        st.query_params["view"] = picked


def current_label() -> str | None:
    """The selected run: the URL, then this session, then the default for this mode."""
    shared = st.query_params.get("run") or st.session_state.get(common.SHARED_RUN)
    labels = [label for label, _ in common.run_choices()]
    if shared in labels:
        return str(shared)
    if common.ui_mode() == "replay":
        default = f"replay/{scenarios.SCENARIO_RUNS[DEFAULT_SCENARIO]}"
        if default in labels:
            return default
    return labels[0] if labels else None


def scenario(label: str | None) -> None:
    """The four scenario choices. Any other selected run leaves all four unselected."""
    key = scenarios.key_of(label or "")
    st.session_state[SCENARIO_KEY] = key if key in scenarios.LABELS else None
    st.pills(
        "Scenario",
        list(scenarios.LABELS),
        format_func=lambda item: scenarios.LABELS[item],
        key=SCENARIO_KEY,
        label_visibility="collapsed",
        on_change=_scenario_changed,
    )
    if label is not None:
        st.session_state[common.SHARED_RUN] = label
        st.query_params["run"] = label


def _scenario_changed() -> None:
    picked = st.session_state.get(SCENARIO_KEY)
    if picked:
        go(f"replay/{scenarios.run_of(picked)}")


def go(label: str) -> None:
    st.session_state[common.SHARED_RUN] = label
    st.query_params["run"] = label

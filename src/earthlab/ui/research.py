"""EarthLab Research Workspace: one scenario at a time, readable without opening a trace.

Each page runs in one order: question, method, evidence, comparison, decision, limits.
Other recorded runs and the checking tools sit in the advanced section.
"""

from __future__ import annotations

import streamlit as st

from earthlab.ui import common, experiments, nav, provenance, scenarios, story_view
from earthlab.ui.story_view import Opened, section
from earthlab.ui.workspace_tabs import (
    tab_data,
    tab_investigate,
    tab_runs,
    tab_verifier,
    tab_wildfire,
)

TAB_NAMES = ["Recorded runs", "Wildfire case", "Verifier", "Data"]
TEAM_LABEL = f"replay/{scenarios.TEAM_RUN}"


def _decision(opened: Opened) -> None:
    story = opened.story
    gate = provenance.human_gate(opened.run_dir, opened.entry)
    with st.container(border=True):
        st.markdown(f"**Engineering decision: {story.decision}**")
        st.write(story.why)
        st.caption(f"{gate.state}. {gate.detail}")


def _story(opened: Opened) -> None:
    story = opened.story
    st.subheader(story.title)
    story_view.badges(opened)
    section("Scientific question")
    st.write(story.question)
    section("Chosen method")
    st.write(story.method)
    section("Evidence")
    st.markdown("\n".join(f"- {line}" for line in story.evidence))
    section("Comparison")
    story_view.tiles(story.tiles)
    if story.charts:
        for column, chart in zip(st.columns(len(story.charts)), story.charts, strict=True):
            with column:
                story_view.bars(chart)
    else:
        st.caption(story.rows_title)
        story_view.table(story.rows)
    section("Decision")
    _decision(opened)
    section("Limitations")
    st.markdown("\n".join(f"- {line}" for line in story.limits))
    section("What is real here")
    story_view.table(provenance.evidence_ladder(opened.run_dir, opened.entry, opened.entries))
    story_view.identity(opened)
    if story.key != "M1":
        section("Where the Meta model ran")
        st.write(
            "This scenario's page is built from recorded engineering evidence. For a recorded "
            "run where Muse Glimmer proposed the steps, open the Muse team run."
        )
        st.button("Open the recorded Muse team run", on_click=nav.go, args=(TEAM_LABEL,))


def _other_run(label: str) -> None:
    """A run that is not one of the scenarios: its request panel, for a local operator."""
    st.caption(f"Selected run: {label}. Open it under Recorded runs below.")
    experiments.request_panel()


def _advanced() -> None:
    operator = common.ui_mode() == "operator"
    with st.expander("Advanced: other recorded runs and checking tools", expanded=operator):
        names = ["Live investigation", *TAB_NAMES] if operator else TAB_NAMES
        draws = (tab_runs, tab_wildfire, tab_verifier, tab_data)
        renders = (tab_investigate, *draws) if operator else draws
        for tab, draw in zip(st.tabs(names), renders, strict=True):
            with tab:
                draw()


def render(label: str | None) -> None:
    st.caption("What was asked, what was done, and what the evidence supports.")
    opened = story_view.open_story(label) if label else None
    if opened is not None:
        _story(opened)
    elif label is None:
        st.info("No recorded runs are available.")
    elif scenarios.key_of(label) is None:
        _other_run(label)
    _advanced()

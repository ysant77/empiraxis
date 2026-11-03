"""Shared pieces of a scenario page: opening it safely, tiles, charts and its identity line."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import altair as alt
import streamlit as st

from earthlab.events.adapter import RunEvents
from earthlab.trace import RunTrace
from earthlab.ui import common, scenarios, theme
from earthlab.ui.scenarios import Bars, Story, Tile

VALIDATION_SCORED = ("S1", "S2", "M1", "M2")
ROW_HEIGHT = 32
AXIS_ROOM = 56


@dataclass(frozen=True)
class Opened:
    story: Story
    run_dir: Path
    events: RunEvents
    entries: list[dict[str, Any]]
    entry: dict[str, Any]


def open_story(label: str) -> Opened | None:
    """A scenario after its checks. Any doubt shows the reason and no value."""
    key = scenarios.key_of(label)
    if key is None:
        return None
    run_dir, events, error = common.open_run(label, None)
    if run_dir is None or events is None:
        st.error(f"Scenario not shown. Integrity check failed: {error}")
        return None
    try:
        story = scenarios.story(key, run_dir)
    except (KeyError, IndexError, TypeError, ValueError, OSError) as exc:
        st.error(f"Scenario not shown. A required value is missing: {type(exc).__name__}: {exc}")
        return None
    entries = list(RunTrace(run_dir / "trace.jsonl").records())
    return Opened(story, run_dir, events, entries, common.replay_entry(story.run))


def identity(opened: Opened) -> None:
    """The same line on every surface: one run, one trace head, one result digest."""
    entry = opened.entry
    st.caption(
        f"Scenario {opened.story.key} · run {opened.story.run} · "
        f"trace head {opened.events.trace_head[:16]} · "
        f"result.json {str(entry['result_sha256'])[:16]}"
    )


def badges(opened: Opened) -> None:
    entry = opened.entry
    science = scenarios.SCIENCE_LABELS.get(str(entry.get("science_label")))
    with st.container(horizontal=True, gap="small"):
        st.badge("Recorded replay", color="gray")
        if science:
            st.badge(science, color="gray")
        if opened.story.key in VALIDATION_SCORED:
            st.badge("Scored on validation only", color="gray")


def tiles(items: list[Tile]) -> None:
    with st.container(horizontal=True, gap="small"):
        for tile in items:
            st.metric(
                tile.label, tile.value, delta=tile.note or None,
                delta_color="off", border=True, width="stretch",
            )  # fmt: skip


def bars(chart: Bars) -> None:
    frame = [{"model": n, "value": v} for n, v in chart.bars]
    title = alt.Title(chart.title, anchor="start", fontSize=13)
    base = alt.Chart(alt.InlineData(values=frame), title=title).encode(
        y=alt.Y("model:N", sort=None, title=None,
                axis=alt.Axis(ticks=False, domain=False, labelLimit=150)),
        x=alt.X("value:Q", title=chart.axis, axis=alt.Axis(tickCount=4, grid=True)),
        tooltip=[alt.Tooltip("model:N", title="Model"),
                 alt.Tooltip("value:Q", title=chart.axis, format=".3f")],
    )  # fmt: skip
    marks = base.mark_bar(cornerRadiusEnd=4, size=14).encode(
        color=alt.condition(
            alt.datum.model == chart.highlight, alt.value(theme.BAR), alt.value(theme.MUTED_BAR)
        )
    )
    labels = base.mark_text(align="left", dx=4, fontSize=11, color="#47535c").encode(
        text=alt.Text("value:Q", format=".3f")
    )
    height = ROW_HEIGHT * len(chart.bars) + AXIS_ROOM
    st.altair_chart(
        (marks + labels).properties(height=height), width="stretch",
        alt=f"{chart.title}. " + ", ".join(f"{n} {v:.3f}" for n, v in chart.bars),
    )  # fmt: skip


def table(rows: list[dict[str, Any]]) -> None:
    st.table(rows, hide_index=True)


def section(title: str) -> None:
    st.markdown(f"##### {title}")


def raw_json(name: str, data: dict[str, Any]) -> None:
    st.code(json.dumps(data, indent=2, default=str)[:6000], language="json")
    st.caption(name)

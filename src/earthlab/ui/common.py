"""Shared UI state: run mode, audience, paths, cached resources and status-labelled panels.

Replay mode is the default. It reads recorded artifacts only and makes no model call.
Operator mode is for a local machine and enables the live investigation tab.
"""

from __future__ import annotations

import os
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import streamlit as st

from earthlab.board.store import BOARD_FILE, Board
from earthlab.events.adapter import RunEvents, load_run
from earthlab.events.contract import Visibility
from earthlab.events.manifest import ManifestError, listed_runs, read_manifest, verified_run
from earthlab.metrics import EarthlabMetrics
from earthlab.runtime import Workspace, open_workspace
from earthlab.trace import TraceIntegrityError

DATA_DIR = Path("data/nea")
RUNS_DIR = Path("runs")
REPLAY_DIR = Path(os.environ.get("EARTHLAB_REPLAY_DIR", "examples/replay"))
PROVIDERS = Path("config/providers.yaml")
METRICS_PORT = int(os.environ.get("EARTHLAB_METRICS_PORT", "9464"))
Status = Literal["implemented", "experimental", "planned", "unavailable"]
SHARED_RUN = "shared_run"
REPLAY_NOTE = "Replay mode: recorded artifacts only. No model is called."
MAP_CAPTION = (
    "Map source: NASA MODIS MCD64A1 v061 monthly burned area, 500 m pixels, after the "
    "selected QA policy. FIRMS MODIS hotspots are context only, not burned area. Axes: "
    "longitude and latitude in degrees (WGS84). Area unit: hectares (ha)."
)
PM25_CAPTION = (
    "Chart source: NEA historical 1-hr PM2.5 (data.gov.sg). Unit: ug/m3. Values are for "
    "NEA reporting regions, not point stations."
)


def ui_mode() -> Literal["replay", "operator"]:
    """Replay unless the local operator sets EARTHLAB_UI_MODE=operator."""
    return "operator" if os.environ.get("EARTHLAB_UI_MODE") == "operator" else "replay"


def audience() -> Visibility:
    """The public replay sees public events only. A local operator also sees reviewer ones."""
    if ui_mode() == "operator":
        return Visibility.AUTHENTICATED_REVIEWER
    return Visibility.PUBLIC_DEMO


def board() -> Board | None:
    """The shared run index. Replay mode never opens it: replay is strictly read-only."""
    return Board(RUNS_DIR / BOARD_FILE) if ui_mode() == "operator" else None


@st.cache_resource
def workspace() -> Workspace:
    return open_workspace(DATA_DIR)


@st.cache_resource
def metrics() -> EarthlabMetrics:
    shared = EarthlabMetrics()
    shared.serve(METRICS_PORT)
    return shared


def record_verification(check: str, verdict: str) -> None:
    """Only operator mode serves Prometheus metrics; replay starts no server."""
    if ui_mode() == "operator":
        metrics().record_verification(check, verdict)


def status_text(status: Status, note: str = "") -> str:
    return f"Status: {status}" + (f". {note}" if note else "")


@contextmanager
def panel(title: str, status: Status, note: str = "") -> Iterator[Any]:
    """A bordered panel whose first line states its status in words."""
    with st.container(border=True) as box:
        st.markdown(f"#### {title}")
        st.caption(status_text(status, note))
        yield box


def columns(count: int) -> Sequence[Any]:
    """Side-by-side columns, or one stacked column in the single-column (phone) layout."""
    if st.session_state.get("compact", False):
        return [st.container() for _ in range(count)]
    return list(st.columns(count))


def header(surface: str, purpose: str) -> None:
    st.header(surface)
    st.write(purpose)
    now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    access = "read-only replay" if ui_mode() == "replay" else "local operator (not public)"
    st.caption(f"{now} · Access: {access} · Audience: {audience().value}")


def replay_names() -> list[str]:
    try:
        return [str(r["run"]) for r in listed_runs(REPLAY_DIR)]
    except ManifestError:
        return []


def replay_entry(name: str) -> dict[str, Any]:
    return next((r for r in listed_runs(REPLAY_DIR) if r["run"] == name), {})


def load_replay(name: str) -> tuple[Path | None, RunEvents | None, str | None]:
    """Return (run folder, events, None) or (None, None, reason). Any doubt fails closed."""
    try:
        run_dir = verified_run(REPLAY_DIR, name)
        return run_dir, load_run(run_dir), None
    except (ManifestError, TraceIntegrityError, RuntimeError) as exc:
        return None, None, f"{type(exc).__name__}: {exc}"


def run_choices() -> list[tuple[str, Path | None]]:
    """Operator runs first, newest first, then replay runs, then other saved local runs."""
    shared = board()
    choices: list[tuple[str, Path | None]] = []
    if shared is not None:
        choices += [(e.run_id, RUNS_DIR / e.run_id) for e in shared.recent()]
    known = {label for label, _ in choices}
    choices += [(f"replay/{n}", None) for n in replay_names()]
    if ui_mode() == "operator" and RUNS_DIR.is_dir():
        found = sorted(RUNS_DIR.rglob("result.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        saved = [(str(p.parent.relative_to(RUNS_DIR)), p.parent) for p in found[:200]]
        choices += [item for item in saved if item[0] not in known]
    return choices


def pick_run() -> tuple[str, Path | None] | None:
    """The run named in the URL, shared by every surface and any browser session."""
    choices = run_choices()
    if not choices:
        return None
    labels = [label for label, _ in choices]
    shared = st.query_params.get("run") or st.session_state.get(SHARED_RUN)
    index = labels.index(shared) if shared in labels else 0
    picked: str = st.selectbox("Recorded run", labels, index=index)
    st.session_state[SHARED_RUN] = picked
    st.query_params["run"] = picked
    return picked, dict(choices)[picked]


def open_run(label: str, local: Path | None) -> tuple[Path | None, RunEvents | None, str | None]:
    """A replay copy through its allowlist, or a saved local run. Any doubt fails closed."""
    if local is None:
        return load_replay(label.removeprefix("replay/"))
    try:
        return local, load_run(local), None
    except (TraceIntegrityError, RuntimeError, OSError, KeyError, ValueError) as exc:
        return None, None, f"{type(exc).__name__}: {exc}"


def run_provenance(local: Path | None) -> str:
    if local is not None:
        return "Local saved run, read from its own hash-chained trace. It is not a redacted copy."
    return replay_provenance()


def replay_provenance() -> str:
    """The replay folder's own provenance note, so a view never overstates what ran."""
    try:
        return str(read_manifest(REPLAY_DIR).get("note", ""))
    except ManifestError:
        return ""


def replay_notice() -> None:
    if ui_mode() == "replay":
        st.info(REPLAY_NOTE)

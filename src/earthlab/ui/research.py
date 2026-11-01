"""EarthLab Research Workspace: the researcher-facing product surface.

It keeps every working product tab. The product assistant role, wind-linked haze and the
challenge workflow are not implemented, so their controls are shown disabled.
"""

from __future__ import annotations

import streamlit as st

from earthlab.cases.models import ScientificCase
from earthlab.ui import common
from earthlab.ui.workspace_tabs import (
    tab_data,
    tab_investigate,
    tab_runs,
    tab_verifier,
    tab_wildfire,
)

DATASETS = {
    "Kalimantan 2015 fire / burned area": "kalimantan-2015-burned-area",
    "Singapore 2015 haze observations": "nea-2015-haze",
}
PROMPTS = {
    "kalimantan-2015-burned-area": [
        "How many hectares were mapped as burned in the study box in September 2015?",
        "How many hectares were mapped as burned in October 2015, after quality checks?",
        "How sensitive is the September area to the QA policy?",
    ],
    "nea-2015-haze": [
        "Which NEA region recorded the highest hourly PM2.5 in September-October 2015?",
        "How many hours was the west region above 200 ug/m3?",
    ],
}
CAPABILITIES = [
    ("NEA PM2.5 historical tools", "implemented"),
    ("Kalimantan burned-area case", "implemented"),
    ("Independent verification", "implemented"),
    ("Plan critique (deterministic code)", "implemented"),
    ("Haze H1 wind-transport plausibility", "backend implemented (CLI), not in this UI"),
    ("Product manager to engineer workflow", "experimental; local live runs, operator mode"),
    ("Implementation workers", "planned"),
]
TAB_NAMES = ["Investigate", "Wildfire case", "Saved runs", "Verifier", "Data", "Challenge"]


def _study(case: ScientificCase) -> None:
    area = case.area
    if area.bbox is not None:
        box = area.bbox
        where = (
            f"{area.name}: lon {box.min_lon} to {box.max_lon}, lat {box.min_lat} to "
            f"{box.max_lat} (EPSG:4326)"
        )
    else:
        names = ", ".join(r.value for r in area.regions)
        where = f"{area.name}: {names}. These are reporting regions, not point stations."
    st.write(f"**Study area.** {where}")
    st.write(
        f"**Data period.** {case.period.start:%Y-%m-%d} to {case.period.end:%Y-%m-%d} "
        f"(end excluded); local zone {case.period.local_zone}."
    )
    if case.notes:
        st.write(f"**Note.** {case.notes}")


def start_panel() -> None:
    with common.panel("Investigation start", "implemented", "Two datasets have pinned data."):
        label = st.radio("Dataset", list(DATASETS), horizontal=True)
        case_id = DATASETS[label]
        st.checkbox(
            "Wind-transport plausibility (H1 backend exists as a CLI; not in this UI)",
            disabled=True,
        )
        st.selectbox("Example research question", PROMPTS[case_id])
        library = common.workspace().cases
        if library is not None and case_id in library.ids():
            _study(library.get(case_id).case)
        st.caption(
            "Observed data, statistical association, transport plausibility and forecasts are "
            "different claims. This product reports observed data and verified computations "
            "only. It makes no forecast and no causal attribution."
        )


def assistant_panel() -> None:
    with common.panel(
        "Product assistant", "planned", "No assistant conversation is recorded or shown."
    ):
        st.write(
            "A product assistant will take a research request, ask clarifying questions and "
            "report results. It will not approve its own actions or publish."
        )
        st.text_input("Message to the product assistant", disabled=True)
        st.button("Send to assistant", disabled=True)


def capabilities_panel() -> None:
    with common.panel("Evidence and scientific limitations", "implemented"):
        st.table([{"capability": name, "status": status} for name, status in CAPABILITIES])
        st.caption(
            "Do not infer a fire source from PM2.5 alone. A time match is a temporal "
            "association, not a cause."
        )


def tab_challenge() -> None:
    st.caption(common.status_text("planned", "The challenge workflow is not implemented."))
    st.write(
        "A researcher will be able to request a review or offer counter-evidence on a run. "
        "Cross-run learning is not implemented."
    )
    st.text_area("Counter-evidence or review request", disabled=True)
    st.button("Submit challenge", disabled=True)


def render() -> None:
    common.header(
        "EarthLab Research Workspace",
        "Ask a question, inspect the study area, the evidence and the verified findings.",
    )
    common.replay_notice()
    left, right = common.columns(2)
    with left:
        start_panel()
    with right:
        assistant_panel()
        capabilities_panel()
    renders = (tab_investigate, tab_wildfire, tab_runs, tab_verifier, tab_data, tab_challenge)
    for tab, draw in zip(st.tabs(TAB_NAMES), renders, strict=True):
        with tab:
            draw()

"""The one small stylesheet of the app. Colour lives in .streamlit/config.toml."""

from __future__ import annotations

import streamlit as st

BAR = "#0f5c6e"
MUTED_BAR = "#b4bec5"
CSS = """
<style>
.block-container {max-width: 1080px; padding-top: 2.5rem; padding-bottom: 4rem;}
h1 {font-size: 1.9rem !important; padding-bottom: 0 !important;}
h2 {font-size: 1.45rem !important;}
h5 {font-size: 0.95rem !important; color: #47535c; margin-top: 0.9rem;}
[data-testid="stMetric"] {min-width: 150px; flex: 1 1 150px;}
[data-testid="stMetricLabel"] p {white-space: normal; font-size: 0.82rem; color: #47535c;}
[data-testid="stMetricValue"] {font-size: 1.4rem; font-variant-numeric: tabular-nums;}
[data-testid="stMetricValue"] > div {white-space: normal; overflow-wrap: anywhere;}
[data-testid="stMetricDelta"] > div {white-space: normal;}
[data-testid="stMetricDelta"] {font-size: 0.78rem;}
[data-testid="stMetricDelta"] svg {display: none;}
table[data-testid="stTableStyledTable"] {width: 100%;}
table[data-testid="stTableStyledTable"] td, table[data-testid="stTableStyledTable"] th,
table[data-testid="stTableStyledTable"] td *, table[data-testid="stTableStyledTable"] th * {
  overflow-wrap: anywhere; white-space: normal;
}
@media (max-width: 640px) {
  .block-container {padding: 1.5rem 1rem 3rem 1rem;}
  table[data-testid="stTableStyledTable"] {table-layout: fixed; font-size: 0.75rem;}
  table[data-testid="stTableStyledTable"] td, table[data-testid="stTableStyledTable"] th {
    padding: 0.3rem 0.35rem;
  }
}
</style>
"""


def apply() -> None:
    st.html(CSS)

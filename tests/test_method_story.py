"""M3 page: numbers come from the redacted replay; the run names its neural model."""

from __future__ import annotations

from pathlib import Path

from earthlab.ui import scenarios

RUN = (
    Path(__file__).resolve().parents[1] / "examples" / "replay" / "scenario-muse-method-comparison"
)


def test_the_m3_story_names_the_trained_tcn_and_both_reload_checks() -> None:
    story = scenarios.story("M3", RUN)
    assert scenarios.key_of(f"replay/{story.run}") == "M3"
    names = [row["Model"] for row in story.rows]
    assert "TCN (compact neural)" in names and "Tuned ridge (rolling-origin)" in names
    assert "GRU" not in " ".join(names)
    assert any("TCN reload difference 0.0" in line for line in story.evidence)
    assert story.decision == "Keep the baseline: Lagged ridge"

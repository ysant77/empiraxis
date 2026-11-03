from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[1] / "src" / "earthlab" / "ui" / "app.py"


def test_app_renders_and_verifier_tab_rejects_a_false_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EARTHLAB_METRICS_PORT", "0")
    monkeypatch.chdir(APP.parents[3])
    app = AppTest.from_file(str(APP), default_timeout=60).run()
    assert not app.exception
    assert app.title[0].value == "Empiraxis"
    region = next(s for s in app.selectbox if s.label == "Region")
    region.set_value("central").run()
    next(b for b in app.button if b.label == "Verify claim").click().run()
    assert not app.exception
    assert any("contradicted" in str(j.value) for j in app.json)


def test_wildfire_tab_shows_the_verified_area_and_checks_a_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("EARTHLAB_METRICS_PORT", "0")
    monkeypatch.chdir(APP.parents[3])
    app = AppTest.from_file(str(APP), default_timeout=120).run()
    assert not app.exception
    metrics = {m.label: m.value for m in app.metric}
    assert metrics["Mapped burned area (ha)"] == "77,426.0"  # September, primary policy
    assert metrics["Verifier checks"] == "pass" and metrics["Reporting gate"] == "pass"
    next(n for n in app.number_input if n.label == "Claimed area (ha)").set_value(77426.0).run()
    next(b for b in app.button if b.label == "Check area claim").click().run()
    assert any("supported" in str(j.value) for j in app.json)
    month = next(s for s in app.selectbox if s.label == "Month (UTC)")
    month.set_value("2015-10").run()
    metrics = {m.label: m.value for m in app.metric}
    assert metrics["Mapped burned area (ha)"] == "not reported (gate)"
    assert metrics["Reporting gate"] == "fail"

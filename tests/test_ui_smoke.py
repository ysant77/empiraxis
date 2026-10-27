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
    assert app.title[0].value == "Axiom EarthLab"
    region = next(s for s in app.selectbox if s.label == "Region")
    region.set_value("central").run()
    next(b for b in app.button if b.label == "Verify claim").click().run()
    assert not app.exception
    assert any("contradicted" in str(j.value) for j in app.json)

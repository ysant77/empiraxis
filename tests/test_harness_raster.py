"""Scenario C: method selection on the real pinned rasters."""

from __future__ import annotations

from pathlib import Path

import pytest
from fake_client import ScriptedClient, call

from earthlab.harness.scenarios import run_scenario

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _at_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(ROOT)


def test_the_deterministic_path_reports_september_and_refuses_october(tmp_path: Path) -> None:
    done = run_scenario("burned-area-method", "fixed", tmp_path / "run", None)
    assert done["recommendation"]["outcome"] == "adopt_limited"
    rows = {row["model"]: row for row in done["comparison"]}
    september, october = rows["raster_deterministic:2015-09"], rows["raster_deterministic:2015-10"]
    assert september["passes"] and september["area_ha"] == pytest.approx(77426.0, abs=0.5)
    assert not october["passes"] and october["area_ha"] is None
    assert any("2015-10" in text for text in done["limitations"])
    assert all(done["acceptance"].values())


def test_segmentation_ends_in_a_resource_request_with_no_score(tmp_path: Path) -> None:
    done = run_scenario("burned-area-segmentation", "fixed", tmp_path / "run", None)
    assert done["recommendation"]["outcome"] == "request_resource"
    assert done["recommendation"]["model_id"] is None
    row = next(r for r in done["comparison"] if r["model"] == "segmentation_pretrained")
    assert not row["passes"] and "iou" not in row and "area_ha" not in row
    assert done["acceptance"]["no_segmentation_score"]


def test_a_lead_that_picks_segmentation_cannot_adopt_it(tmp_path: Path) -> None:
    client = ScriptedClient(
        [
            call("review_scope", in_scope=True, note="Within the problem."),
            call("choose_method", method="segmentation_pretrained", reason="It is newer."),
            call("prepare_data"),
            call("submit_note", note="Checked."),
            call("train_models"),
            call("submit_note", note="Not run."),
            call("review_results", action="finish", reason="The inputs do not fit."),
            call("recommend", outcome="adopt_limited", model_id="segmentation_pretrained",
                 reason="It is a strong model."),
            call("recommend", outcome="request_resource", reason="The imagery is missing."),
            call("forward_decision", forward_to_human=True, note="Within the criteria."),
        ]
    )  # fmt: skip
    done = run_scenario("burned-area-method", "team", tmp_path / "run", client)
    assert done["status"] == "awaiting_human"
    assert done["recommendation"]["outcome"] == "request_resource"

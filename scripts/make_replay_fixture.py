"""Write the offline replay fixture under examples/replay/.

The two runs use the scripted test client, not a Meta model. They record the real tool,
verifier and safety path on the pinned Kalimantan 2015 data: September passes the reporting
gate, October fails it. The fixture holds visible development questions only.

Run with:  uv run python scripts/make_replay_fixture.py
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from fake_client import FAKE_CONFIG, ScriptedClient, Step, call, say  # noqa: E402

from earthlab.bench.scenarios import load_scenarios  # noqa: E402
from earthlab.events.manifest import write_manifest  # noqa: E402
from earthlab.llm.types import ChatResponse  # noqa: E402
from earthlab.report.write import write_report  # noqa: E402
from earthlab.runtime import investigate, open_workspace  # noqa: E402

OUT = ROOT / "examples" / "replay"
NEA = ROOT / "data" / "nea"
CASE = "kalimantan-2015-burned-area"
SEPTEMBER = {
    "case_id": CASE,
    "month": "2015-09",
    "quantity": "burned_area_ha",
    "value": 77426.0,
    "statement": "Mapped burned area after quality checks.",
}
# The fixture names its client plainly, so no view can mistake it for a Muse run.
FIXTURE_CONFIG = FAKE_CONFIG.model_copy(
    update={"name": "scripted-fixture", "model": "scripted-test-client", "logical_model": "none"}
)


class FixtureClient(ScriptedClient):
    """The scripted client, reporting its own name as the served model."""

    def chat(self, *args: Any, **kwargs: Any) -> ChatResponse:
        resp = super().chat(*args, **kwargs)
        return resp.model_copy(update={"served_model": FIXTURE_CONFIG.model})


NOTE = (
    "Recorded with the scripted test client (no Meta model call). The tools, verifier and "
    "safety gate ran on the pinned data. Use it to demonstrate replay, not model quality."
)


def september() -> list[Step]:
    return [
        call("burned_area_summary", case_id=CASE, month="2015-09"),
        call("submit_area_findings", claims=[SEPTEMBER]),
        say("The verified mapped burned area for the study box is in A1.1."),
    ]


def october() -> list[Step]:
    return [
        call("burned_area_summary", case_id=CASE, month="2015-10"),
        call(
            "declare_limitation",
            reasons=["insufficient_valid_data"],
            explanation="Too little valid land data in the requested month.",
        ),
        say("The requested month fails the valid-data gate, so no area is reported."),
    ]


RUNS: dict[str, tuple[str, Any]] = {
    "sb05-september": ("SB-05", september),
    "sb05b-october": ("SB-05b", october),
}


def main() -> int:
    questions = {s.id: s.question for s in load_scenarios(ROOT / "evals/sciencebench_dev_v1.yaml")}
    shutil.rmtree(OUT, ignore_errors=True)
    workspace = open_workspace(NEA)
    entries: list[dict[str, Any]] = []
    for name, (scenario_id, steps) in RUNS.items():
        run_dir = OUT / name
        client = FixtureClient(steps(), FIXTURE_CONFIG)
        investigate(questions[scenario_id], client, workspace, run_dir)
        write_report(run_dir, NEA)
        entries.append({"run": name, "scenario_id": scenario_id, "split": "development"})
    write_manifest(OUT, entries, note=NOTE)
    print(json.dumps(entries, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

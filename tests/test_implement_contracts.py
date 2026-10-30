"""Implementor task, result, review and acceptance contracts; the static patch screen."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from earthlab.implement.bindings import load_bindings
from earthlab.implement.contracts import (
    ExecutionResultV1,
    HumanPatchDecision,
    ImplementationResultV1,
    ImplementationTaskV1,
    ReviewFindingV1,
    RunnerTestOutcome,
    acceptance,
    sha256_text,
)
from earthlab.implement.screen import screen_patch

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = "0" * 64

GOOD_PATCH = """diff --git a/src/earthlab/haze/wind.py b/src/earthlab/haze/wind.py
index 1111111..2222222 100644
--- a/src/earthlab/haze/wind.py
+++ b/src/earthlab/haze/wind.py
@@ -1,3 +1,4 @@
 import math
+DOWNWIND_OFFSET_DEG = 180.0
 def f():
     return 1
"""


def task(**overrides: Any) -> ImplementationTaskV1:
    base: dict[str, Any] = {
        "task_id": "wind-uv-001",
        "parent_task_id": "haze-001",
        "task_kind": "code_patch",
        "method_ref": "wind-vector-geometry",
        "allowed_paths": ["src/earthlab/haze/wind.py"],
        "requirements": ["Convert wind-from direction to downwind bearing"],
        "fixed_tests": ["tests/test_haze_wind_fixed.py"],
        "data_classification": "synthetic_development",
    }
    return ImplementationTaskV1.model_validate({**base, **overrides})


def result(
    patch: str = GOOD_PATCH, family: str = "qwen", **overrides: Any
) -> ImplementationResultV1:
    base: dict[str, Any] = {
        "task_id": "wind-uv-001",
        "worker": {
            "worker_id": f"{family}-worker",
            "model_family": family,
            "model_id": "some/model",
            "provider_id": "local-test",
        },
        "status": "proposed",
        "patch_diff": patch,
        "artifact_sha256": sha256_text(patch),
        "usage": {"model_calls": 1, "wall_seconds": 3.0},
    }
    return ImplementationResultV1.model_validate({**base, **overrides})


def run(res: ImplementationResultV1, outcome: str = "passed", exit_code: int = 0) -> Any:
    return ExecutionResultV1(
        task_id=res.task_id,
        artifact_sha256=res.artifact_sha256,
        runner_id="sandbox-v0",
        command_id="pytest_fixed",
        exit_code=exit_code,
        timed_out=False,
        tests=(
            RunnerTestOutcome(test_id="tests/test_haze_wind_fixed.py::test_north", outcome=outcome),
        ),
        input_manifest_sha256=MANIFEST,
        wall_seconds=4.0,
        hardware="test",
    )


def human(res: ImplementationResultV1, decision: str = "accept") -> HumanPatchDecision:
    return HumanPatchDecision.model_validate(
        {
            "task_id": res.task_id,
            "artifact_sha256": res.artifact_sha256,
            "decision": decision,
            "approver": "director",
        }
    )


@pytest.mark.parametrize(
    "paths",
    [
        ["../outside.py"],
        ["/etc/passwd"],
        ["src/earthlab/../../x.py"],
        ["evals/heldout_v1.lock.yaml"],
        ["config/approvals/haze-2015-h1.yaml"],
        ["data/nea/manifest.json"],
        [".github/workflows/ci.yml"],
        ["pyproject.toml"],
        ["src\\earthlab\\x.py"],
    ],
)
def test_tasks_cannot_open_paths_outside_source_and_tests(paths: list[str]) -> None:
    with pytest.raises(ValidationError):
        task(allowed_paths=paths)


def test_a_worker_cannot_edit_its_own_acceptance_tests() -> None:
    with pytest.raises(ValidationError, match="own acceptance tests"):
        task(allowed_paths=["src/earthlab/haze/wind.py", "tests/test_haze_wind_fixed.py"])


def test_every_permission_is_fixed_off() -> None:
    with pytest.raises(ValidationError):
        task(permissions={"run_shell": True})
    assert not any(task().permissions.model_dump().values())


def test_a_result_cannot_claim_it_passed_or_misstate_its_hash() -> None:
    with pytest.raises(ValidationError):
        result(passed=True)
    with pytest.raises(ValidationError, match="does not match"):
        result(artifact_sha256="a" * 64)


def test_the_screen_passes_a_scoped_patch() -> None:
    assert screen_patch(task(), result()) == ()


@pytest.mark.parametrize(
    ("patch", "check"),
    [
        (GOOD_PATCH.replace("haze/wind.py", "haze/h1.py"), "path_not_allowed"),
        (GOOD_PATCH.replace("+DOWNWIND", "+import subprocess\n+DOWNWIND"), "shell"),
        (GOOD_PATCH.replace("+DOWNWIND", "+import urllib.request\n+DOWNWIND"), "network"),
        (GOOD_PATCH.replace("+DOWNWIND", "+eval('1')\n+DOWNWIND"), "dynamic_code"),
        (GOOD_PATCH.replace("+DOWNWIND", "+import pickle\n+DOWNWIND"), "unsafe_load"),
        (GOOD_PATCH.replace("+DOWNWIND", "+KEY = os.environ['K']\n+DOWNWIND"), "environment"),
        (GOOD_PATCH.replace("+DOWNWIND", "+pytest.skip('x')\n+DOWNWIND"), "test_bypass"),
        (
            GOOD_PATCH.replace("index 1111111", "old mode 100644\nnew mode 100755\nindex 1"),
            "mode_change",
        ),
        (GOOD_PATCH.replace("index 1111111..2222222 100644", "GIT binary patch"), "binary"),
        ("not a diff at all", "unreadable_patch"),
    ],
)
def test_the_screen_blocks_unsafe_patches(patch: str, check: str) -> None:
    findings = screen_patch(task(), result(patch))
    assert check in {f.check_id for f in findings}
    assert all(f.severity == "blocking" and f.reviewer_kind == "deterministic" for f in findings)


def test_the_screen_blocks_symlinks_and_test_configuration() -> None:
    link = (
        "diff --git a/src/earthlab/haze/wind.py b/src/earthlab/haze/wind.py\n"
        "new file mode 120000\n--- /dev/null\n+++ b/src/earthlab/haze/wind.py\n@@ -0,0 +1 @@\n"
        "+/etc/passwd\n"
    )
    assert "mode_change" in {f.check_id for f in screen_patch(task(), result(link))}
    conf = GOOD_PATCH.replace("src/earthlab/haze/wind.py", "tests/conftest.py")
    scoped = task(allowed_paths=["tests/conftest.py"])
    assert "test_config" in {f.check_id for f in screen_patch(scoped, result(conf))}


def test_acceptance_needs_screen_run_and_human_in_that_order() -> None:
    t, r = task(), result()
    assert acceptance(t, r).stage == "execution"
    assert acceptance(t, r, run=run(r, "failed", 1)).stage == "execution"
    assert acceptance(t, r, run=run(r)).stage == "human"
    assert acceptance(t, r, run=run(r), decision=human(r, "reject")).accepted is False
    assert acceptance(t, r, run=run(r), decision=human(r)).accepted is True


def test_a_run_or_approval_of_another_artifact_does_not_count() -> None:
    t, r = task(), result()
    other = result(GOOD_PATCH + " \n")
    assert acceptance(t, r, run=run(other), decision=human(r)).stage == "execution"
    assert acceptance(t, r, run=run(r), decision=human(other)).stage == "human"


def test_a_fixed_test_that_did_not_run_blocks_acceptance() -> None:
    t, r = task(fixed_tests=["tests/test_haze_wind_fixed.py", "tests/test_other.py"]), result()
    verdict = acceptance(t, r, run=run(r), decision=human(r))
    assert not verdict.accepted and "tests/test_other.py did not run" in verdict.reasons


def test_a_model_reviewer_can_block_but_the_rule_is_the_same_for_every_family() -> None:
    for family in ("meta-muse", "qwen", "gemma"):
        r = result(family=family)
        block = ReviewFindingV1(
            finding_id="wind-uv-001.review.1",
            reviewer_kind="model",
            reviewer_id="muse-glimmer",
            model_family="meta-muse",
            artifact_sha256=r.artifact_sha256,
            check_id="sign_convention",
            severity="blocking",
            message="Downwind bearing is not reduced modulo 360.",
        )
        assert acceptance(task(), r, (block,), run(r), human(r)).stage == "review"
        assert acceptance(task(), r, (), run(r), human(r)).accepted is True


def test_repository_bindings_load_and_only_glimmer_is_enabled() -> None:
    bindings = load_bindings(ROOT / "config" / "roles" / "bindings.yaml")
    assert [c.candidate_id for c in bindings.candidates if c.enabled] == ["muse-glimmer"]
    assert [c.candidate_id for c in bindings.ready("orchestrator")] == ["muse-glimmer"]
    assert bindings.ready("implementor") == ()
    with pytest.raises(PermissionError, match="planned for implementor"):
        bindings.bind("implementor", "qwen3-coder-30b-a3b")
    assert bindings.bind("orchestrator", "muse-glimmer").family == "meta-muse"


def _bindings(candidates: list[dict[str, Any]], **roles: Any) -> dict[str, Any]:
    policy = {
        "product_manager": {"families": ["meta-llama"], "status": "planned"},
        "implementor": {"families": ["meta-muse", "qwen"], "status": "planned"},
    }
    return {"schema_version": "1", "roles": {**policy, **roles}, "candidates": candidates}


def test_bindings_keep_supervision_on_meta_and_gate_enabling() -> None:
    from earthlab.implement.bindings import Bindings

    qwen = {"candidate_id": "q", "family": "qwen", "model_id": "q", "license": "x"}
    with pytest.raises(ValidationError, match="Meta families only"):
        Bindings.model_validate(
            _bindings([], product_manager={"families": ["qwen"], "status": "planned"})
        )
    with pytest.raises(ValidationError, match="cannot serve product_manager"):
        Bindings.model_validate(_bindings([{**qwen, "planned_roles": ["product_manager"]}]))
    with pytest.raises(ValidationError, match="licence"):
        Bindings.model_validate(_bindings([{**qwen, "enabled": True, "roles": ["implementor"]}]))
    with pytest.raises(ValidationError, match="preflight"):
        Bindings.model_validate(
            _bindings([{**qwen, "enabled": True, "license_checked": True, "provider_id": "p"}])
        )
    with pytest.raises(ValidationError, match="disabled candidate"):
        Bindings.model_validate(_bindings([{**qwen, "roles": ["implementor"]}]))
    ready = {
        **qwen,
        "enabled": True,
        "license_checked": True,
        "provider_id": "p",
        "roles": ["implementor"],
        "preflight": {
            "checked_on": "2026-10-30",
            "json_schema": "pass",
            "tool_call": "text_only",
            "served_model": "q",
        },
    }
    assert Bindings.model_validate(_bindings([ready])).bind("implementor", "q").family == "qwen"

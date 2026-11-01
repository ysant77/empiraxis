"""The implementor harness with scripted Meta and Qwen workers: same task, same checks.

These are synthetic tests of the harness, not measurements of any model.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from fake_client import FAKE_CONFIG, ScriptedClient, say

from earthlab.implement.bindings import BindingRefused, Bindings
from earthlab.implement.catalogue import TASKS, WORKSPACE
from earthlab.implement.harness import extract_diff, run_trial
from earthlab.llm.types import ChatResponse, ProviderError, ProviderErrorKind, Usage

ROOT = Path(__file__).resolve().parents[1]
SPEC = TASKS["dev-wind-vector"]
TARGET = f"{WORKSPACE}/wind.py"
GOOD_BODY = [
    "import math",
    "",
    "",
    "def wind_vector(from_deg, speed_ms):",
    "    if not (math.isfinite(from_deg) and math.isfinite(speed_ms)) or speed_ms < 0:",
    "        raise ValueError('bad input')",
    "    rad = math.radians(from_deg)",
    "    return -speed_ms * math.sin(rad), -speed_ms * math.cos(rad)",
    "",
    "",
    "def downwind_bearing(from_deg):",
    "    return (from_deg + 180.0) % 360.0",
]


def diff(body: list[str], path: str = TARGET) -> str:
    added = "\n".join(f"+{line}" for line in body)
    return (
        f"diff --git a/{path} b/{path}\nnew file mode 100644\n--- /dev/null\n+++ b/{path}\n"
        f"@@ -0,0 +1,{len(body)} @@\n{added}\n"
    )


def reply_text(body: list[str]) -> str:
    return f"Here is the patch.\n```diff\n{diff(body)}```\n"


def reply(patch: str) -> Any:
    return say(f"Here is the patch.\n```diff\n{patch}```\n")


def worker(family: str, model: str) -> tuple[ScriptedClient, Any]:
    config = FAKE_CONFIG.model_copy(update={"name": f"fake-{family}", "model": model})
    bindings = Bindings.model_validate(
        {
            "schema_version": "1",
            "roles": {"implementor": {"families": ["meta-muse", "qwen"], "status": "experimental"}},
            "candidates": [
                {
                    "candidate_id": f"fake-{family}", "family": family, "model_id": model,
                    "provider_id": config.name, "roles": ["implementor"], "license": "test",
                    "license_checked": True, "enabled": True,
                    "preflight": {"checked_on": "2026-10-31", "json_schema": "pass",
                                  "tool_call": "text_only", "served_model": model},
                }
            ],
        }
    )  # fmt: skip
    binding = bindings.bind_runtime(
        "implementor", f"fake-{family}", config, {config.name: config}, allow_experimental=True
    )
    return ScriptedClient([], config=config), binding


@pytest.mark.parametrize(
    ("family", "model"), [("meta-muse", "muse-glimmer-30B"), ("qwen", "qwen3-coder")]
)
def test_each_family_gets_the_same_task_and_the_same_screen(family: str, model: str) -> None:
    client, binding = worker(family, model)
    client._steps = [reply(diff(GOOD_BODY))]
    trial = run_trial(SPEC, client, binding)
    assert trial.status == "screened" and trial.findings == ()
    assert trial.worker.model_family == family and trial.worker.model_id == model
    assert trial.acceptance is not None and trial.acceptance.stage == "execution"
    assert trial.acceptance.reasons == ("no trusted run",)
    assert client.requests[0]["tools"] == [] and client.requests[0]["tool_choice"] == "none"
    assert "dev-wind-vector" in client.requests[0]["messages"][1]["content"]


def test_a_blocked_patch_gets_one_revision_then_stays_blocked() -> None:
    client, binding = worker("qwen", "qwen3-coder")
    bad = diff(["import subprocess", *GOOD_BODY])
    client._steps = [reply(bad), reply(bad)]
    trial = run_trial(SPEC, client, binding)
    assert trial.status == "blocked" and trial.model_calls == 2 and trial.revisions == 1
    assert {"shell", "import_not_allowed"} <= {f.check_id for f in trial.findings}
    assert trial.acceptance is not None and trial.acceptance.stage == "review"
    assert "screen blocked the patch" in client.requests[1]["messages"][-1]["content"]


def test_a_revision_that_fixes_the_patch_is_screened() -> None:
    client, binding = worker("meta-muse", "muse-glimmer-30B")
    client._steps = [
        reply(diff(GOOD_BODY, path="src/earthlab/haze/wind.py")),
        reply(diff(GOOD_BODY)),
    ]
    trial = run_trial(SPEC, client, binding)
    assert trial.status == "screened" and trial.revisions == 1


@pytest.mark.parametrize(
    ("body", "check"),
    [
        (["def f(:"], "syntax_error"),
        (["import os"], "import_not_allowed"),
        (["from pathlib import Path"], "import_not_allowed"),
        (["x = open('/etc/passwd').read()"], "filesystem"),
        (["import base64"], "obfuscation"),
        (["import threading"], "process"),
        (["globals()['x'] = 1"], "dynamic_code"),
        (["s = '" + "a" * 320 + "'"], "obfuscation"),
    ],
)
def test_the_screen_v1_rules(body: list[str], check: str) -> None:
    client, binding = worker("qwen", "qwen3-coder")
    client._steps = [reply(diff(body)), reply(diff(body))]
    assert check in {f.check_id for f in run_trial(SPEC, client, binding).findings}


def test_a_non_python_file_is_blocked() -> None:
    client, binding = worker("qwen", "qwen3-coder")
    patch = diff(["#!/bin/sh"], path=f"{WORKSPACE}/run.sh")
    client._steps = [reply(patch), reply(patch)]
    assert "file_type" in {f.check_id for f in run_trial(SPEC, client, binding).findings}


def test_the_harness_never_imports_or_writes_the_proposal() -> None:
    client, binding = worker("meta-muse", "muse-glimmer-30B")
    client._steps = [reply(diff([*GOOD_BODY, "RAN = True"]))]
    run_trial(SPEC, client, binding)
    assert not (ROOT / TARGET).exists()
    assert not any(name.startswith("earthlab.implement.workspace") for name in sys.modules)


def test_no_diff_is_a_decline_and_a_provider_error_is_recorded() -> None:
    client, binding = worker("qwen", "qwen3-coder")
    client._steps = [say("I cannot do this.")]
    assert run_trial(SPEC, client, binding).status == "declined"
    client._steps = [ProviderError(ProviderErrorKind.SERVER, "HTTP 500")]
    trial = run_trial(SPEC, client, binding)
    assert trial.status == "provider_error" and trial.error == "server"


def test_the_binding_must_be_an_implementor_for_this_client() -> None:
    client, binding = worker("qwen", "qwen3-coder")
    other, _ = worker("meta-muse", "muse-glimmer-30B")
    with pytest.raises(BindingRefused):
        run_trial(SPEC, other, binding)
    with pytest.raises(BindingRefused, match="not implementor"):
        run_trial(SPEC, client, binding.model_copy(update={"role": "orchestrator"}))


def test_repository_bindings_approve_no_implementor_yet() -> None:
    from earthlab.implement.bindings import load_bindings
    from earthlab.llm.providers import load_providers

    repo = load_bindings(ROOT / "config" / "roles" / "bindings.yaml")
    providers = load_providers(ROOT / "config" / "providers.yaml")
    for candidate in ("muse-glimmer", "qwen3-coder-30b-a3b", "gemma-3-4b-it"):
        blockers = repo.status("implementor", candidate, providers).blockers(True)
        assert "implementor is planned, not implemented" in blockers


def test_extract_diff_reads_only_a_fenced_block() -> None:
    assert extract_diff("no code here") == ""
    assert extract_diff("```diff\n+x\n```").startswith("+x")


def test_a_hunk_line_starting_with_plus_plus_is_still_screened() -> None:
    """Regression: the parser skipped added lines that begin "+++", which hid the valid
    Python line "++__import__('os').system('id')" from every rule."""
    client, binding = worker("qwen", "qwen3-coder")
    hidden = diff(["import math", "++__import__('os').system('id')"])
    client._steps = [reply(hidden), reply(hidden)]
    assert "dynamic_code" in {f.check_id for f in run_trial(SPEC, client, binding).findings}


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (f"+++ b/{TARGET}", "+++ b/src/earthlab/runtime.py"),
        ("--- /dev/null", "--- a/src/earthlab/runtime.py"),
    ],
)
def test_file_names_must_match_the_diff_header(old: str, new: str) -> None:
    """Regression: a header naming the allowed path with +++/--- naming another passed."""
    client, binding = worker("qwen", "qwen3-coder")
    patch = diff(GOOD_BODY).replace(old, new)
    client._steps = [reply(patch), reply(patch)]
    findings = run_trial(SPEC, client, binding).findings
    assert [f.check_id for f in findings] == ["unreadable_patch"]


def test_an_unknown_line_inside_a_hunk_is_unreadable() -> None:
    client, binding = worker("qwen", "qwen3-coder")
    patch = diff(GOOD_BODY) + "garbage outside the diff grammar\n"
    client._steps = [reply(patch), reply(patch)]
    assert [f.check_id for f in run_trial(SPEC, client, binding).findings] == ["unreadable_patch"]


def response(
    client: ScriptedClient,
    text: str = "",
    finish: str | None = "stop",
    tokens: int | None = 100,
    reasoning: str | None = None,
) -> ChatResponse:
    return ChatResponse(
        provider=client.config.name, model=client.config.model, served_model=client.config.model,
        request_id=None, content=text, reasoning=reasoning, tool_calls=(), finish_reason=finish,
        usage=Usage(prompt_tokens=10, completion_tokens=tokens), wall_seconds=1.0,
    )  # fmt: skip


class Replies(ScriptedClient):
    """Returns whole ChatResponse objects, to control how each reply ends."""

    def __init__(self, config: Any, replies: list[ChatResponse | ProviderError]):
        super().__init__([], config=config)
        self.replies = replies

    def chat(self, *args: Any, **kwargs: Any) -> ChatResponse:
        reply = self.replies.pop(0)
        if isinstance(reply, ProviderError):
            raise reply
        return reply


def trial_of(*steps: Any) -> Any:
    base, binding = worker("qwen", "qwen3-coder")
    client = Replies(base.config, [])
    client.replies = [s(client) if callable(s) else s for s in steps]
    return run_trial(SPEC, client, binding)


def test_a_token_stop_is_not_a_decline_and_reasoning_text_is_not_kept() -> None:
    trial = trial_of(
        lambda c: response(c, finish="length", tokens=4096, reasoning="private reasoning")
    )
    assert trial.status == "truncated" and trial.finish_reason == "length"
    assert trial.reasoning_chars == len("private reasoning")
    assert "private reasoning" not in trial.model_dump_json()


def test_a_real_decline_stays_a_decline() -> None:
    trial = trial_of(lambda c: response(c, "I cannot do this."))
    assert trial.status == "declined" and trial.finish_reason == "stop" and trial.error is None


@pytest.mark.parametrize("tokens", [0, None], ids=["zero", "not_reported"])
def test_an_empty_reply_is_a_provider_error(tokens: int | None) -> None:
    trial = trial_of(lambda c: response(c, tokens=tokens))
    assert trial.status == "provider_error" and trial.error == "malformed"
    assert trial.result is None and trial.proposals == () and trial.model_calls == 1


def test_a_reply_with_text_and_no_usage_report_is_not_a_fault() -> None:
    assert trial_of(lambda c: response(c, reply_text(GOOD_BODY), tokens=None)).status == "screened"


def test_a_revision_keeps_the_first_proposal() -> None:
    bad = reply_text(["import subprocess", *GOOD_BODY])
    trial = trial_of(lambda c: response(c, bad), lambda c: response(c, reply_text(GOOD_BODY)))
    assert trial.status == "screened" and len(trial.proposals) == 2
    assert "subprocess" in trial.proposals[0].patch_diff and trial.result == trial.proposals[1]


@pytest.mark.parametrize("finish", ["stop", "length"])
def test_a_revision_without_a_patch_leaves_the_block_standing(finish: str) -> None:
    bad = reply_text(["import subprocess", *GOOD_BODY])
    trial = trial_of(lambda c: response(c, bad), lambda c: response(c, finish=finish))
    assert trial.status == "blocked" and trial.findings and trial.revisions == 1
    assert [p.status for p in trial.proposals] == ["proposed"]
    assert trial.result == trial.proposals[0] and trial.acceptance is not None
    assert trial.acceptance.stage == "review"


@pytest.mark.parametrize(
    "fault",
    [ProviderError(ProviderErrorKind.SERVER, "HTTP 500"), None],
    ids=["raised", "empty_reply"],
)
def test_a_fault_on_the_revision_keeps_the_blocked_proposal(fault: Any) -> None:
    bad = reply_text(["import subprocess", *GOOD_BODY])
    second = fault or (lambda c: response(c, tokens=0))
    trial = trial_of(lambda c: response(c, bad), second)
    assert trial.status == "provider_error" and trial.revisions == 1 and trial.model_calls == 2
    assert len(trial.proposals) == 1 and trial.findings and trial.acceptance is None

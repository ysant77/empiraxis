from __future__ import annotations

from pathlib import Path

from earthlab.efficiency.__main__ import main
from earthlab.efficiency.prompt_models import PromptSpec, ToolDecl
from earthlab.efficiency.prompt_review import ENGINEER_TOOLS, default_specs, review_prompts

SRC = Path(__file__).resolve().parents[1] / "src"
GOOD_PM = (
    "You are the product manager of a research system.\n"
    "You do not answer, choose or approve. Do not add any number the request lacks.\n"
    "A period keeps the end excluded. Call submit_brief exactly once. Never guess.\n"
)


def _pm(text: str, **kw: object) -> PromptSpec:
    base: dict[str, object] = {
        "prompt_id": "t",
        "role": "product_manager",
        "text": text,
        "tools": (ToolDecl(name="submit_brief"),),
    }
    return PromptSpec.model_validate(base | kw)


def _rules(spec: PromptSpec, *more: PromptSpec) -> set[str]:
    return {f.rule for f in review_prompts((spec, *more)).findings}


def test_clean_prompt_has_no_errors() -> None:
    review = review_prompts((_pm(GOOD_PM),))
    assert [f for f in review.findings if f.severity == "error"] == []


def test_role_mismatch_and_missing_role() -> None:
    assert "R001" in _rules(_pm(GOOD_PM.replace("product manager", "orchestrator")))
    assert "R001" in _rules(_pm("Do the work."))


def test_unknown_and_unused_tools() -> None:
    found = review_prompts((_pm(GOOD_PM + "Then call submit_verdict.\n"),)).findings
    assert any(f.rule == "R002" and f.evidence == "submit_verdict" for f in found)
    unused = review_prompts((_pm(GOOD_PM, tools=(ToolDecl(name="rank_regions"),)),)).findings
    assert any(f.rule == "R002" and f.severity == "info" for f in unused)


def test_missing_scientific_constraints() -> None:
    found = review_prompts((_pm("You are the product manager."),)).findings
    keys = {f.evidence for f in found if f.rule == "R003"}
    assert keys == {"no_invented_values", "period_end_excluded", "no_self_decision"}


def test_report_prompt_needs_finding_ids() -> None:
    spec = PromptSpec(
        prompt_id="r",
        role="product_manager",
        kind="report",
        text="You are the product manager. Write a report on the finding results.",
    )
    assert "R004" in _rules(spec)
    assert {f.evidence for f in review_prompts((spec,)).findings if f.rule == "R003"} == {
        "cites_finding_ids",
        "no_digits",
    }


def test_budget_permission_and_write_tools() -> None:
    spec = PromptSpec(
        prompt_id="w",
        role="orchestrator",
        text="You are the workflow orchestrator. Go.",
        tools=(ToolDecl(name="submit_decision", writes=True),),
    )
    messages = [f.message for f in review_prompts((spec,)).findings if f.rule == "R005"]
    assert len(messages) == 3 and any("approval" in m for m in messages)


def test_contradictory_limits_and_always_never() -> None:
    text = GOOD_PM + "Write at most 100 words. Later write at most 120 words.\n"
    text += "Always cite findings. Never cite findings.\n"
    found = [f for f in review_prompts((_pm(text),)).findings if f.rule == "R006"]
    assert len(found) == 2


def test_placeholders_must_be_declared() -> None:
    assert "R009" in _rules(_pm(GOOD_PM + "Cases: {cases}\n"))
    assert "R009" not in _rules(_pm(GOOD_PM + "Cases: {cases}\n", placeholders=("cases",)))
    assert "R009" in _rules(_pm(GOOD_PM + "Broken {\n"))


def test_artifact_reference_chances_and_repeats() -> None:
    spec = _pm(GOOD_PM + "Cases: {cases}\nThe brief is below as JSON.\n", placeholders=("cases",))
    found = review_prompts((spec,)).findings
    assert {f.rule for f in found if f.severity == "info"} >= {"R008"}
    twin = _pm(GOOD_PM).model_copy(update={"prompt_id": "twin"})
    repeats = [f for f in review_prompts((_pm(GOOD_PM), twin)).findings if f.rule == "R007"]
    assert repeats and "across" in repeats[0].message


def test_review_never_rewrites_and_needs_approval() -> None:
    spec = _pm("You are the product manager.")
    before = spec.model_dump()
    review = review_prompts((spec,))
    assert spec.model_dump() == before
    assert review.requires_approval is True and review.rewrites_prompts is False
    assert review.candidate_changes and all(isinstance(c, tuple) for c in review.candidate_changes)


def test_production_prompts_have_no_errors_and_tools_exist() -> None:
    review = review_prompts(default_specs())
    assert [f for f in review.findings if f.severity == "error"] == []
    source = "\n".join(p.read_text(encoding="utf-8") for p in (SRC / "earthlab").rglob("*.py"))
    assert all(f'"{name}"' in source for name in ENGINEER_TOOLS)


def test_cli_review_prints_and_changes_nothing(capsys: object) -> None:
    assert main(["review"]) == 0
    assert "No prompt was changed" in capsys.readouterr().out  # type: ignore[attr-defined]
    assert main(["review", "--json"]) == 0
    assert '"rewrites_prompts": false' in capsys.readouterr().out  # type: ignore[attr-defined]

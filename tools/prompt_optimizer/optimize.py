"""Offline tuning of the specialist closing prompt with DSPy MIPROv2. It never edits the repo.

Run it only in the separate environment (see README.md), with a Qwen3 4B server up on the
URL you give. It scores prompts on 12 synthetic tickets with one deterministic check: the
specialist calls the ticket tool one time, then `submit_note`, and nothing else. It writes a
candidate file for a person to review. A person adds a reviewed candidate to
config/benchmark/prompt_variants.yaml as a new variant ID.

  --dry-run   no network, no model: check the tickets, the split and the check itself.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[2]
TICKETS = ROOT / "config" / "benchmark" / "specialist_dev_tickets.yaml"
VARIANTS = ROOT / "config" / "benchmark" / "prompt_variants.yaml"
ROLE = {"data": "Data Scientist", "ml": "ML/DL Engineer"}
TOOL = {"data": "prepare_data", "ml": "train_models"}
DEFAULT_TEMPLATE = "You are the {role}. Call {tool}, then submit_note."
MAX_TURNS = 3
LOCK = Path(__file__).with_name("requirements.lock")


def closes_cleanly(calls: list[str], tool: str) -> bool:
    """Same rule as earthlab.harness.closure.closes_cleanly. A test keeps them equal."""
    return list(calls) == [tool, "submit_note"]


def load_tickets() -> list[dict[str, Any]]:
    doc = yaml.safe_load(TICKETS.read_text(encoding="utf-8"))
    return list(doc["tickets"])


def split(tickets: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Tickets 01 to 04 of each role train. Tickets 05 and 06 stay out for the final score."""
    train = [t for t in tickets if int(t["ticket_id"].split("-")[1]) <= 4]
    return train, [t for t in tickets if t not in train]


def template_from_variant(variant_id: str) -> str:
    """The data text of a variant, turned into a template with the role and tool slots."""
    for v in yaml.safe_load(VARIANTS.read_text(encoding="utf-8"))["variants"]:
        if v["id"] == variant_id and "data" in v.get("texts", {}):
            text = " ".join(v["texts"]["data"].split())
            return text.replace("Data Scientist", "{role}").replace("prepare_data", "{tool}")
    raise SystemExit(f"variant {variant_id} has no data text")


def tool_schemas(tool: str) -> list[dict[str, Any]]:
    empty = {"type": "object", "properties": {}}
    note = {"type": "object", "properties": {"note": {"type": "string"}}, "required": ["note"]}
    return [
        {"type": "function", "function": {"name": n, "description": f"Call {n}.", "parameters": p}}
        for n, p in ((tool, empty), ("submit_note", note))
    ]


def run_ticket(client: Any, model: str, system: str, ticket: dict[str, Any]) -> list[str]:
    """A real tool loop of at most 3 turns. The tool result is a fixed stub."""
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system},
        {"role": "user", "content": json.dumps(ticket["ticket"])},
    ]
    names: list[str] = []
    for _ in range(MAX_TURNS):
        reply = (
            client.chat.completions.create(
                model=model, messages=messages, tools=tool_schemas(ticket["tool"]), temperature=0
            )
            .choices[0]
            .message
        )
        messages.append(reply.model_dump(exclude_none=True))
        for call in reply.tool_calls or []:
            names.append(call.function.name)
            stub = json.dumps({"sha256": "0" * 64})
            messages.append({"role": "tool", "tool_call_id": call.id, "content": stub})
        if "submit_note" in names or not reply.tool_calls:
            break
    return names


def fill(template: str, key: str) -> str:
    return template.format(role=ROLE[key], tool=TOOL[key])


def score(client: Any, model: str, template: str, tickets: list[dict[str, Any]]) -> float:
    done = [
        closes_cleanly(run_ticket(client, model, fill(template, t["prompt_key"]), t), t["tool"])
        for t in tickets
    ]
    return sum(done) / len(done)


def tune(client: Any, args: argparse.Namespace, train: list[dict[str, Any]]) -> str:
    import dspy

    lm = dspy.LM(f"openai/{args.model}", api_base=args.server_url, api_key="none", temperature=0.7)

    class Closer(dspy.Module):  # type: ignore[misc]
        def __init__(self) -> None:
            super().__init__()
            self.step = dspy.Predict(dspy.Signature("ticket -> calls", DEFAULT_TEMPLATE))

        def forward(self, ticket: str, key: str, tool: str) -> Any:
            system = fill(self.step.signature.instructions, key)
            ticket_row = {"ticket": json.loads(ticket), "tool": tool}
            return dspy.Prediction(
                calls=json.dumps(run_ticket(client, args.model, system, ticket_row))
            )

    def metric(example: Any, pred: Any, trace: Any = None) -> float:
        return float(closes_cleanly(json.loads(pred.calls), example.tool))

    shots = [
        dspy.Example(ticket=json.dumps(t["ticket"]), key=t["prompt_key"], tool=t["tool"])
        .with_inputs("ticket", "key", "tool") for t in train
    ]  # fmt: skip
    with dspy.context(lm=lm):
        opt = dspy.MIPROv2(
            metric=metric, prompt_model=lm, task_model=lm, auto=None,
            num_candidates=args.candidates, max_bootstrapped_demos=0, max_labeled_demos=0,
            num_threads=1, seed=9,
        )  # fmt: skip
        best = opt.compile(
            Closer(), trainset=shots, num_trials=args.trials, minibatch=False,
            requires_permission_to_run=False,
        )  # fmt: skip
    return str(best.step.signature.instructions)


def dry_run() -> int:
    tickets = load_tickets()
    train, held = split(tickets)
    assert len(tickets) == 12
    assert (len(train), len(held)) == (8, 4)
    assert closes_cleanly(["prepare_data", "submit_note"], "prepare_data")
    assert not closes_cleanly(["prepare_data"], "prepare_data")
    for template in (DEFAULT_TEMPLATE, template_from_variant("note-close-v1")):
        fill(template, "data"), fill(template, "ml")
    print("dry run ok: 12 tickets, 8 train, 4 held out, templates fill, check is exact")
    return 0


def main() -> int:
    top = argparse.ArgumentParser(description=__doc__)
    top.add_argument("--dry-run", action="store_true")
    top.add_argument("--server-url", default="http://127.0.0.1:8081/v1")
    top.add_argument("--model", default="Qwen/Qwen3-4B-Instruct-2507")
    top.add_argument("--trials", type=int, default=8)
    top.add_argument("--candidates", type=int, default=6)
    top.add_argument("--out", type=Path, help="the candidate file to write")
    args = top.parse_args()
    if args.dry_run:
        return dry_run()
    if args.out is None:
        raise SystemExit("--out is required")
    from openai import OpenAI

    client = OpenAI(base_url=args.server_url, api_key="none")
    train, held = split(load_tickets())
    candidate = tune(client, args, train)
    rows = {
        "default": DEFAULT_TEMPLATE, "note-close-v1": template_from_variant("note-close-v1"),
        "candidate": candidate,
    }  # fmt: skip
    scores = {name: score(client, args.model, text, held) for name, text in rows.items()}
    out = {
        "candidate_template": candidate, "held_out_scores": scores, "tickets_held_out": len(held),
        "sha256": hashlib.sha256(candidate.encode()).hexdigest(),
        "lock_sha256": hashlib.sha256(LOCK.read_bytes()).hexdigest(), "needs_review": True,
    }  # fmt: skip
    args.out.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

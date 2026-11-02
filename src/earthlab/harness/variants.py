"""Prompt variants as data. A variant ID selects reviewed text for a role key.

A variant holds replacement texts and optional controller reminders. A key it leaves out keeps
the engine default. Resolving a variant gives a `PromptSet` with a digest for every text, so a
trace names the exact prompts that a run used.
"""

from __future__ import annotations

from pathlib import Path
from typing import Self

import yaml
from pydantic import Field, model_validator

from earthlab.contracts import Strict
from earthlab.digest import payload_digest

PROMPT_KEYS = ("scope", "strategy", "plan", "data", "ml", "review", "decide", "forward")
BASELINE_ID = "baseline"
PROMOTED_ID = "note-close-v1"
PROMOTED_TEXTS = {
    "data": "You are the Data Scientist. Do two steps in order. Step 1: call prepare_data one "
    "time. Step 2: when the tool result arrives, call submit_note with one short sentence about "
    "the result. Your work is not done until you call submit_note. Never answer in plain text.",
    "ml": "You are the ML/DL Engineer. Do two steps in order. Step 1: call train_models one "
    "time. Step 2: when the tool result arrives, call submit_note with one short sentence about "
    "the result. Your work is not done until you call submit_note. Never answer in plain text.",
}


class PromptVariant(Strict):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    description: str = Field(min_length=10)
    texts: dict[str, str] = Field(default_factory=dict)
    reminders: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _known_keys(self) -> Self:
        for key in (*self.texts, *self.reminders):
            if key not in PROMPT_KEYS:
                raise ValueError(f"{self.id}: unknown prompt key {key}")
        if self.id == BASELINE_ID and (self.texts or self.reminders):
            raise ValueError("the baseline variant holds no text: it is the engine default")
        return self


PROMOTED = PromptVariant(
    id=PROMOTED_ID, description="The specialist closing fix. Text only, no reminder.",
    texts=PROMOTED_TEXTS,
)  # fmt: skip


class VariantFile(Strict):
    version: int
    variants: tuple[PromptVariant, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique(self) -> Self:
        ids = [v.id for v in self.variants]
        if len(set(ids)) != len(ids) or BASELINE_ID not in ids:
            raise ValueError("variant IDs must be unique and include the baseline")
        return self

    def get(self, variant_id: str) -> PromptVariant:
        for variant in self.variants:
            if variant.id == variant_id:
                return variant
        raise KeyError(f"unknown prompt variant {variant_id}")


class PromptSet(Strict):
    """The resolved prompts of one run."""

    variant_id: str
    texts: dict[str, str]
    reminders: dict[str, str]

    def system(self, key: str) -> str:
        return self.texts[key]

    def reminder(self, key: str) -> str | None:
        return self.reminders.get(key)

    def digests(self) -> dict[str, str]:
        """SHA-256 of each text and each reminder. Reminder keys end in `.reminder`."""
        found = {k: payload_digest(t) for k, t in self.texts.items()}
        return found | {f"{k}.reminder": payload_digest(t) for k, t in self.reminders.items()}


def resolve(variant: PromptVariant, defaults: dict[str, str]) -> PromptSet:
    if set(defaults) != set(PROMPT_KEYS):
        raise ValueError("the engine defaults must cover every prompt key")
    return PromptSet(
        variant_id=variant.id, texts=defaults | variant.texts, reminders=dict(variant.reminders)
    )


def load_variants(path: Path) -> VariantFile:
    return VariantFile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))

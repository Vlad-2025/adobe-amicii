"""Output schemas: Pydantic for validation, plain JSON-schema dicts for Gemini/Ollama structured output."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

DIMENSIONS = ["hook", "cta", "benefit", "emotional_angle", "offer"]


class Persona(BaseModel):
    name: str = Field(max_length=60)
    one_liner: str = Field(max_length=200)
    interests: list[str] = Field(min_length=2, max_length=6)
    tone: str = Field(max_length=80)
    do: list[str] = Field(min_length=1, max_length=4)
    dont: list[str] = Field(min_length=1, max_length=4)
    best_hours: str = Field(max_length=60)


class Narrative(BaseModel):
    headline: str = Field(max_length=120)
    explanation: str = Field(max_length=600)
    recommended_action: str = Field(max_length=200)


class Variant(BaseModel):
    changed_dimension: Literal["hook", "cta", "benefit", "emotional_angle", "offer"]
    hook: str
    body: str
    cta: str
    offer: str = "none"
    hypothesis: str = Field(max_length=300)
    expected_effect: str = Field(max_length=200)

    @field_validator("offer", mode="before")
    @classmethod
    def _none(cls, v):
        return v or "none"


class Variants(BaseModel):
    variants: list[Variant] = Field(min_length=1, max_length=5)


class Learning(BaseModel):
    insight: str = Field(max_length=240)
    evidence: str = Field(max_length=240)
    community: str = Field(max_length=60)
    dimension: str = Field(max_length=40)


def _obj(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required}


S = {"type": "string"}
SA = {"type": "array", "items": S}

PERSONA_SCHEMA = _obj({"name": S, "one_liner": S, "interests": SA, "tone": S, "do": SA, "dont": SA, "best_hours": S},
                      ["name", "one_liner", "interests", "tone", "do", "dont", "best_hours"])
NARRATIVE_SCHEMA = _obj({"headline": S, "explanation": S, "recommended_action": S}, ["headline", "explanation", "recommended_action"])
VARIANTS_SCHEMA = _obj({"variants": {"type": "array", "items": _obj(
    {"changed_dimension": {"type": "string", "enum": DIMENSIONS}, "hook": S, "body": S, "cta": S, "offer": S, "hypothesis": S, "expected_effect": S},
    ["changed_dimension", "hook", "body", "cta", "offer", "hypothesis", "expected_effect"])}}, ["variants"])
LEARNING_SCHEMA = _obj({"insight": S, "evidence": S, "community": S, "dimension": S}, ["insight", "evidence", "community", "dimension"])

"""Output schemas: Pydantic for validation, plain JSON-schema dicts for Gemini/Ollama structured output.

Validation is forgiving on size: models often return a few too many list items or a slightly long
sentence, so lists are trimmed and strings cut to the limit instead of rejecting the whole answer.
Wrong types or missing fields still fail (and trigger the retry / fallback)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, field_validator

DIMENSIONS = ["hook", "cta", "benefit", "emotional_angle", "offer"]


def _cut(v, n: int):
    return v[:n].rstrip() if isinstance(v, str) else v


def _first(v, n: int):
    if isinstance(v, str):  # a comma-separated string instead of a list
        v = [x.strip() for x in v.split(",") if x.strip()]
    return v[:n] if isinstance(v, list) else v


class Persona(BaseModel):
    name: str
    one_liner: str
    interests: list[str]
    tone: str
    do: list[str]
    dont: list[str]
    best_hours: str

    @field_validator("name", mode="before")
    @classmethod
    def _n(cls, v):
        return _cut(v, 60)

    @field_validator("one_liner", mode="before")
    @classmethod
    def _o(cls, v):
        return _cut(v, 200)

    @field_validator("tone", "best_hours", mode="before")
    @classmethod
    def _t(cls, v):
        return _cut(v, 80)

    @field_validator("interests", mode="before")
    @classmethod
    def _i(cls, v):
        return _first(v, 5)

    @field_validator("do", "dont", mode="before")
    @classmethod
    def _d(cls, v):
        return _first(v, 3)

    @field_validator("interests", "do", "dont")
    @classmethod
    def _nonempty(cls, v):
        if not v:
            raise ValueError("empty list")
        return [_cut(x, 120) for x in v]


class Narrative(BaseModel):
    headline: str
    explanation: str
    recommended_action: str

    @field_validator("headline", mode="before")
    @classmethod
    def _h(cls, v):
        return _cut(v, 120)

    @field_validator("explanation", mode="before")
    @classmethod
    def _e(cls, v):
        return _cut(v, 600)

    @field_validator("recommended_action", mode="before")
    @classmethod
    def _r(cls, v):
        return _cut(v, 200)


class Variant(BaseModel):
    changed_dimension: Literal["hook", "cta", "benefit", "emotional_angle", "offer"]
    hook: str
    body: str
    cta: str
    offer: str = "none"
    hypothesis: str
    expected_effect: str

    @field_validator("offer", mode="before")
    @classmethod
    def _none(cls, v):
        return v or "none"

    @field_validator("changed_dimension", mode="before")
    @classmethod
    def _dim(cls, v):
        return str(v).strip().lower().replace(" ", "_").replace("-", "_") if v else v

    @field_validator("hypothesis", mode="before")
    @classmethod
    def _hy(cls, v):
        return _cut(v, 300)

    @field_validator("expected_effect", mode="before")
    @classmethod
    def _ex(cls, v):
        return _cut(v, 200)


class Variants(BaseModel):
    variants: list[Variant]

    @field_validator("variants", mode="before")
    @classmethod
    def _v(cls, v):
        return _first(v, 5)

    @field_validator("variants")
    @classmethod
    def _nonempty(cls, v):
        if not v:
            raise ValueError("no variants")
        return v


class Learning(BaseModel):
    insight: str
    evidence: str
    community: str
    dimension: str

    @field_validator("insight", "evidence", mode="before")
    @classmethod
    def _ie(cls, v):
        return _cut(v, 240)

    @field_validator("community", mode="before")
    @classmethod
    def _c(cls, v):
        return _cut(v, 60)

    @field_validator("dimension", mode="before")
    @classmethod
    def _d(cls, v):
        return _cut(v, 40)


def _obj(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required}


S = {"type": "string"}


def SA(n: int) -> dict:
    return {"type": "array", "items": S, "minItems": 1, "maxItems": n}


PERSONA_SCHEMA = _obj({"name": S, "one_liner": S, "interests": SA(5), "tone": S, "do": SA(3), "dont": SA(3), "best_hours": S},
                      ["name", "one_liner", "interests", "tone", "do", "dont", "best_hours"])
NARRATIVE_SCHEMA = _obj({"headline": S, "explanation": S, "recommended_action": S}, ["headline", "explanation", "recommended_action"])
VARIANTS_SCHEMA = _obj({"variants": {"type": "array", "minItems": 3, "maxItems": 3, "items": _obj(
    {"changed_dimension": {"type": "string", "enum": DIMENSIONS}, "hook": S, "body": S, "cta": S, "offer": S, "hypothesis": S, "expected_effect": S},
    ["changed_dimension", "hook", "body", "cta", "offer", "hypothesis", "expected_effect"])}}, ["variants"])
LEARNING_SCHEMA = _obj({"insight": S, "evidence": S, "community": S, "dimension": S}, ["insight", "evidence", "community", "dimension"])

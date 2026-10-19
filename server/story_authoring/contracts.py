"""Typed contracts of the story-authoring generation seam.

Token limits are tokens counted by the serving model, never words or characters. Every ceiling is a
positive finite integer; money ceilings are in the configured currency's minor unit, and currency
``LOCAL`` means a local model with no billing (its token and call ceilings still bind).
"""

from __future__ import annotations

import hashlib
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from r2.contracts.common import ensure_json_value
from r2.contracts.fingerprints import canonical_json_bytes

OLLAMA_CHAT_ENDPOINT = "ollama-chat"
LOCAL_CURRENCY = "LOCAL"


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class StoryFailureCode(StrEnum):
    INPUT_OVER_LIMIT = "INPUT_OVER_LIMIT"
    INPUT_OVER_CONTEXT = "INPUT_OVER_CONTEXT"
    OUTPUT_TRUNCATED = "OUTPUT_TRUNCATED"
    OUTPUT_INVALID = "OUTPUT_INVALID"
    CJK_IN_OUTPUT = "CJK_IN_OUTPUT"
    COUNT_MISMATCH = "COUNT_MISMATCH"
    MODEL_UNAVAILABLE = "MODEL_UNAVAILABLE"
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    PROVIDER_NOT_QUALIFIED = "PROVIDER_NOT_QUALIFIED"
    SELECTION_CHANGED = "SELECTION_CHANGED"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    RUN_NOT_RUNNING = "RUN_NOT_RUNNING"
    NOT_DISPATCHED = "NOT_DISPATCHED"


class AttemptKind(StrEnum):
    COUNT = "COUNT"
    GENERATE = "GENERATE"


class StoryStepKind(StrEnum):
    SEED = "SEED"
    BIBLE = "BIBLE"
    OUTLINE = "OUTLINE"
    SCENE_CONTRACT = "SCENE_CONTRACT"
    SCENE_DRAFT = "SCENE_DRAFT"
    REPAIR = "REPAIR"
    CHAPTER_REVIEW = "CHAPTER_REVIEW"
    MANUSCRIPT_REVIEW = "MANUSCRIPT_REVIEW"
    PACKAGING = "PACKAGING"


class OutputMode(StrEnum):
    PROSE = "PROSE"
    STRUCTURED = "STRUCTURED"


class StoryScope(_Frozen):
    user_id: str = Field(min_length=1)
    project_name: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)


class StoryLimits(_Frozen):
    chapters: int = Field(default=3, ge=1)
    max_input_tokens: int = Field(default=24576, gt=0)
    max_output_tokens: int = Field(default=4096, gt=0)
    server_context_tokens: int = Field(default=32768, gt=0)
    generate_calls_max: int = Field(default=132, gt=0)
    count_calls_max: int = Field(default=132, gt=0)
    input_tokens_max: int = Field(gt=0)
    output_tokens_max: int = Field(gt=0)
    wall_clock_max_seconds: int = Field(gt=0)
    max_repairs: int = Field(default=2, ge=0)
    max_scene_attempts: int = Field(default=6, gt=0)
    max_cost_minor_units: int = Field(default=0, ge=0)
    currency: str = Field(default=LOCAL_CURRENCY, min_length=1)

    @model_validator(mode="after")
    def _consistent(self) -> StoryLimits:
        if self.max_input_tokens + self.max_output_tokens > self.server_context_tokens:
            raise ValueError("max_input_tokens + max_output_tokens must fit inside server_context_tokens")
        if self.currency != LOCAL_CURRENCY and self.max_cost_minor_units <= 0:
            raise ValueError("a priced currency needs a positive max_cost_minor_units")
        if self.currency == LOCAL_CURRENCY and self.max_cost_minor_units != 0:
            raise ValueError("currency LOCAL carries no money ceiling")
        return self

    @property
    def total_http_calls_max(self) -> int:
        return self.count_calls_max + self.generate_calls_max


class StoryModelSelection(_Frozen):
    """A frozen route. ``config_digest`` covers every routing field and never the credential itself."""

    provider_id: str = Field(min_length=1)
    endpoint: str = Field(min_length=1)
    base_url: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    has_credential: bool
    config_digest: str

    @classmethod
    def create(
        cls, *, provider_id: str, endpoint: str, base_url: str, model_id: str, has_credential: bool
    ) -> StoryModelSelection:
        fields = {
            "provider_id": provider_id,
            "endpoint": endpoint,
            "base_url": base_url,
            "model_id": model_id,
            "has_credential": has_credential,
        }
        return cls(**fields, config_digest=sha256_digest(fields))

    @model_validator(mode="after")
    def _digest_matches(self) -> StoryModelSelection:
        expected = sha256_digest(self.model_dump(exclude={"config_digest"}))
        if self.config_digest != expected:
            raise ValueError("config_digest does not match the selection fields")
        return self


class StoryDecoding(_Frozen):
    temperature: float = Field(ge=0.0, le=2.0)
    top_p: float = Field(default=0.8, gt=0.0, le=1.0)
    top_k: int = Field(default=20, gt=0)
    presence_penalty: float = Field(default=0.0, ge=0.0, le=2.0)
    # Ollama 0.32.6 ignores presence_penalty for qwen3.5; repeat_penalty and frequency_penalty take effect.
    repeat_penalty: float = Field(default=1.0, ge=1.0, le=2.0)
    frequency_penalty: float = Field(default=0.0, ge=0.0, le=2.0)
    seed: int

    def options(self) -> dict[str, float | int]:
        return self.model_dump()


class StoryStepRequest(BaseModel):
    """One generation step. ``response_model`` is required for STRUCTURED output and forbidden for PROSE.

    PROSE is generated as an array of paragraphs bounded by ``min_paragraphs``..``max_paragraphs`` and returned
    joined by blank lines.
    """

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    step_id: str = Field(min_length=1)
    kind: StoryStepKind
    context_digest: str = Field(min_length=1)
    selection: StoryModelSelection
    system_prompt: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    output_mode: OutputMode
    response_model: type[BaseModel] | None = None
    decoding: StoryDecoding
    max_output_tokens: int = Field(gt=0)
    min_paragraphs: int = Field(default=1, ge=1)
    max_paragraphs: int = Field(default=40, ge=1)
    min_paragraph_chars: int = Field(default=20, ge=1, le=600)
    max_paragraph_chars: int | None = Field(default=None, ge=1, le=4000)

    @model_validator(mode="after")
    def _mode_matches_model(self) -> StoryStepRequest:
        if (self.output_mode is OutputMode.STRUCTURED) != (self.response_model is not None):
            raise ValueError("response_model is required exactly for STRUCTURED output")
        if self.min_paragraphs > self.max_paragraphs:
            raise ValueError("min_paragraphs must not exceed max_paragraphs")
        if self.max_paragraph_chars is not None and self.max_paragraph_chars < self.min_paragraph_chars:
            raise ValueError("max_paragraph_chars must not be below min_paragraph_chars")
        return self


class StoryStepOutput(_Frozen):
    step_id: str
    text: str
    provider_id: str
    model_id: str
    finish_reason: str
    input_tokens: int
    output_tokens: int
    request_digest: str
    response_digest: str
    count_attempt_id: str
    generate_attempt_id: str


def sha256_digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(ensure_json_value(value))).hexdigest()

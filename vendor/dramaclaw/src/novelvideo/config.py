"""Seam: the three ``novelvideo.config`` members the identity planner reads.

``get_newapi_structured_output_model_settings`` and ``get_fish_voice_id`` keep DramaClaw @ b299bfd behaviour.
The text model comes from the host: ArcReel installs a factory with ``set_text_model_factory`` that returns a
PydanticAI model for its configured text route.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

TextModelFactory = Callable[[str, str], Any]
_text_model_factory: TextModelFactory | None = None


def set_text_model_factory(factory: TextModelFactory | None) -> None:
    """Install (or clear) the factory called as ``factory(model_env, default_model)``."""
    global _text_model_factory
    _text_model_factory = factory


def get_newapi_text_pydantic_model(
    model_env: str,
    default_model: str,
    *,
    model_name_override: str | None = None,
    timeout_seconds_override: float | None = None,
    capability: str = "text.generate",
) -> Any:
    if _text_model_factory is None:
        raise ValueError("no text model factory installed for the DramaClaw identity planner")
    return _text_model_factory(model_env, model_name_override or default_model)


def get_newapi_structured_output_model_settings() -> dict:
    return {"openai_reasoning_effort": "none"}


FISH_VOICE_PRESETS = {
    "child_male": os.environ.get("FISH_VOICE_CHILD_MALE", ""),
    "child_female": os.environ.get("FISH_VOICE_CHILD_FEMALE", ""),
    "youth_male": os.environ.get("FISH_VOICE_YOUTH_MALE", ""),
    "youth_female": os.environ.get("FISH_VOICE_YOUTH_FEMALE", ""),
    "middle_male": os.environ.get("FISH_VOICE_MIDDLE_MALE", ""),
    "middle_female": os.environ.get("FISH_VOICE_MIDDLE_FEMALE", ""),
    "elder_male": os.environ.get("FISH_VOICE_ELDER_MALE", ""),
    "elder_female": os.environ.get("FISH_VOICE_ELDER_FEMALE", ""),
}


def get_fish_voice_id(age_group: str, gender: str) -> str:
    text = str(gender or "").strip().lower()
    gender_key = "female" if ("女" in text or "female" in text) else "male"
    return FISH_VOICE_PRESETS.get(f"{age_group}_{gender_key}", "")

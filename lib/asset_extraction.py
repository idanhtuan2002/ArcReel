"""Schema-bound asset extraction for one asset-inventory scope.

One text call reads the scope's source text and returns characters, scenes and props in a fixed schema. Names
the project already registers are dropped, then the result goes through ``complete_asset_inventory`` with the
source revision the extraction read, so the definitions and the completion fact land in one transaction or not
at all. The model never writes files; an empty or malformed response fails instead of completing an empty
inventory.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from lib.asset_inventory import AssetInventoryCompletion, AssetInventoryError, complete_asset_inventory
from lib.asset_types import resolve_asset_key, validate_asset_name
from lib.project_manager import ProjectManager
from lib.source_revision import SourceScope, compute_source_revision
from lib.text_attestation import named_in
from lib.text_backends.base import TextGenerationRequest, TextGenerationResult

MAX_PER_BUCKET = 12
MAX_SOURCE_CHARS = 60_000

type Generate = Callable[[TextGenerationRequest], Awaitable[TextGenerationResult]]


class _Entry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=40)
    description: str = Field(min_length=1, max_length=600)


class _Character(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=40)
    identity: str = Field(min_length=1, max_length=400)
    outfit: str = Field(min_length=1, max_length=300)
    voice_style: str = Field(default="", max_length=200)

    @property
    def description(self) -> str:
        """The character's appearance: who they are to the eye, then what they wear."""
        return f"{self.identity.strip()}\n{self.outfit.strip()}"


class AssetExtraction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    characters: list[_Character] = Field(max_length=MAX_PER_BUCKET)
    scenes: list[_Entry] = Field(max_length=MAX_PER_BUCKET)
    props: list[_Entry] = Field(max_length=MAX_PER_BUCKET)


class AssetExtractionError(AssetInventoryError):
    """The model's response cannot become an inventory."""


PROMPT = """You extract visual asset definitions for AI video production from the source text below.

Return JSON with three lists: characters, scenes, props.
- characters: named individuals with a substantial on-page presence and a stable look. Skip unnamed or generic
  people (crowds, "an old man", numbered extras). Appearance only: no personality, relations or plot.
  - identity: what stays the same in every scene: age (a number or a narrow range), gender, height and build,
    face shape and features (eyes, nose, brows, jaw), skin tone, hair (colour, length, style), and any
    distinguishing mark. Concrete visual words, never abstract ones ("large dark eyes, a high nose bridge", not
    "beautiful").
  - outfit: what the character wears through most of the story: each garment with its colour as a name and a
    hex code bound to that garment (for example "a jade silk ao dai #2A7F7A, white trousers #F4F1EA"), shoes,
    accessories, and one signature item they carry or wear.
  - Where the text does not say, design plausible details that fit the setting and the character, and make the
    characters clearly different from each other at a glance (hair, build, outfit colours).
  - voice_style: a short voice/tone description.
- scenes: recurring or visually distinctive places. description: space, atmosphere, light and colour of the
  place itself; never people or events.
- props: recurring or visually distinctive objects. description: look, material, size and colour.
Write every name and description in the source text's language. Use names exactly as the text writes them.
At most {limit} entries per list. For scenes and props, do not invent visual details the text does not support;
when the text gives none, write a short neutral description consistent with the story's setting.

Source text:
<<<
{source}
>>>
"""


def _entries(extraction: AssetExtraction, project: dict[str, Any], source: str) -> dict[str, dict[str, dict[str, str]]]:
    buckets: dict[str, dict[str, dict[str, str]]] = {}
    for bucket, items in (
        ("characters", extraction.characters),
        ("scenes", extraction.scenes),
        ("props", extraction.props),
    ):
        existing = project.get(bucket) if isinstance(project.get(bucket), dict) else {}
        chosen: dict[str, dict[str, str]] = {}
        for item in items:
            try:
                name = validate_asset_name(item.name)
            except ValueError:
                continue
            if resolve_asset_key(existing, name) is not None or resolve_asset_key(chosen, name) is not None:
                continue
            # A character the source never names is invented (DramaClaw's name attestation); places and objects
            # may carry a descriptive name, so only characters are held to the source's words.
            if bucket == "characters" and not named_in(name, source):
                continue
            entry = {"description": item.description.strip()}
            if isinstance(item, _Character) and item.voice_style.strip():
                entry["voice_style"] = item.voice_style.strip()
            chosen[name] = entry
        buckets[bucket] = chosen
    return buckets


async def extract_asset_inventory(
    projects: ProjectManager,
    project_name: str,
    *,
    scope: SourceScope,
    expected_source_revision: str,
    generate: Generate,
) -> AssetInventoryCompletion:
    project_path = projects.get_project_path(project_name)
    project = await asyncio.to_thread(projects.load_project, project_name)
    revision = await asyncio.to_thread(compute_source_revision, project_path, project, scope)
    if revision.blockers or revision.revision is None:
        raise AssetExtractionError("source scope is blocked")
    if revision.revision != expected_source_revision:
        raise AssetExtractionError("source revision changed before extraction")
    source = "\n\n".join(doc.text for doc in revision.documents).strip()
    if not source:
        raise AssetExtractionError("source text is empty")
    if len(source) > MAX_SOURCE_CHARS:
        raise AssetExtractionError("source text exceeds the extraction bound")
    result = await generate(
        TextGenerationRequest(
            prompt=PROMPT.format(limit=MAX_PER_BUCKET, source=source),
            response_schema=AssetExtraction,
        )
    )
    try:
        extraction = AssetExtraction.model_validate(json.loads(result.text))
    except (ValueError, ValidationError) as error:
        raise AssetExtractionError(f"extraction response is invalid: {error}") from None
    entries = _entries(extraction, project, source)
    existing_characters = project.get("characters") if isinstance(project.get("characters"), dict) else {}
    if not entries["characters"] and not existing_characters:
        raise AssetExtractionError("extraction found no character")
    return await asyncio.to_thread(
        complete_asset_inventory, projects, project_name, scope, expected_source_revision, entries
    )


__all__ = ["AssetExtraction", "AssetExtractionError", "extract_asset_inventory"]

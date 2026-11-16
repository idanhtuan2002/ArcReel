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
import unicodedata
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from lib.asset_inventory import AssetInventoryCompletion, AssetInventoryError, complete_asset_inventory
from lib.asset_types import DERIVATIVES_FIELD, resolve_asset_key, validate_asset_name
from lib.output_hygiene import leak_reason
from lib.project_manager import ProjectManager
from lib.source_revision import SourceScope, compute_source_revision
from lib.text_attestation import named_in
from lib.text_backends.base import TextGenerationRequest, TextGenerationResult

MAX_PER_BUCKET = 12
MAX_STATES = 4
MAX_SOURCE_CHARS = 60_000
#: A longer source (a book of several parts) is read in chunks of at most this size, cut at paragraph breaks.
CHUNK_CHARS = 50_000
#: The most chunks one inventory reads (about 400 000 characters).
MAX_CHUNKS = 8

type Generate = Callable[[TextGenerationRequest], Awaitable[TextGenerationResult]]


class _Entry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=40)
    description: str = Field(min_length=1, max_length=600)


class _State(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=24)
    change: str = Field(min_length=1, max_length=300)
    evidence: str = Field(min_length=1, max_length=300)


class _Character(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=40)
    identity: str = Field(min_length=1, max_length=400)
    outfit: str = Field(min_length=1, max_length=300)
    voice_style: str = Field(default="", max_length=200)
    states: list[_State] = Field(default_factory=list, max_length=MAX_STATES)

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
  - states: only lasting, visible changes the text states explicitly for a stretch of the story: another outfit
    (a wedding dress, a uniform, mourning clothes), an injury or bandage, a clearly different age (a childhood
    flashback, years later), soaked or dirty after an event. Never a momentary expression, pose or held object.
    name: a short state name; change: an image-edit instruction saying only what differs from identity and
    outfit ("now wears a white wedding ao dai #F5F1E8 and a gold headband; everything else stays the same");
    evidence: the exact sentence of the source text that shows it. At most {states} per character; none when
    the character never changes.
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


def _normalized(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).split()).casefold()


def _attested_states(states: list[_State], source: str) -> dict[str, dict[str, str]]:
    """The states whose evidence the source really contains, as derivatives (state name → change description);
    a state the text never shows is invented and dropped, like a character the text never names."""
    text = _normalized(source)
    attested: dict[str, dict[str, str]] = {}
    for state in states:
        try:
            name = validate_asset_name(state.name)
        except ValueError:
            continue
        if name in attested or _normalized(state.evidence) not in text:
            continue
        attested[name] = {"description": state.change.strip()}
    return attested


#: Field names of the extraction schema; one inside a description is scaffolding, not a description.
_SCHEMA_FIELDS = ("description", "voice_style", "evidence", "states", "change")


def _entries(extraction: AssetExtraction, project: dict[str, Any], source: str) -> dict[str, dict[str, dict[str, Any]]]:
    buckets: dict[str, dict[str, dict[str, Any]]] = {}
    for bucket, items in (
        ("characters", extraction.characters),
        ("scenes", extraction.scenes),
        ("props", extraction.props),
    ):
        existing = project.get(bucket) if isinstance(project.get(bucket), dict) else {}
        chosen: dict[str, dict[str, Any]] = {}
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
            # A description holding the model's reasoning or schema scaffolding is not one; another chunk may
            # describe the same asset cleanly.
            if leak_reason(item.description, schema_fields=_SCHEMA_FIELDS):
                continue
            entry: dict[str, Any] = {"description": item.description.strip()}
            if (
                isinstance(item, _Character)
                and item.voice_style.strip()
                and not leak_reason(item.voice_style, schema_fields=_SCHEMA_FIELDS)
            ):
                entry["voice_style"] = item.voice_style.strip()
            if isinstance(item, _Character):
                states = _attested_states(item.states, source)
                if states:
                    entry[DERIVATIVES_FIELD] = states
            chosen[name] = entry
        buckets[bucket] = chosen
    return buckets


def source_chunks(source: str, size: int = CHUNK_CHARS) -> list[str]:
    """The source cut at paragraph breaks into chunks of at most ``size`` characters (a longer paragraph alone)."""
    chunks: list[str] = []
    current = ""
    for paragraph in source.split("\n\n"):
        if current and len(current) + 2 + len(paragraph) > size:
            chunks.append(current)
            current = paragraph
        else:
            current = f"{current}\n\n{paragraph}" if current else paragraph
    if current:
        chunks.append(current)
    return chunks


def merge_entries(
    parts: list[dict[str, dict[str, dict[str, Any]]]], source: str
) -> dict[str, dict[str, dict[str, Any]]]:
    """Chunk inventories as one: an entry keeps its first description and voice, gains the states later chunks
    attest (up to ``MAX_STATES``), and each list keeps the ``MAX_PER_BUCKET`` entries the whole source names most."""
    text = _normalized(source)
    merged: dict[str, dict[str, dict[str, Any]]] = {}
    for bucket in ("characters", "scenes", "props"):
        chosen: dict[str, dict[str, Any]] = {}
        for part in parts:
            for name, entry in part.get(bucket, {}).items():
                key = resolve_asset_key(chosen, name)
                if key is None:
                    chosen[name] = {k: (dict(v) if isinstance(v, dict) else v) for k, v in entry.items()}
                    continue
                states = chosen[key].setdefault(DERIVATIVES_FIELD, {}) if DERIVATIVES_FIELD in entry else None
                if states is not None:
                    for state, change in entry[DERIVATIVES_FIELD].items():
                        if state not in states and len(states) < MAX_STATES:
                            states[state] = change
        ranked = sorted(chosen, key=lambda name: -text.count(_normalized(name)))
        merged[bucket] = {name: chosen[name] for name in ranked[:MAX_PER_BUCKET]}
    return merged


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
    chunks = [source] if len(source) <= MAX_SOURCE_CHARS else source_chunks(source)
    if len(chunks) > MAX_CHUNKS:
        raise AssetExtractionError("source text exceeds the extraction bound")
    parts: list[dict[str, dict[str, dict[str, Any]]]] = []
    for chunk in chunks:
        result = await generate(
            TextGenerationRequest(
                prompt=PROMPT.format(limit=MAX_PER_BUCKET, states=MAX_STATES, source=chunk),
                response_schema=AssetExtraction,
            )
        )
        try:
            extraction = AssetExtraction.model_validate(json.loads(result.text))
        except (ValueError, ValidationError) as error:
            raise AssetExtractionError(f"extraction response is invalid: {error}") from None
        parts.append(_entries(extraction, project, chunk))
    entries = parts[0] if len(parts) == 1 else merge_entries(parts, source)
    existing_characters = project.get("characters") if isinstance(project.get("characters"), dict) else {}
    if not entries["characters"] and not existing_characters:
        raise AssetExtractionError("extraction found no character")
    return await asyncio.to_thread(
        complete_asset_inventory, projects, project_name, scope, expected_source_revision, entries
    )


__all__ = ["AssetExtraction", "AssetExtractionError", "extract_asset_inventory", "merge_entries", "source_chunks"]

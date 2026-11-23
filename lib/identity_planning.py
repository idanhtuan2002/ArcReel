"""Per-episode character identities, planned by DramaClaw's identity planner (vendor/dramaclaw, ADR-0168).

The planner runs unchanged. This module is only the seam:

- ``text_function_model`` gives the planner's PydanticAI agents a model that sends every request through the
  project's own text route (``generate``), so routing, fallbacks and usage accounting stay ArcReel's.
- ``ProjectIdentityStore`` answers the store calls the planner makes from a ``project.json`` snapshot and records
  its writes in memory.
- ``plan_episode_identities`` runs the planner for one episode over the text script planning reads, and
  ``apply_identity_plan`` writes the result in one ``project.json`` update: each identity becomes a character
  derivative (ADR-0072/0146) and the episode records which derivative each character wears by default.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from novelvideo.agents.identity_planner import IdentityPlanner
from novelvideo.models import CharacterIdentity, NovelCharacter, NovelEpisode
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    RetryPromptPart,
    SystemPromptPart,
    TextPart,
    ToolCallPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from lib.asset_derivatives import derivative_table, ensure_derivative_table
from lib.asset_types import ASSET_SPECS, DERIVATIVES_FIELD, resolve_asset_key, validate_asset_name
from lib.episode_adaptation import script_source_relpath
from lib.text_backends.base import TextGenerationRequest, TextGenerationResult

type Generate = Callable[[TextGenerationRequest], Awaitable[TextGenerationResult]]

#: Episode field naming the derivative each character wears by default in that episode (character → derivative).
IDENTITY_DEFAULTS_FIELD = "identity_defaults"
#: Derivative field keeping the planner's identity fields, so a later episode reuses or repairs the same identity.
IDENTITY_FIELD = "identity"
_SHEET_FIELD = ASSET_SPECS["character"].sheet_field
_IDENTITY_KEYS = ("appearance_details", "face_prompt", "body_type", "age_group", "source")


class IdentityPlanningError(RuntimeError):
    """The planner could not plan the episode (no cast, a character without a default identity, no source)."""


# --- model seam -------------------------------------------------------------------------------------------------


def _render_messages(messages: list[ModelMessage]) -> tuple[str, str]:
    """The conversation as (system prompt, prompt): the planner's request first, then any earlier answer and the
    validation feedback PydanticAI sends back for a retry."""
    system: list[str] = []
    turns: list[str] = []
    for message in messages:
        if isinstance(message, ModelRequest):
            if message.instructions:
                system.append(message.instructions)
            for part in message.parts:
                if isinstance(part, SystemPromptPart):
                    system.append(part.content)
                elif isinstance(part, UserPromptPart):
                    turns.append(part.content if isinstance(part.content, str) else str(part.content))
                elif isinstance(part, RetryPromptPart):
                    turns.append("Your previous answer was rejected:\n" + part.model_response())
                else:
                    turns.append(str(part.content))
        else:
            for part in message.parts:
                if isinstance(part, ToolCallPart):
                    turns.append("Your previous answer:\n" + part.args_as_json_str())
                elif isinstance(part, TextPart):
                    turns.append("Your previous answer:\n" + part.content)
    return "\n\n".join(system), "\n\n".join(turns)


def text_function_model(generate: Generate) -> FunctionModel:
    """A PydanticAI model whose every call is one schema-bound request on the project's text route."""

    async def call(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        if len(info.output_tools) != 1:
            raise IdentityPlanningError("the identity planner expects exactly one structured output")
        tool = info.output_tools[0]
        system, prompt = _render_messages(messages)
        result = await generate(
            TextGenerationRequest(
                prompt=prompt,
                system_prompt=system or None,
                response_schema=tool.parameters_json_schema,
            )
        )
        return ModelResponse(parts=[ToolCallPart(tool_name=tool.name, args=result.text)], model_name=result.model)

    return FunctionModel(call, model_name="arcreel-text-route")


# --- store seam -------------------------------------------------------------------------------------------------


def _identity_id(character: str, derivative: str) -> str:
    return f"{character}_{derivative}"


def _base_parts(description: str) -> tuple[str, str]:
    """A character description is its identity line, then its outfit (``lib.asset_extraction``)."""
    head, _, rest = description.strip().partition("\n")
    return head.strip(), rest.strip()


def derivative_description(identity: Mapping[str, Any]) -> str:
    """The image-edit change a derivative sheet applies to the owner's sheet for this identity."""
    lines = [f"Outfit, hair and accessories become: {str(identity.get('appearance_details') or '').strip()}"]
    if face := str(identity.get("face_prompt") or "").strip():
        lines.append(f"Face (a different age of the same person): {face}")
    if body := str(identity.get("body_type") or "").strip():
        lines.append(f"Build: {body}")
    lines.append("Everything not named here stays the same.")
    return "\n".join(lines)


@dataclass
class IdentityPlan:
    """What the planner decided for one episode."""

    episode: int
    #: character → derivative name → the identity's fields (``_IDENTITY_KEYS``), for identities created or updated.
    identities: dict[str, dict[str, dict[str, str]]] = field(default_factory=dict)
    #: character → derivative worn by default in this episode.
    defaults: dict[str, str] = field(default_factory=dict)
    #: every identity the episode uses, as ``character/derivative``.
    used: list[str] = field(default_factory=list)
    log: list[str] = field(default_factory=list)


class ProjectIdentityStore:
    """The store calls DramaClaw's planner makes, answered from a ``project.json`` snapshot."""

    def __init__(self, project: Mapping[str, Any], episode_text: Mapping[int, str]) -> None:
        raw = project.get("characters")
        self._characters: dict[str, NovelCharacter] = {}
        for name, entry in raw.items() if isinstance(raw, Mapping) else ():
            if isinstance(entry, Mapping):
                self._characters[name] = self._character(name, entry)
        self._episode_text = dict(episode_text)
        self.written: dict[str, dict[str, dict[str, str]]] = {}
        self.episode_fields: dict[int, dict[str, Any]] = {}

    @staticmethod
    def _character(name: str, entry: Mapping[str, Any]) -> NovelCharacter:
        face, outfit = _base_parts(str(entry.get("description") or ""))
        identities = []
        for derivative, item in derivative_table(entry).items():
            if not isinstance(item, Mapping):
                continue
            raw_identity = item.get(IDENTITY_FIELD)
            stored: Mapping[str, Any] = raw_identity if isinstance(raw_identity, Mapping) else {}
            identity_id = _identity_id(name, derivative)
            identities.append(
                CharacterIdentity(
                    identity_id=identity_id,
                    character_name=name,
                    identity_name=derivative,
                    appearance_details=str(stored.get("appearance_details") or item.get("description") or ""),
                    face_prompt=str(stored.get("face_prompt") or ""),
                    body_type=str(stored.get("body_type") or ""),
                    age_group=str(stored.get("age_group") or ""),
                    source=str(stored.get("source") or "extracted"),
                )
            )
        character = NovelCharacter(name=name, age_group="", face_prompt=face, appearance_details=outfit)
        character.identities = identities
        return character

    # Reads -------------------------------------------------------------------------------------------------------

    def get_all_characters(self) -> list[NovelCharacter]:
        return list(self._characters.values())

    def get_character(self, name: str | None) -> NovelCharacter | None:
        return self._characters.get(name) if name else None

    def resolve_name(self, name: str | None) -> str | None:
        if not name:
            return None
        if name in self._characters:
            return name
        key = resolve_asset_key(self._characters, name.strip())
        return key if isinstance(key, str) else None

    async def load_episode_content(self, episode_number: int) -> str:
        return self._episode_text.get(episode_number, "")

    # Writes ------------------------------------------------------------------------------------------------------

    def _put(self, character_name: str, identity: CharacterIdentity) -> None:
        character = self._characters[character_name]
        others = [i for i in character.identities if i.identity_id != identity.identity_id]
        character.identities = [*others, identity]
        self.written.setdefault(character_name, {})[identity.identity_name] = {
            key: str(getattr(identity, key) or "") for key in _IDENTITY_KEYS
        }

    async def add_character_identity(self, character_name: str, identity: CharacterIdentity) -> None:
        character = self._characters.get(character_name)
        if character is None:
            raise ValueError(f"角色 {character_name} 不存在")
        if character.get_identity(identity.identity_name) is not None:
            raise ValueError(f"身份 {identity.identity_id} 已存在")
        validate_asset_name(identity.identity_name)
        self._put(character_name, identity)

    async def update_character_identity(self, character_name: str, identity_id: str, **fields: Any) -> None:
        character = self._characters[character_name]
        current = next(i for i in character.identities if i.identity_id == identity_id)
        self._put(character_name, current.model_copy(update=fields))

    async def patch_episode(self, episode_number: int, **fields: Any) -> None:
        self.episode_fields.setdefault(episode_number, {}).update(fields)


# --- run and apply ----------------------------------------------------------------------------------------------


def episode_planning_text(project_path: Path, project: Mapping[str, Any], episode: int) -> str:
    """The text the episode's script is planned from: its adaptation under screen mode, else its source slice."""
    path = project_path / script_source_relpath(project, episode)
    return path.read_text(encoding="utf-8") if path.is_file() else ""


async def plan_episode_identities(
    project_path: Path, project: Mapping[str, Any], episode: int, *, generate: Generate
) -> IdentityPlan:
    """Run DramaClaw's planner for one episode; nothing is written to the project."""
    from novelvideo import config as dramaclaw_config

    text = episode_planning_text(project_path, project, episode)
    if not text.strip():
        raise IdentityPlanningError(f"episode {episode} has no text to plan identities from")
    store = ProjectIdentityStore(project, {episode: text})
    model = text_function_model(generate)
    dramaclaw_config.set_text_model_factory(lambda _env, _default: model)
    plan = IdentityPlan(episode=episode)
    try:
        planner = IdentityPlanner(store)
        try:
            await planner.plan_single_episode(NovelEpisode(number=episode, title="", raw_content=text), plan.log.append)
        except (ValueError, RuntimeError) as exc:
            # The planner reports a pass that cannot complete (no cast, a missing default) as these.
            raise IdentityPlanningError(str(exc)) from exc
    finally:
        dramaclaw_config.set_text_model_factory(None)
    plan.identities = store.written
    fields = store.episode_fields.get(episode, {})
    for character, identity_id in (fields.get("identity_default_map") or {}).items():
        plan.defaults[character] = identity_id.removeprefix(f"{character}_")
    names = sorted((c.name for c in store.get_all_characters()), key=len, reverse=True)
    for identity_id in fields.get("identity_ids") or ():
        owner = next((n for n in names if str(identity_id).startswith(f"{n}_")), None)
        if owner is not None:
            plan.used.append(f"{owner}/{str(identity_id).removeprefix(f'{owner}_')}")
    return plan


def apply_identity_plan(project: dict[str, Any], plan: IdentityPlan) -> None:
    """Write the plan into a ``project.json`` dict (call inside ``ProjectManager.update_project``).

    A new identity becomes a derivative without a sheet; an existing one keeps its sheet and gets its new
    description only when the planner changed it (repairing a pending or polluted identity).
    """
    characters = project.get("characters")
    if not isinstance(characters, dict):
        raise IdentityPlanningError("project has no characters")
    for name, identities in plan.identities.items():
        key = resolve_asset_key(characters, name)
        entry = characters.get(key) if key is not None else None
        if not isinstance(entry, dict):
            raise IdentityPlanningError(f"character {name} is gone from the project")
        table = ensure_derivative_table(entry)
        for derivative, identity in identities.items():
            current_key = resolve_asset_key(table, derivative)
            current = table.get(current_key) if current_key is not None else None
            description = derivative_description(identity)
            if isinstance(current, dict):
                current[IDENTITY_FIELD] = dict(identity)
                if current.get("description") != description:
                    current["description"] = description
            else:
                table[derivative] = {"description": description, _SHEET_FIELD: "", IDENTITY_FIELD: dict(identity)}
        entry[DERIVATIVES_FIELD] = table
    episodes = project.get("episodes")
    for item in episodes if isinstance(episodes, list) else ():
        if isinstance(item, dict) and item.get("episode") == plan.episode:
            item[IDENTITY_DEFAULTS_FIELD] = dict(plan.defaults)
            return
    raise IdentityPlanningError(f"episode {plan.episode} is not in the project")


def plan_digest(plan: IdentityPlan) -> str:
    """A stable text of the plan, for logs and evidence."""
    return json.dumps(
        {"episode": plan.episode, "identities": plan.identities, "defaults": plan.defaults, "used": plan.used},
        ensure_ascii=False,
        sort_keys=True,
    )


# --- script planning ------------------------------------------------------------------------------------------------


def episode_identity_defaults(project: Mapping[str, Any], episode: int) -> dict[str, str] | None:
    """The episode's default derivative per character, or ``None`` when its identities were never planned."""
    for item in project.get("episodes") or ():
        if isinstance(item, Mapping) and item.get("episode") == episode:
            raw = item.get(IDENTITY_DEFAULTS_FIELD)
            if isinstance(raw, Mapping):
                return {str(k): str(v) for k, v in raw.items() if isinstance(v, str) and v}
            return None
    return None


def identity_defaults_block(defaults: Mapping[str, str]) -> str:
    """The script prompt's note on which look each character wears in this episode."""
    if not defaults:
        return ""
    lines = "\n".join(f"- {name} → {name}/{derivative}" for name, derivative in defaults.items())
    return (
        "## 本集角色造型\n\n"
        "以下角色在本集现实主线中的默认造型。分镜中该角色未换成其他造型时，characters_in_scene 写右侧的造型引用名"
        "（不要写本体名）；回忆、闪回或另一造型的分镜写候选中对应的造型引用名。utterances 的 speaker 仍写角色本体名。\n"
        f"{lines}\n"
    )


def apply_default_identities(scenes: list[Any], defaults: Mapping[str, str], field_name: str) -> int:
    """Name each bare character in a unit's ``field_name`` by the episode's default derivative; returns how many."""
    changed = 0
    for scene in scenes:
        names = scene.get(field_name) if isinstance(scene, dict) else None
        if not isinstance(names, list):
            continue
        for index, name in enumerate(names):
            if isinstance(name, str) and name in defaults:
                names[index] = f"{name}/{defaults[name]}"
                changed += 1
        # A unit naming the character twice (bare and by its look) keeps one reference.
        scene[field_name] = list(dict.fromkeys(names))
    return changed

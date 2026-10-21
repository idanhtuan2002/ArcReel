"""Structured outputs of the planning, review and packaging stages.

Field sets follow the donor surfaces in ``R2_STORY_DONOR_BASELINE.json`` (Novel Studio ``schemas.ts`` for seed,
bibles, chapter outline and scene beats; Shenbi memo sections for the chapter plan; Shenbi short-outline and
short-packaging), reduced to what a three-chapter Vietnamese short story uses and kept shallow, because every
string is generated under the no-CJK grammar by a small local model. Identifiers are never model output: keys
are derived from names by :func:`server.story_authoring.prompts.planning.entity_key`.
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, create_model


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SeedCharacter(_Out):
    name: str = Field(min_length=1)
    role: str = Field(min_length=1)
    relation_to_protagonist: str = Field(min_length=1)
    description: str = Field(min_length=1)
    goal: str = Field(min_length=1)


class SeedLocation(_Out):
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)


class StorySeed(_Out):
    working_title: str = Field(min_length=1)
    premise: str = Field(min_length=1)
    genre: str = Field(min_length=1)
    tone: str = Field(min_length=1)
    pov: str = Field(min_length=1)
    central_conflict: str = Field(min_length=1)
    ending_direction: str = Field(min_length=1)
    characters: list[SeedCharacter] = Field(min_length=2, max_length=5)
    locations: list[SeedLocation] = Field(min_length=1, max_length=4)


class StoryBibleOut(_Out):
    logline: str = Field(min_length=1)
    core_promise: str = Field(min_length=1)
    world_rules: list[str] = Field(min_length=1, max_length=6)
    major_conflicts: list[str] = Field(min_length=1, max_length=4)
    forbidden_contradictions: list[str] = Field(min_length=1, max_length=6)


class StyleBibleOut(_Out):
    narration_style: str = Field(min_length=1)
    sentence_rhythm: str = Field(min_length=1)
    emotional_texture: str = Field(min_length=1)
    dialogue_style: str = Field(min_length=1)
    forbidden_style: list[str] = Field(min_length=1, max_length=6)
    style_rules: list[str] = Field(min_length=3, max_length=8)


class OutlineChapter(_Out):
    core_task: str = Field(min_length=1)
    threads_advanced: str = Field(min_length=1)
    turning_point: str = Field(min_length=1)


class ShortOutline(_Out):
    story_arc: str = Field(min_length=1)
    opening: str = Field(min_length=1)
    confrontation: str = Field(min_length=1)
    resolution: str = Field(min_length=1)
    chapters: list[OutlineChapter] = Field(min_length=3, max_length=3)
    ending: str = Field(min_length=1)
    final_image: str = Field(min_length=1)


class OutlineReview(_Out):
    passed: bool
    problems: list[str] = Field(max_length=6)


class PlannedScene(_Out):
    summary: str = Field(min_length=1)
    location: str = Field(min_length=1)
    pov: str = Field(min_length=1)
    characters: list[str] = Field(min_length=1, max_length=5)
    beats: list[str] = Field(min_length=2, max_length=4)
    emotional_turn: str = Field(min_length=1)
    plot_function: str = Field(min_length=1)
    dialogue_required: bool


class ChapterPlan(_Out):
    chapter_goal: str = Field(min_length=1)
    reader_expectation: str = Field(min_length=1)
    withheld_cards: list[str] = Field(max_length=3)
    required_changes_by_end: list[str] = Field(min_length=1, max_length=3)
    do_not: list[str] = Field(max_length=4)
    scenes: list[PlannedScene] = Field(min_length=3, max_length=5)


def bound_chapter_plan(characters: Sequence[str], locations: Sequence[str]) -> type[ChapterPlan]:
    """The chapter plan of one story: a scene's POV and location are enums of the bible's names, so the grammar
    cannot emit others; the scene's other participants stay free text (minor or collective characters)."""
    pov = StrEnum("BoundPov", {f"v{i}": name for i, name in enumerate(characters)})
    location = StrEnum("BoundLocation", {f"v{i}": name for i, name in enumerate(locations)})
    scene = create_model("BoundPlannedScene", __base__=PlannedScene, pov=(pov, Field()), location=(location, Field()))
    return create_model(
        "BoundChapterPlan",
        __base__=ChapterPlan,
        scenes=(list[scene], Field(min_length=3, max_length=5)),
    )


class TitleCandidate(_Out):
    title: str = Field(min_length=1)
    kind: str = Field(min_length=1)


class SellingPoint(_Out):
    point: str = Field(min_length=1)
    evidence_quote: str = Field(min_length=1)


class Packaging(_Out):
    titles: list[TitleCandidate] = Field(min_length=3, max_length=5)
    blurbs: list[str] = Field(min_length=2, max_length=3)
    selling_points: list[SellingPoint] = Field(min_length=3, max_length=5)
    tags: list[str] = Field(min_length=5, max_length=10)

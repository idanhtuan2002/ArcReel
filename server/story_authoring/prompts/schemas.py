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
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, create_model


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SeedCharacter(_Out):
    name: str = Field(min_length=1)
    role: str = Field(min_length=1)
    relation_to_protagonist: str = Field(min_length=1)
    description: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    #: A generated seed always states both (``book.bound_seed``); seeds stored before they existed carry neither.
    gender: Literal["nam", "nữ"] | None = None
    #: The word the narration calls the character by besides the name ("anh", "cô", "bà", "ông", "cậu"...).
    address: str | None = Field(default=None, min_length=1, max_length=16)
    #: How the character speaks, and a real flaw that shapes their decisions (donor shenbi: a speech fingerprint
    #: for every major character). Seeds stored before these carry neither.
    voice: str | None = Field(default=None, min_length=1, max_length=120)
    flaw: str | None = Field(default=None, min_length=1, max_length=120)

    def locked_line(self) -> str:
        """What the narration may never change about the character: who they are to the protagonist, their gender
        and the word the narration calls them by, then the description."""
        identity = ""
        if self.gender is not None:
            identity = f"giới tính {self.gender}"
            if self.address:
                identity += f", lời kể gọi là “{self.address}”"
            identity += ". "
        line = f"{self.relation_to_protagonist}. {identity}{self.description}"
        if self.voice:
            line += f" Cách nói: {self.voice}."
        if self.flaw:
            line += f" Điểm yếu: {self.flaw}."
        return line


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
    #: A short story generates at most 5 and 4 (``book.bound_seed``); a book's cast adds its volumes' additions.
    characters: list[SeedCharacter] = Field(min_length=2, max_length=25)
    locations: list[SeedLocation] = Field(min_length=1, max_length=23)


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
    #: What stands in the protagonist's way, the choice they make, the question the reader carries to the next
    #: chapter (donor huohuo drama fields). A generated short outline states them; stored outlines carry none.
    obstacle: str | None = Field(default=None, min_length=1)
    choice: str | None = Field(default=None, min_length=1)
    ending_question: str | None = Field(default=None, min_length=1)


class ShortOutline(_Out):
    story_arc: str = Field(min_length=1)
    opening: str = Field(min_length=1)
    confrontation: str = Field(min_length=1)
    resolution: str = Field(min_length=1)
    #: Exactly three for a short story (``bound_short_outline``); a book part has its own chapter count.
    chapters: list[OutlineChapter] = Field(min_length=1, max_length=6)
    ending: str = Field(min_length=1)
    final_image: str = Field(min_length=1)


_DramaChapter = create_model(
    "DramaOutlineChapter",
    __base__=OutlineChapter,
    obstacle=(str, Field(min_length=1)),
    choice=(str, Field(min_length=1)),
    ending_question=(str, Field(min_length=1)),
)


def bound_short_outline() -> type[ShortOutline]:
    return create_model(
        "BoundShortOutline",
        __base__=ShortOutline,
        chapters=(list[_DramaChapter], Field(min_length=3, max_length=3)),
    )


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


SCENES_PER_CHAPTER_MAX = 5
CLOSING_HOOK_MAX = 200
#: Withheld cards and do-not items a generated chapter plan may carry.
PLAN_LIST_MAX = 2


class ChapterPlan(_Out):
    chapter_goal: str = Field(min_length=1)
    reader_expectation: str = Field(min_length=1)
    withheld_cards: list[str] = Field(max_length=3)
    required_changes_by_end: list[str] = Field(min_length=1, max_length=3)
    do_not: list[str] = Field(max_length=4)
    scenes: list[PlannedScene] = Field(min_length=3, max_length=SCENES_PER_CHAPTER_MAX)
    #: The sentence the chapter ends on, declared by the planner and written by the last scene (donor shenbi
    #: closing-hook beat). A generated plan states it; stored plans carry none.
    closing_hook: str | None = Field(default=None, min_length=1, max_length=CLOSING_HOOK_MAX)


def bound_chapter_plan(
    characters: Sequence[str], locations: Sequence[str], *, min_scenes: int = 3
) -> type[ChapterPlan]:
    """The chapter plan of one story: a scene's POV and location are enums of the bible's names, so the grammar
    cannot emit others; the scene's other participants stay free text (minor or collective characters)."""
    pov = StrEnum("BoundPov", {f"v{i}": name for i, name in enumerate(characters)})
    location = StrEnum("BoundLocation", {f"v{i}": name for i, name in enumerate(locations)})
    scene = create_model("BoundPlannedScene", __base__=PlannedScene, pov=(pov, Field()), location=(location, Field()))
    return create_model(
        "BoundChapterPlan",
        __base__=ChapterPlan,
        scenes=(list[scene], Field(min_length=min_scenes, max_length=SCENES_PER_CHAPTER_MAX)),
        # Fewer secrets and bans leave fewer ways for a small writer to contradict its own plan.
        withheld_cards=(list[str], Field(max_length=PLAN_LIST_MAX)),
        do_not=(list[str], Field(max_length=PLAN_LIST_MAX)),
        closing_hook=(str, Field(min_length=10, max_length=CLOSING_HOOK_MAX)),
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

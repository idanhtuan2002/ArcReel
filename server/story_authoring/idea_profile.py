"""A drawn project profile (ADR-0125): the idea and settings a run writes from when it was started without an idea.

The writer route returns a :class:`ProfileDraft`; :func:`settle_profile` turns it into a :class:`ProjectProfile`
whose every chosen value lies in a closed set. A value outside its set falls back to the run's seed and is named in
``defaulted``. The seed is derived from the start command id, so one run always asks with the same genre and angle;
the model never chooses the content safety level, caps, routes or grants.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from lib.project_manager import ProjectManager
from server.story_authoring.genre_packs import PACKS, GenrePack, pack_for

PROFILE_SCHEMA = "r2.story-project-profile.v1"

TONES: tuple[str, ...] = (
    "ấm áp",
    "nhẹ nhàng",
    "hồi hộp",
    "kịch tính",
    "u tối",
    "bi tráng",
    "lãng mạn",
    "hài hước",
)
AUDIENCES: tuple[str, ...] = ("phổ thông", "thanh thiếu niên", "người trưởng thành")
DEFAULT_AUDIENCE = "phổ thông"
BOOK_CHAPTERS_MIN, BOOK_CHAPTERS_MAX, DEFAULT_BOOK_CHAPTERS = 6, 120, 12
IDEA_MIN_CHARS, IDEA_MAX_CHARS = 40, 1200

#: Story angles a seed hands the writer so runs started together do not converge on one premise.
ANGLES: tuple[str, ...] = (
    "một bí mật bị giấu nhiều năm buộc phải lộ ra",
    "một cuộc trở về nơi nhân vật từng bỏ đi",
    "một lời hứa không thể giữ trọn",
    "một người lạ thay đổi cả một cộng đồng nhỏ",
    "một món đồ cũ mở ra một câu chuyện bị quên",
    "hai người buộc phải hợp tác dù không tin nhau",
    "một lựa chọn sai lầm phải trả giá dần dần",
    "một cuộc đua với thời gian",
    "một người bình thường bị cuốn vào chuyện lớn",
    "một mất mát buộc nhân vật làm lại từ đầu",
    "một lá thư, tin nhắn hay cuộc gọi đến muộn",
    "một quy tắc bị phá vỡ và hệ quả của nó",
)

_IdeaText = Annotated[str, StringConstraints(min_length=1, max_length=4000)]


class ProfileDraft(BaseModel):
    """What the writer route returns; every value is checked by :func:`settle_profile`."""

    model_config = ConfigDict(extra="ignore")

    title: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    idea: _IdeaText
    genre: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    tone: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    audience: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    chapters: int


class ProfileSeed(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    genre_pack: str
    angle: str
    tone: str


class ProjectProfile(BaseModel):
    """One run's drawn idea and settings; stored by digest in the project's story blob store."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_id: Literal["r2.story-project-profile.v1"] = PROFILE_SCHEMA
    title: Annotated[str, StringConstraints(min_length=1, max_length=200)]
    idea: Annotated[str, StringConstraints(min_length=IDEA_MIN_CHARS, max_length=IDEA_MAX_CHARS)]
    genre_pack: str
    tone: str
    audience: str
    book_chapters: Annotated[int, Field(ge=BOOK_CHAPTERS_MIN, le=BOOK_CHAPTERS_MAX)]
    seed: ProfileSeed
    #: Fields whose drawn value lay outside its closed set and were taken from the seed or a default.
    defaulted: tuple[str, ...] = ()

    def pack(self) -> GenrePack:
        return pack_by_id(self.genre_pack)


class ProfileRefused(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def pack_by_id(pack_id: str) -> GenrePack:
    for pack in PACKS:
        if pack.pack_id == pack_id:
            return pack
    raise KeyError(pack_id)


def _fold(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).casefold().split())


def profile_seed(command_id: str, *, genre_pack: str | None = None) -> ProfileSeed:
    """The genre, angle and tone a run asks with, derived from its start command id; a given pack wins."""
    digest = hashlib.sha256(command_id.encode("utf-8")).digest()
    pack = pack_by_id(genre_pack) if genre_pack is not None else PACKS[digest[0] % len(PACKS)]
    return ProfileSeed(
        genre_pack=pack.pack_id, angle=ANGLES[digest[1] % len(ANGLES)], tone=TONES[digest[2] % len(TONES)]
    )


def _genre(value: str) -> GenrePack | None:
    folded = _fold(value)
    for pack in PACKS:
        if folded in {pack.pack_id, _fold(pack.label)}:
            return pack
    return pack_for(value)


def _closed(value: str, choices: tuple[str, ...]) -> str | None:
    folded = _fold(value)
    return next((choice for choice in choices if _fold(choice) == folded), None)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text)).strip()


def settle_profile(
    draft: ProfileDraft,
    *,
    seed: ProfileSeed,
    genre_pack: str | None = None,
    book_chapters: int | None = None,
) -> ProjectProfile:
    """The profile with every value in its closed set; a Showrunner's ``genre_pack`` or ``book_chapters`` wins over
    the drawn one. An idea too short to write from refuses with ``IDEA_EMPTY``; a longer one is cut at a sentence."""
    defaulted: list[str] = []
    idea = _clean(draft.idea)
    if len(idea) < IDEA_MIN_CHARS:
        raise ProfileRefused("IDEA_EMPTY")
    if len(idea) > IDEA_MAX_CHARS:
        cut = idea[:IDEA_MAX_CHARS]
        end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
        idea = cut[: end + 1] if end >= IDEA_MIN_CHARS else cut
    if genre_pack is not None:
        pack = pack_by_id(genre_pack)
    else:
        drawn = _genre(draft.genre)
        if drawn is None:
            defaulted.append("genre_pack")
        pack = drawn or pack_by_id(seed.genre_pack)
    tone = _closed(draft.tone, TONES)
    if tone is None:
        defaulted.append("tone")
    audience = _closed(draft.audience, AUDIENCES)
    if audience is None:
        defaulted.append("audience")
    if book_chapters is not None:
        chapters = book_chapters
    elif BOOK_CHAPTERS_MIN <= draft.chapters <= BOOK_CHAPTERS_MAX:
        chapters = draft.chapters
    else:
        chapters = DEFAULT_BOOK_CHAPTERS
        defaulted.append("book_chapters")
    title = _clean(draft.title)[:200] or idea[:60]
    return ProjectProfile(
        title=title,
        idea=idea,
        genre_pack=pack.pack_id,
        tone=tone or seed.tone,
        audience=audience or DEFAULT_AUDIENCE,
        book_chapters=chapters,
        seed=seed,
        defaulted=tuple(defaulted),
    )


#: The project.json key that shows the drawn profile of the project's latest automatic story.
PROFILE_SETTING = "story_profile"


def profile_bytes(profile: ProjectProfile) -> bytes:
    return profile.model_dump_json().encode("utf-8")


def profile_pin(run_id: str) -> str:
    """The blob-store pin naming a run's profile."""
    return f"{PROFILE_SCHEMA}:{run_id}"


def profile_idea(profile: ProjectProfile) -> str:
    """The idea the brief is drafted from: the drawn idea with its tone and audience."""
    return f"{profile.idea}\n\nGiọng điệu: {profile.tone}. Độc giả: {profile.audience}."


def record_profile(projects: ProjectManager, project_name: str, run_id: str, profile: ProjectProfile) -> None:
    """Show the run's profile on its project; written once per run, so a replay changes nothing."""
    shown = {**profile.model_dump(mode="json", exclude={"schema_id", "seed"}), "run_id": run_id}

    def mutate(project: dict) -> None:
        project[PROFILE_SETTING] = shown

    if projects.load_project(project_name).get(PROFILE_SETTING) != shown:
        projects.update_project(project_name, mutate)


__all__ = [
    "ANGLES",
    "AUDIENCES",
    "BOOK_CHAPTERS_MAX",
    "BOOK_CHAPTERS_MIN",
    "DEFAULT_BOOK_CHAPTERS",
    "PROFILE_SCHEMA",
    "PROFILE_SETTING",
    "TONES",
    "ProfileDraft",
    "ProfileRefused",
    "ProfileSeed",
    "ProjectProfile",
    "pack_by_id",
    "profile_bytes",
    "profile_idea",
    "profile_pin",
    "profile_seed",
    "record_profile",
    "settle_profile",
]

"""Drawing a run's idea and settings on its writer route (ADR-0125 §2–§4).

One structured call returns a :class:`ProfileDraft`; it is settled into closed sets and compared with the ideas the
user's recent projects already hold. A near-duplicate is drawn once more with it named as an idea to avoid; a second
near-duplicate refuses with ``IDEA_DUPLICATE``. The calls are counted against the BRIEF step's own reservation, so a
draw never spends more than :data:`DRAW_ATTEMPTS` generations.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from uuid import uuid4

from lib.project_manager import ProjectManager
from server.story_authoring.audits import SafetyLevel, safety_instruction
from server.story_authoring.contracts import (
    AttemptKind,
    OutputMode,
    StoryDecoding,
    StoryFailureCode,
    StoryLimits,
    StoryModelSelection,
    StoryScope,
    StoryStepKind,
    StoryStepRequest,
)
from server.story_authoring.driver import PLANNING
from server.story_authoring.generation import AuthoringTextGateway, StoryStepError
from server.story_authoring.genre_packs import PACKS
from server.story_authoring.idea_profile import (
    AUDIENCES,
    BOOK_CHAPTERS_MAX,
    BOOK_CHAPTERS_MIN,
    PROFILE_SETTING,
    TONES,
    ProfileDraft,
    ProfileRefused,
    ProfileSeed,
    ProjectProfile,
    pack_by_id,
    settle_profile,
)

#: Generations one draw may spend: the first and the one retry after a near-duplicate.
DRAW_ATTEMPTS = 2
DRAW_MAX_OUTPUT_TOKENS = 1024
#: Word overlap (Jaccard) at or above which two ideas count as the same idea.
DUPLICATE_THRESHOLD = 0.5
#: Recent ideas named to the writer as ones to avoid.
AVOID_LIMIT = 20

DRAW_SYSTEM = (
    "Bạn là biên tập viên phát triển truyện tiếng Việt. Bạn nghĩ ra một ý tưởng truyện mới, cụ thể, có nhân vật, "
    "xung đột và điều đặt cược rõ ràng. Chỉ trả về JSON đúng schema, viết bằng tiếng Việt tự nhiên."
)


@dataclass(frozen=True)
class DrawnProfile:
    profile: ProjectProfile
    attempts: int


def _words(text: str) -> frozenset[str]:
    folded = unicodedata.normalize("NFC", text).casefold()
    return frozenset(word for word in re.findall(r"\w+", folded) if len(word) > 1)


def overlap(a: str, b: str) -> float:
    left, right = _words(a), _words(b)
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def near_duplicate(profile: ProjectProfile, avoid: Sequence[str]) -> str | None:
    """The first avoided idea the drawn one repeats (same title, or word overlap at or above the threshold)."""
    title = " ".join(_words(profile.title))
    for other in avoid:
        if overlap(profile.idea, other) >= DUPLICATE_THRESHOLD or (title and title == " ".join(_words(other))):
            return other
    return None


def recent_ideas(projects: ProjectManager, *, exclude: str, limit: int = AVOID_LIMIT) -> list[str]:
    """The ideas of the most recently changed projects, newest first: a drawn profile's title and idea, else the
    project's title."""
    changed: list[tuple[float, str]] = []
    for name in projects.list_projects():
        if name == exclude:
            continue
        try:
            changed.append(((projects.get_project_path(name) / "project.json").stat().st_mtime, name))
        except (OSError, ValueError):
            continue
    ideas: list[str] = []
    for _mtime, name in sorted(changed, reverse=True):
        if len(ideas) >= limit:
            break
        try:
            project = projects.load_project(name)
        except (FileNotFoundError, ValueError):
            continue
        shown = project.get(PROFILE_SETTING)
        if isinstance(shown, dict) and isinstance(shown.get("idea"), str):
            ideas.append(f"{shown.get('title') or ''}: {shown['idea']}".strip(": "))
        elif isinstance(project.get("title"), str) and project["title"].strip():
            ideas.append(project["title"].strip())
    return ideas


def draw_prompt(
    seed: ProfileSeed,
    *,
    avoid: Sequence[str],
    safety: SafetyLevel,
    genre_pack: str | None = None,
    book_chapters: int | None = None,
) -> str:
    genres = "; ".join(f"{pack.label}" for pack in PACKS)
    if genre_pack is not None:
        genre_rule = f"- genre: đúng thể loại {pack_by_id(genre_pack).label}."
    else:
        genre_rule = (
            f"- genre: một trong các thể loại sau, ghi nguyên văn: {genres}. Nếu không có lý do khác, ưu tiên "
            f"{pack_by_id(seed.genre_pack).label}."
        )
    length = (
        f"- chapters: {book_chapters}."
        if book_chapters is not None
        else f"- chapters: số chương của truyện, từ {BOOK_CHAPTERS_MIN} đến {BOOK_CHAPTERS_MAX}, vừa với ý tưởng."
    )
    avoided = "\n".join(f"- {text}" for text in avoid[:AVOID_LIMIT]) or "- (chưa có)"
    return f"""Nghĩ ra MỘT ý tưởng truyện dài mới, đọc được như một sản phẩm thương mại hoàn chỉnh.

Yêu cầu:
- title: tên truyện ngắn gọn, gợi tò mò.
- idea: 3–6 câu: nhân vật chính là ai, họ muốn gì, điều gì cản họ, cái giá nếu thất bại, và một chi tiết riêng khiến
  truyện không giống truyện khác. Không viết lời mở đầu hay giải thích.
{genre_rule}
- tone: một trong: {"; ".join(TONES)}.
- audience: một trong: {"; ".join(AUDIENCES)}.
{length}
- Góc khai thác gợi ý: {seed.angle}.
- Mức nội dung của dự án: {safety_instruction(safety)}

Các ý tưởng đã có, KHÔNG được lặp lại hay na ná (nhân vật, tình huống, cú ngoặt):
{avoided}"""


class _DrawSink:
    """An in-memory attempt ledger for the draw: it refuses past its generation bound; usage is settled by the
    production run's own reservation for the BRIEF step."""

    def __init__(self, generations: int) -> None:
        self._left = generations

    async def reserve(
        self,
        *,
        scope: StoryScope,
        step_id: str,
        kind: AttemptKind,
        request_digest: str,
        reserved_input_tokens: int,
        reserved_output_tokens: int,
    ) -> str:
        if kind is AttemptKind.GENERATE:
            if self._left <= 0:
                raise StoryStepError(StoryFailureCode.BUDGET_EXHAUSTED, "the draw spent its calls", step_id=step_id)
            self._left -= 1
        return uuid4().hex

    async def dispatched(self, attempt_id: str) -> None:
        return None

    async def completed(
        self, attempt_id: str, *, input_tokens: int, output_tokens: int, done_reason: str, duration_ms: int
    ) -> None:
        return None

    async def failed(
        self,
        attempt_id: str,
        *,
        code: StoryFailureCode,
        detail: str,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        done_reason: str | None = None,
        duration_ms: int | None = None,
    ) -> None:
        return None

    async def unknown(self, attempt_id: str, *, detail: str) -> None:
        return None


def _sampling_seed(key: str) -> int:
    return int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:8], 16) % (2**31)


GatewayFor = Callable[[_DrawSink], Awaitable[AuthoringTextGateway]]


async def draw_profile(
    *,
    gateway_for: GatewayFor,
    selection: StoryModelSelection,
    limits: StoryLimits,
    scope: StoryScope,
    draw_key: str,
    seed: ProfileSeed,
    avoid: Sequence[str],
    safety: SafetyLevel,
    genre_pack: str | None = None,
    book_chapters: int | None = None,
) -> DrawnProfile:
    """Draw and settle a profile; ``IDEA_DUPLICATE`` after a second near-duplicate, ``IDEA_DRAW_FAILED`` when the
    route returns no usable draft."""
    gateway = await gateway_for(_DrawSink(DRAW_ATTEMPTS))
    avoided = list(avoid)
    for attempt in range(1, DRAW_ATTEMPTS + 1):
        request = StoryStepRequest(
            step_id=f"profile-draw-{attempt}",
            kind=StoryStepKind.SEED,
            context_digest=seed.model_dump_json(),
            selection=selection,
            system_prompt=DRAW_SYSTEM,
            prompt=draw_prompt(seed, avoid=avoided, safety=safety, genre_pack=genre_pack, book_chapters=book_chapters),
            output_mode=OutputMode.STRUCTURED,
            response_model=ProfileDraft,
            decoding=StoryDecoding.model_validate({**PLANNING, "seed": _sampling_seed(f"{draw_key}:{attempt}")}),
            max_output_tokens=min(DRAW_MAX_OUTPUT_TOKENS, limits.max_output_tokens),
        )
        try:
            output = await gateway.generate(scope=scope, request=request)
            draft = ProfileDraft.model_validate_json(output.text)
        except (StoryStepError, ValueError) as error:
            raise ProfileRefused("IDEA_DRAW_FAILED") from error
        profile = settle_profile(draft, seed=seed, genre_pack=genre_pack, book_chapters=book_chapters)
        repeated = near_duplicate(profile, avoided)
        if repeated is None:
            return DrawnProfile(profile=profile, attempts=attempt)
        avoided.insert(0, f"{profile.title}: {profile.idea}")
    raise ProfileRefused("IDEA_DUPLICATE")


__all__ = [
    "AVOID_LIMIT",
    "DRAW_ATTEMPTS",
    "DRAW_MAX_OUTPUT_TOKENS",
    "DUPLICATE_THRESHOLD",
    "DrawnProfile",
    "draw_profile",
    "draw_prompt",
    "near_duplicate",
    "overlap",
    "recent_ideas",
]

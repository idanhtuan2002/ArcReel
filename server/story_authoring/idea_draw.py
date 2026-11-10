"""Drawing a run's idea and settings on its writer route (ADR-0125 §2–§4).

One structured call returns a :class:`ProfileDraft`; it is settled into closed sets and compared with the ideas the
user's recent projects already hold. A near-duplicate is drawn once more with it named as an idea to avoid; a second
near-duplicate refuses with ``IDEA_DUPLICATE``. The calls are counted against the BRIEF step's own reservation, so a
draw never spends more than :data:`DRAW_ATTEMPTS` generations.
"""

from __future__ import annotations

import hashlib
import math
import re
import time
import unicodedata
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from uuid import uuid4

from lib.project_manager import ProjectManager
from server.story_authoring.audits import SafetyLevel
from server.story_authoring.contracts import (
    AttemptKind,
    CloudPriceBounds,
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

_MINORS = "Tuyệt đối không có nội dung tình dục hay gợi dục liên quan người dưới 18 tuổi."
#: What the drawn idea may contain at each content safety level (ADR-0121); the story's chapters are audited at
#: the same level.
DRAW_SAFETY: dict[SafetyLevel, str] = {
    "strict": _MINORS + " Truyện cho độc giả từ 12 tuổi: không bạo lực chi tiết, không cảnh rùng rợn, không gợi dục.",
    "standard": _MINORS + " Không tình dục trần trụi, không bạo lực máu me quá mức, không kích động thù ghét.",
    "mature": _MINORS + " Truyện cho người lớn; không hướng dẫn tự hại hay chế tạo vũ khí, chất nổ, ma túy.",
    "off": _MINORS,
}

DRAW_SYSTEM = (
    "Bạn là biên tập viên phát triển truyện tiếng Việt. Bạn nghĩ ra một ý tưởng truyện mới, cụ thể, có nhân vật, "
    "xung đột và điều đặt cược rõ ràng. Chỉ trả về JSON đúng schema, viết bằng tiếng Việt tự nhiên."
)


@dataclass(frozen=True)
class DrawnProfile:
    profile: ProjectProfile
    attempts: int
    #: What the draw spent: every count and generation call, their cost and the wall time.
    usage: DrawUsage


@dataclass(frozen=True)
class AvoidedIdea:
    title: str
    idea: str

    def line(self) -> str:
        return f"{self.title}: {self.idea}" if self.title and self.idea else self.title or self.idea


def _words(text: str) -> frozenset[str]:
    folded = unicodedata.normalize("NFC", text).casefold()
    return frozenset(word for word in re.findall(r"\w+", folded) if len(word) > 1)


def overlap(a: str, b: str) -> float:
    left, right = _words(a), _words(b)
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def near_duplicate(profile: ProjectProfile, avoid: Sequence[AvoidedIdea]) -> AvoidedIdea | None:
    """The first avoided idea the drawn one repeats: the same title, or ideas whose word overlap is at or above the
    threshold."""
    title = _words(profile.title)
    for other in avoid:
        if title and title == _words(other.title):
            return other
        if other.idea and overlap(profile.idea, other.idea) >= DUPLICATE_THRESHOLD:
            return other
    return None


def recent_ideas(projects: ProjectManager, *, exclude: str, limit: int = AVOID_LIMIT) -> list[AvoidedIdea]:
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
    ideas: list[AvoidedIdea] = []
    for _mtime, name in sorted(changed, reverse=True):
        if len(ideas) >= limit:
            break
        try:
            project = projects.load_project(name)
        except (FileNotFoundError, ValueError):
            continue
        shown = project.get(PROFILE_SETTING)
        if isinstance(shown, dict) and isinstance(shown.get("idea"), str):
            title = shown.get("title")
            ideas.append(AvoidedIdea(title=title.strip() if isinstance(title, str) else "", idea=shown["idea"].strip()))
        elif isinstance(project.get("title"), str) and project["title"].strip():
            ideas.append(AvoidedIdea(title=project["title"].strip(), idea=""))
    return ideas


def draw_prompt(
    seed: ProfileSeed,
    *,
    avoid: Sequence[AvoidedIdea],
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
    avoided = "\n".join(f"- {other.line()}" for other in avoid[:AVOID_LIMIT]) or "- (chưa có)"
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
- Giới hạn nội dung: {DRAW_SAFETY[safety]}

Các ý tưởng đã có, KHÔNG được lặp lại hay na ná (nhân vật, tình huống, cú ngoặt):
{avoided}"""


@dataclass(frozen=True)
class DrawUsage:
    model_calls: int
    cost_minor_units: int
    runtime_seconds: int


class _DrawSink:
    """An in-memory attempt ledger for the draw: it refuses past its generation bound and counts every call it
    reserves, with its cost on a priced route (an attempt whose outcome is unknown costs what it reserved)."""

    def __init__(self, generations: int, prices: CloudPriceBounds | None) -> None:
        self._left = generations
        self._prices = prices
        self._reserved: dict[str, tuple[int, int]] = {}
        self.calls = 0
        self.cost = 0

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
        del scope, request_digest
        if kind is AttemptKind.GENERATE:
            if self._left <= 0:
                raise StoryStepError(StoryFailureCode.BUDGET_EXHAUSTED, "the draw spent its calls", step_id=step_id)
            self._left -= 1
        attempt = uuid4().hex
        self._reserved[attempt] = (reserved_input_tokens, reserved_output_tokens)
        self.calls += 1
        return attempt

    def _charge(self, attempt_id: str, input_tokens: int | None, output_tokens: int | None) -> None:
        reserved = self._reserved.pop(attempt_id, (0, 0))
        if self._prices is not None:
            used_in = reserved[0] if input_tokens is None else input_tokens
            used_out = reserved[1] if output_tokens is None else output_tokens
            self.cost += self._prices.minor_units(used_in, used_out)

    async def dispatched(self, attempt_id: str) -> None:
        return None

    async def completed(
        self, attempt_id: str, *, input_tokens: int, output_tokens: int, done_reason: str, duration_ms: int
    ) -> None:
        del done_reason, duration_ms
        self._charge(attempt_id, input_tokens, output_tokens)

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
        del code, detail, done_reason, duration_ms
        self._charge(attempt_id, input_tokens, output_tokens)

    async def unknown(self, attempt_id: str, *, detail: str) -> None:
        del detail
        self._charge(attempt_id, None, None)


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
    avoid: Sequence[AvoidedIdea],
    safety: SafetyLevel,
    genre_pack: str | None = None,
    book_chapters: int | None = None,
) -> DrawnProfile:
    """Draw and settle a profile; ``IDEA_DUPLICATE`` after a second near-duplicate, ``IDEA_DRAW_FAILED`` when the
    route returns no usable draft."""
    sink = _DrawSink(DRAW_ATTEMPTS, limits.cloud_prices)
    gateway = await gateway_for(sink)
    started = time.monotonic()

    def usage() -> DrawUsage:
        return DrawUsage(
            model_calls=sink.calls, cost_minor_units=sink.cost, runtime_seconds=math.ceil(time.monotonic() - started)
        )

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
            return DrawnProfile(profile=profile, attempts=attempt, usage=usage())
        avoided.insert(0, AvoidedIdea(title=profile.title, idea=profile.idea))
    raise ProfileRefused("IDEA_DUPLICATE")


__all__ = [
    "AVOID_LIMIT",
    "DRAW_ATTEMPTS",
    "DRAW_MAX_OUTPUT_TOKENS",
    "DRAW_SAFETY",
    "DUPLICATE_THRESHOLD",
    "AvoidedIdea",
    "DrawUsage",
    "DrawnProfile",
    "draw_profile",
    "draw_prompt",
    "near_duplicate",
    "overlap",
    "recent_ideas",
]

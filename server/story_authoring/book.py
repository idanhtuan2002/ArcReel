"""A long story written part by part from one book plan and one book memory (ADR-0116).

A book spec fixes the total chapter count, the syllables per chapter and the chapters per part. Parts are story
runs; volumes are narrative units with chapter ranges computed here, never by the model. The book plan holds the
skeleton and one row per chapter (role, hooks planted and paid); hook ids are assigned in code. The book memory
is a deterministic fold of the chapter digests and part summaries extracted from accepted text, bounded by fixed
windows so it does not grow with the book. Donor surfaces: shenbi ``story-architecture`` (chapter budget and
volume count), ``foreshadowing-lifecycle`` (hook ids, max distance) and ``memory-distill`` (bounded window);
huohuo phased outline (chunks of 15, gap patch), ``chapter_role`` and the plot ledger; novel-studio (only
accepted chapters write memory).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, create_model

from lib.text_attestation import named_in
from server.story_authoring.prompts.schemas import OutlineChapter, SeedCharacter, SeedLocation, ShortOutline, StorySeed

VOLUME_CHAPTERS = 12
MAX_VOLUMES = 5
ROWS_PER_CALL = 8
HOOK_MAX_DISTANCE = 12
HOOK_SILENCE = 8
SUMMARY_WINDOW = 8
PART_SUMMARY_WINDOW = 6
TAIL_CHARS = 1500
BOOK_SEED_CHARACTERS = 10
BOOK_SEED_LOCATIONS = 8
PLAN_REVISIONS = 3


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BookSpec(_Frozen):
    chapters: int = Field(ge=6, le=120)
    chapter_syllables: int = Field(default=3000, ge=2000, le=5000)
    part_chapters: int = Field(default=5, ge=3, le=6)

    def parts(self) -> tuple[tuple[int, int], ...]:
        """``(first chapter, chapter count)`` per part; the remainder goes to the first parts."""
        count = math.ceil(self.chapters / self.part_chapters)
        base, extra = divmod(self.chapters, count)
        parts, first = [], 1
        for k in range(count):
            size = base + (1 if k < extra else 0)
            parts.append((first, size))
            first += size
        return tuple(parts)

    def volumes(self) -> tuple[tuple[int, int], ...]:
        """``(first chapter, last chapter)`` per volume: ``clamp(round(chapters / 12), 1, 5)`` even volumes."""
        count = max(1, min(MAX_VOLUMES, round(self.chapters / VOLUME_CHAPTERS)))
        base, extra = divmod(self.chapters, count)
        volumes, first = [], 1
        for k in range(count):
            size = base + (1 if k < extra else 0)
            volumes.append((first, first + size - 1))
            first += size
        return tuple(volumes)


class BookPart(_Frozen):
    """The part of a book a run writes; parts after the first read the book state the previous part committed."""

    spec: BookSpec
    part: int = Field(default=1, ge=1)
    state_digest: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")

    @property
    def first_chapter(self) -> int:
        return self.spec.parts()[self.part - 1][0]

    @property
    def chapters(self) -> int:
        return self.spec.parts()[self.part - 1][1]

    @property
    def is_last(self) -> bool:
        return self.part == len(self.spec.parts())


class ChapterRole(StrEnum):
    SETUP = "setup"
    ADVANCE = "advance"
    TURN = "turn"
    PAYOFF = "payoff"
    CLIMAX = "climax"
    BREATH = "breath"


ENDING_ROLES = frozenset({ChapterRole.CLIMAX, ChapterRole.PAYOFF})


# --- model outputs -------------------------------------------------------------------------------------


class VolumeEntry(_Out):
    title: str = Field(min_length=1, max_length=120)
    objective: str = Field(min_length=1, max_length=400)
    key_results: list[str] = Field(min_length=3, max_length=5)
    turning_point: str = Field(min_length=1, max_length=400)
    new_characters: list[SeedCharacter] = Field(max_length=3)
    new_locations: list[SeedLocation] = Field(max_length=3)


class BookOutline(_Out):
    logline: str = Field(min_length=1, max_length=400)
    story_arc: str = Field(min_length=1, max_length=600)
    central_question: str = Field(min_length=1, max_length=300)
    ending: str = Field(min_length=1, max_length=800)
    final_image: str = Field(min_length=1, max_length=300)
    volumes: list[VolumeEntry] = Field(min_length=1, max_length=MAX_VOLUMES)


class BookRow(_Out):
    core_task: str = Field(min_length=1, max_length=300)
    threads_advanced: str = Field(min_length=1, max_length=200)
    turning_point: str = Field(min_length=1, max_length=200)
    role: ChapterRole
    plants: list[str] = Field(max_length=2)
    payoffs: list[str] = Field(max_length=2)


class BookRows(_Out):
    rows: list[BookRow] = Field(min_length=1, max_length=ROWS_PER_CALL)


class CharacterNow(_Out):
    name: str = Field(min_length=1, max_length=60)
    state: str = Field(min_length=1, max_length=400)


class HookOp(_Out):
    hook: str = Field(min_length=1)
    op: Literal["touched", "resolved"]


class ChapterDigest(_Out):
    summary: str = Field(min_length=1, max_length=600)
    events: list[str] = Field(min_length=1, max_length=6)
    characters: list[CharacterNow] = Field(max_length=10)
    hooks: list[HookOp] = Field(max_length=6)
    new_threads: list[str] = Field(max_length=3)
    time_place: str = Field(min_length=1, max_length=200)


class PartSummary(_Out):
    summary: str = Field(min_length=1, max_length=1200)


def _enum(name: str, values: Sequence[str]) -> Any:
    return StrEnum(name, {f"v{i}": value for i, value in enumerate(values)})


def bound_seed(characters: int, locations: int) -> type[StorySeed]:
    """The seed a run generates: a short story keeps two to five characters and one to four places."""
    return create_model(
        "BoundStorySeed",
        __base__=StorySeed,
        characters=(list[SeedCharacter], Field(min_length=2, max_length=characters)),
        locations=(list[SeedLocation], Field(min_length=1, max_length=locations)),
    )


def bound_book_outline(volumes: int) -> type[BookOutline]:
    return create_model(
        "BoundBookOutline",
        __base__=BookOutline,
        volumes=(list[VolumeEntry], Field(min_length=volumes, max_length=volumes)),
    )


def next_hook_ids(hooks: Sequence[Hook], count: int) -> list[str]:
    """The ids the next ``count`` plants will get, so a row can pay a hook planted earlier in the same call."""
    return [f"h{len(hooks) + 1 + j}" for j in range(count)]


def bound_rows(count: int, open_hooks: Sequence[str]) -> type[BookRows]:
    """Exactly ``count`` rows whose payoffs name only the given hook ids (open ones and those planted in the same
    call); a payoff before its plant is a plan problem."""
    if open_hooks:
        hook = _enum("OpenHook", list(open_hooks))
        payoffs: Any = (list[hook], Field(max_length=2))
    else:
        payoffs = (list[str], Field(max_length=0))
    row = create_model("BoundBookRow", __base__=BookRow, payoffs=payoffs)
    return create_model("BoundBookRows", __base__=BookRows, rows=(list[row], Field(min_length=count, max_length=count)))


def bound_digest(hooks: Sequence[str]) -> type[ChapterDigest]:
    """A chapter digest whose hook operations name only known hook ids."""
    if hooks:
        hook = _enum("KnownHook", list(hooks))
        op = create_model("BoundHookOp", __base__=HookOp, hook=(hook, Field()))
        ops: Any = (list[op], Field(max_length=6))
    else:
        ops = (list[HookOp], Field(max_length=0))
    return create_model("BoundChapterDigest", __base__=ChapterDigest, hooks=ops)


# --- the plan ------------------------------------------------------------------------------------------


class Hook(_Frozen):
    hook_id: str
    text: str
    planted: int
    due: int
    paid: int | None = None


class PlannedRow(_Frozen):
    chapter: int
    core_task: str
    threads_advanced: str
    turning_point: str
    role: ChapterRole
    plants: tuple[str, ...] = ()
    payoffs: tuple[str, ...] = ()


class BookPlan(_Frozen):
    outline: dict[str, Any]
    rows: tuple[PlannedRow, ...]
    hooks: tuple[Hook, ...]

    def book_outline(self) -> BookOutline:
        return BookOutline.model_validate(self.outline)


def add_rows(
    rows: Sequence[PlannedRow], hooks: Sequence[Hook], new: Sequence[BookRow], *, first: int, total: int
) -> tuple[tuple[PlannedRow, ...], tuple[Hook, ...]]:
    """Append generated rows from chapter ``first``: plants get the next ids ``h<n>``, payoffs close open hooks."""
    ledger = {h.hook_id: h for h in hooks}
    added = list(rows)
    for offset, row in enumerate(new):
        chapter = first + offset
        plants: list[str] = []
        for text in row.plants:
            hook_id = f"h{len(ledger) + 1}"
            ledger[hook_id] = Hook(
                hook_id=hook_id, text=text, planted=chapter, due=min(chapter + HOOK_MAX_DISTANCE, total)
            )
            plants.append(hook_id)
        payoffs = [str(getattr(p, "value", p)) for p in row.payoffs]
        for hook_id in payoffs:
            if hook_id in ledger and ledger[hook_id].paid is None and ledger[hook_id].planted < chapter:
                ledger[hook_id] = ledger[hook_id].model_copy(update={"paid": chapter})
        added.append(
            PlannedRow(
                chapter=chapter,
                core_task=row.core_task,
                threads_advanced=row.threads_advanced,
                turning_point=row.turning_point,
                role=row.role,
                plants=tuple(plants),
                payoffs=tuple(payoffs),
            )
        )
    return tuple(added), tuple(ledger.values())


def open_hook_ids(hooks: Sequence[Hook]) -> list[str]:
    return [h.hook_id for h in hooks if h.paid is None]


def plan_problems(rows: Sequence[PlannedRow], hooks: Sequence[Hook], *, total: int) -> list[str]:
    """Code checks of the plan so far: role rotation, the ending's role, hooks paid by their due chapter, a
    payoff after its plant."""
    problems = [
        f"chương {rows[i - 2].chapter}–{rows[i].chapter} cùng vai trò '{rows[i].role.value}': không để ba chương "
        "liền nhau cùng vai trò"
        for i in range(2, len(rows))
        if rows[i].role == rows[i - 1].role == rows[i - 2].role
    ]
    last = rows[-1].chapter if rows else 0
    if last == total and rows[-1].role not in ENDING_ROLES:
        problems.append(f"chương cuối {total} phải có vai trò 'climax' hoặc 'payoff'")
    problems.extend(
        f"phục bút {hook.hook_id} (“{hook.text}”, cài ở chương {hook.planted}) phải được giải muộn nhất ở chương "
        f"{hook.due}"
        for hook in hooks
        if hook.paid is None and hook.due <= last
    )
    planted = {h.hook_id: h.planted for h in hooks}
    problems.extend(
        f"chương {row.chapter} giải {hook_id} nhưng phục bút này chưa được cài ở một chương trước đó"
        for row in rows
        for hook_id in row.payoffs
        if planted.get(hook_id, row.chapter) >= row.chapter
    )
    return problems


def merged_seed(seed: StorySeed, outline: BookOutline) -> StorySeed:
    """The book's cast: the seed's characters and places, then each volume's additions in volume order (names
    already present are skipped), so entity keys stay the same in every part."""
    characters = list(seed.characters)
    locations = list(seed.locations)
    for volume in outline.volumes:
        known = {c.name for c in characters}
        characters.extend(c for c in volume.new_characters if c.name not in known)
        places = {loc.name for loc in locations}
        locations.extend(loc for loc in volume.new_locations if loc.name not in places)
    return seed.model_copy(update={"characters": characters, "locations": locations})


def part_outline(plan: BookPlan, part: BookPart) -> ShortOutline:
    """The part's outline: its rows as chapters; the part ends on its last row's turning point, the book's last
    part on the book's ending."""
    outline = plan.book_outline()
    rows = [r for r in plan.rows if part.first_chapter <= r.chapter < part.first_chapter + part.chapters]
    volume = _volume_of(part.spec, part.first_chapter)
    entry = outline.volumes[volume]
    return ShortOutline.model_validate(
        {
            "story_arc": outline.story_arc,
            "opening": entry.objective,
            "confrontation": "; ".join(entry.key_results),
            "resolution": outline.ending if part.is_last else rows[-1].turning_point,
            "chapters": [
                OutlineChapter(
                    core_task=r.core_task, threads_advanced=r.threads_advanced, turning_point=r.turning_point
                ).model_dump()
                for r in rows
            ],
            "ending": outline.ending if part.is_last else rows[-1].turning_point,
            "final_image": outline.final_image if part.is_last else rows[-1].turning_point,
        }
    )


def _volume_of(spec: BookSpec, chapter: int) -> int:
    for index, (first, last) in enumerate(spec.volumes()):
        if first <= chapter <= last:
            return index
    raise ValueError(f"chapter {chapter} outside the book")


# --- the memory ----------------------------------------------------------------------------------------


class HookStatus(_Frozen):
    hook_id: str
    text: str
    planted: int
    due: int
    status: Literal["planted", "touched", "resolved"] = "planted"
    last_touched: int

    def overdue(self, chapter: int) -> bool:
        return self.status != "resolved" and (chapter - self.last_touched > HOOK_SILENCE or chapter > self.due)


class BookMemory(_Frozen):
    chapters_done: int = 0
    chapter_summaries: tuple[tuple[int, str], ...] = ()
    part_summaries: tuple[tuple[int, str], ...] = ()
    characters: tuple[tuple[str, str, int], ...] = ()
    hooks: tuple[HookStatus, ...] = ()
    tail: str = ""

    def character_state(self, name: str) -> str | None:
        for known, state, _ in self.characters:
            if known == name:
                return state
        return None


def initial_memory(plan: BookPlan) -> BookMemory:
    return BookMemory(
        hooks=tuple(
            HookStatus(hook_id=h.hook_id, text=h.text, planted=h.planted, due=h.due, last_touched=h.planted)
            for h in plan.hooks
        )
    )


def attest_digest(digest: ChapterDigest, text: str) -> ChapterDigest:
    """Keep only the characters the chapter writes by name, as whole words (ADR-0115 attestation)."""
    kept = [c for c in digest.characters if named_in(c.name, text)]
    return digest.model_copy(update={"characters": kept})


def fold(
    memory: BookMemory,
    digests: Sequence[tuple[int, ChapterDigest]],
    *,
    part: int,
    part_summary: str,
    tail: str,
) -> BookMemory:
    """The memory after a part: summaries windowed, character states replaced, hooks updated, new threads opened
    as ``u<n>`` hooks due ``HOOK_SILENCE`` chapters later."""
    summaries = list(memory.chapter_summaries)
    characters = {name: (state, chapter) for name, state, chapter in memory.characters}
    hooks = {h.hook_id: h for h in memory.hooks}
    unplanned = sum(1 for h in hooks if h.startswith("u"))
    done = memory.chapters_done
    for chapter, digest in digests:
        summaries.append((chapter, digest.summary))
        for now in digest.characters:
            characters[now.name] = (now.state, chapter)
        for op in digest.hooks:
            hook_id = str(getattr(op.hook, "value", op.hook))
            if hook_id in hooks and hooks[hook_id].status != "resolved":
                hooks[hook_id] = hooks[hook_id].model_copy(update={"status": op.op, "last_touched": chapter})
        for thread in digest.new_threads:
            unplanned += 1
            hook_id = f"u{unplanned}"
            hooks[hook_id] = HookStatus(
                hook_id=hook_id, text=thread, planted=chapter, due=chapter + HOOK_SILENCE, last_touched=chapter
            )
        done = max(done, chapter)
    return BookMemory(
        chapters_done=done,
        chapter_summaries=tuple(summaries[-SUMMARY_WINDOW:]),
        part_summaries=(
            (*memory.part_summaries, (part, part_summary))[-PART_SUMMARY_WINDOW:]
            if part_summary
            else memory.part_summaries
        ),
        characters=tuple((name, state, chapter) for name, (state, chapter) in characters.items()),
        hooks=tuple(hooks.values()),
        tail=tail[-TAIL_CHARS:] if tail else memory.tail,
    )


def due_hooks(memory: BookMemory, plan: BookPlan, chapter: int) -> list[HookStatus]:
    """Hooks this chapter must touch: planned to be paid here, or overdue."""
    planned = {h for r in plan.rows if r.chapter == chapter for h in r.payoffs}
    return [h for h in memory.hooks if h.status != "resolved" and (h.hook_id in planned or h.overdue(chapter))]


def memory_block(
    memory: BookMemory, plan: BookPlan, *, chapter: int, names: Sequence[str] = (), recent: int = 3
) -> str:
    """The book memory as labelled Vietnamese text for planning and drafting prompts."""
    lines = ["[Bộ nhớ truyện — những gì đã xảy ra trong các phần trước]"]
    if memory.part_summaries:
        lines.append("Tóm tắt các phần trước:")
        lines.extend(f"- Phần {p}: {text}" for p, text in memory.part_summaries)
    window = [(c, s) for c, s in memory.chapter_summaries if c < chapter][-recent:]
    if window:
        lines.append("Các chương gần nhất:")
        lines.extend(f"- Chương {c}: {s}" for c, s in window)
    states = [(n, s) for n, s, _ in memory.characters if not names or n in names]
    if states:
        lines.append("Trạng thái hiện tại của nhân vật:")
        lines.extend(f"- {n}: {s}" for n, s in states)
    due = due_hooks(memory, plan, chapter)
    if due:
        lines.append("Phục bút / mạch còn mở chương này phải chạm tới hoặc giải:")
        lines.extend(f"- {h.hook_id}: {h.text} (cài ở chương {h.planted})" for h in due)
    return "\n".join(lines) if len(lines) > 1 else ""


class BookState(_Frozen):
    """What a part commits for the next one: the plan, the cast, the bibles and the memory after the part."""

    spec: BookSpec
    parts_done: int
    title: str
    plan: BookPlan
    seed: dict[str, Any]
    story_bible: dict[str, Any]
    style_bible: dict[str, Any]
    memory: BookMemory


__all__ = [
    "BookMemory",
    "BookOutline",
    "BookPart",
    "BookPlan",
    "BookRow",
    "BookRows",
    "BookSpec",
    "BookState",
    "ChapterDigest",
    "ChapterRole",
    "Hook",
    "HookStatus",
    "PartSummary",
    "PlannedRow",
    "add_rows",
    "attest_digest",
    "bound_book_outline",
    "bound_digest",
    "bound_rows",
    "bound_seed",
    "due_hooks",
    "fold",
    "initial_memory",
    "memory_block",
    "merged_seed",
    "open_hook_ids",
    "part_outline",
    "plan_problems",
]

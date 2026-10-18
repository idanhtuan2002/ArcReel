"""Seed, story bible, style bible and chapter-plan prompts, and the deterministic name-to-key mapping.

Donor surfaces (``R2_STORY_DONOR_BASELINE.json``):

- S02 Novel Studio ``src/lib/ai/prompts.ts`` (sha256 ``e112fbc8…a2f4``) ``projectIdeaPrompt``, ``storyBiblePrompt``,
  ``styleBiblePrompt``, ``chapterOutlinePrompt`` and ``sceneBeatsPrompt``, with field sets from ``schemas.ts``
  (``4881e7bc…e792``): seed fields, bible fields, 3–5 scenes per chapter with location, POV, characters,
  emotional turn and plot function, the causal order goal → conflict → turn → hook, no summarizing across
  days, no knowledge a character does not have, no early resolution of the climax.
- S03 Shenbi ``skills/shenbi-chapter-planning/SKILL.md`` (``565f1743…ef23``) memo sections: current task,
  what the reader is waiting for, cards to keep hidden, changes that must happen by chapter end, do-not list.

Recorded deviations: Vietnamese, short-story scale (no volumes or five-chapter arc packs), object-rooted
grammar-constrained schemas, and identifiers derived from names in code rather than written by the model.
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Iterable, Sequence

from server.story_authoring.prompts.schemas import ChapterPlan, ShortOutline, StoryBibleOut, StorySeed

PLANNING_SYSTEM = (
    "Bạn là mô-đun lập kế hoạch cho một truyện ngắn tiếng Việt gồm đúng ba chương. "
    "Chỉ trả về JSON đúng schema, viết toàn bộ nội dung bằng tiếng Việt tự nhiên; "
    "tên người và địa danh là tên Việt, xưng hô theo quan hệ gia đình Việt."
)


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def seed_prompt(*, idea: str, genre: str) -> str:
    return f"""Hãy dựng phần ý tưởng gốc (seed) cho một truyện ngắn ba chương từ ý tưởng của tác giả.

Yêu cầu:
- working_title: tên tạm, ngắn, dễ nhớ.
- premise: 1–2 câu tóm lược truyện.
- tone: giọng điệu chủ đạo; pov: ngôi kể (ví dụ "ngôi thứ ba, bám theo nhân vật chính").
- central_conflict: xung đột trung tâm cụ thể; ending_direction: hướng kết thúc rõ ràng, khép lại xung đột.
- characters: 2–5 nhân vật; mỗi người có name (tên Việt), role, relation_to_protagonist (cách gọi trong gia đình
  hoặc quan hệ, ghi "chính là nhân vật chính" cho nhân vật chính), description, goal.
- locations: 1–4 địa điểm có name và description.
- Bám sát ý tưởng của tác giả: giữ nguyên tên, tuổi, mốc thời gian và chi tiết họ đã nêu.

Thể loại: {genre}

Ý tưởng của tác giả:
{idea}"""


def story_bible_prompt(seed: StorySeed) -> str:
    return f"""Dựa trên seed dưới đây, viết Story Bible cho truyện ngắn.

Trả về: logline (một câu), core_promise (điều truyện hứa với người đọc), world_rules (các quy tắc của thế giới
truyện, kể cả hoàn cảnh xã hội và gia đình), major_conflicts, forbidden_contradictions (những điều tuyệt đối
không được mâu thuẫn trong suốt truyện: tuổi, quan hệ, mốc thời gian, sự thật đã xảy ra).

Seed:
{_json(seed.model_dump())}"""


def style_bible_prompt(seed: StorySeed, bible: StoryBibleOut) -> str:
    return f"""Dựa trên seed và Story Bible, viết Style Bible cho truyện.

Trả về: narration_style, sentence_rhythm, emotional_texture, dialogue_style, forbidden_style (lối viết phải tránh),
style_rules: 3–8 quy tắc viết ngắn, mỗi quy tắc là một câu mệnh lệnh có thể kiểm tra được.

Seed:
{_json(seed.model_dump())}

Story Bible:
{_json(bible.model_dump())}"""


def chapter_plan_prompt(
    *,
    chapter_number: int,
    outline: ShortOutline,
    bible: StoryBibleOut,
    character_names: Sequence[str],
    location_names: Sequence[str],
    previous_plans: Sequence[ChapterPlan],
) -> str:
    chapter = outline.chapters[chapter_number - 1]
    is_final = chapter_number == len(outline.chapters)
    previous = (
        _json(
            [
                {"chapter_goal": p.chapter_goal, "required_changes_by_end": p.required_changes_by_end}
                for p in previous_plans
            ]
        )
        if previous_plans
        else "(chưa có)"
    )
    ending = (
        f"\n- Đây là chương cuối: các cảnh phải dẫn tới và trình bày trọn kết thúc: {outline.ending} "
        f"Hình ảnh khép truyện: {outline.final_image}"
        if is_final
        else "\n- Không giải quyết xung đột trung tâm trước chương cuối."
    )
    return f"""Lập kế hoạch cho chương {chapter_number} và chia thành 3–5 cảnh có thể viết được.

Phần ghi chú chương:
- chapter_goal: việc cụ thể nhân vật chính phải làm trong chương này.
- reader_expectation: người đọc đang chờ đợi điều gì; chương này tạo, trì hoãn hay đáp ứng kỳ vọng nào.
- withheld_cards: những bí mật phải giữ kín, chưa được hé lộ trong chương này (có thể để trống).
- required_changes_by_end: 1–3 thay đổi cụ thể (thông tin, quan hệ, vật chất, quyền lực) bắt buộc xảy ra trước khi
  chương kết thúc.
- do_not: những điều chương này phải tránh.

Mỗi cảnh: summary, location, pov, characters, beats (2–4 nhịp hành động/lời thoại cụ thể), emotional_turn,
plot_function, dialogue_required.

Quy tắc:
- Thứ tự cảnh có nhân quả rõ: mục tiêu → xung đột → bước ngoặt → móc nối sang cảnh sau.
- Không tóm tắt lướt qua nhiều ngày hay nhiều sự kiện lớn; tách thành hành động, lời thoại, hiểu lầm, phản ứng.
- Nhân vật không được biết điều họ chưa thể biết.
- location chỉ được chọn trong: {", ".join(location_names)}.
- pov và characters chỉ được chọn trong: {", ".join(character_names)}.{ending}

Nhiệm vụ của chương {chapter_number} theo dàn ý: {chapter.core_task}
Mạch truyện được đẩy: {chapter.threads_advanced}
Bước ngoặt: {chapter.turning_point}

Dàn ý toàn truyện{"" if is_final else " (phần kết được giữ kín cho chương cuối)"}:
{_json(outline.model_dump(exclude=set() if is_final else {"ending", "final_image", "resolution"}))}

Story Bible:
{_json(bible.model_dump())}

Các chương trước:
{previous}"""


# --- names to keys ---------------------------------------------------------------------------------


def _fold(name: str) -> str:
    decomposed = unicodedata.normalize("NFD", name.replace("đ", "d").replace("Đ", "D"))
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn").lower()


def entity_key(name: str, taken: Iterable[str] = ()) -> str:
    """A stable lowercase ASCII key from a Vietnamese name, made unique against ``taken``."""
    base = re.sub(r"[^a-z0-9]+", "-", _fold(name)).strip("-")[:40].strip("-") or "entity"
    used = set(taken)
    key, n = base, 2
    while key in used:
        key = f"{base}-{n}"
        n += 1
    return key


def resolve_name(name: str, known: dict[str, str]) -> str | None:
    """The key of a known entity named ``name``: exact, then diacritic-insensitive, then a unique word match."""
    if name in known:
        return known[name]
    folded = {_fold(k): v for k, v in known.items()}
    target = _fold(name).strip()
    if target in folded:
        return folded[target]
    words = set(target.split())
    candidates = {v for k, v in folded.items() if words & set(k.split())}
    return candidates.pop() if len(candidates) == 1 else None

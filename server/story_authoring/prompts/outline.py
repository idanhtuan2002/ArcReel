"""Short-story outline: generate, review against six points, revise once.

Donor surface S01 Shenbi ``skills/shenbi-short-outline/SKILL.md`` (sha256 ``ac9fea12…973a``): three-act
compression (opening ~20 %, confrontation ~60 %, resolution ~20 %), one core task per chapter and no transition
chapters, at most a few turning points, an ending that answers the opening, and the generate → review → revise
loop. Recorded deviations: three chapters instead of up to thirty; the six-point review is deterministic where a
rule can be checked in code (chapter count, a task per chapter, a non-empty ending) and asked of the model only
for the judged points (arc clarity, turning-point spread, ending echoing the opening); one revision, not an open
loop, inside the run's call budget.
"""

from __future__ import annotations

import json

from server.story_authoring.prompts.schemas import OutlineReview, ShortOutline, StorySeed

OUTLINE_SYSTEM = (
    "Bạn là biên tập viên cấu trúc truyện ngắn tiếng Việt. Chỉ trả về JSON đúng schema, viết bằng tiếng Việt."
)


def outline_prompt(seed: StorySeed) -> str:
    return f"""Viết dàn ý nén cho một truyện ngắn đúng BA chương từ seed dưới đây.

Quy tắc cứng:
- Cấu trúc ba hồi: opening (dựng nhân vật, tình huống, câu hỏi), confrontation (đẩy xung đột lên, bước ngoặt),
  resolution (đối mặt, lắng đọng, khép lại).
- Mỗi chương có đúng một nhiệm vụ cốt lõi (core_task) và phải đẩy ít nhất một mạch truyện; không có chương chuyển tiếp.
- Chương 3 phải giải quyết xung đột trung tâm; ending mô tả kết thúc cụ thể, trả lời câu hỏi đặt ra ở mở đầu.
- final_image: hình ảnh cuối cùng khép truyện, gợi lại hình ảnh mở đầu.
- story_arc: một câu tóm cả hành trình.

Seed:
{json.dumps(seed.model_dump(), ensure_ascii=False, indent=2)}"""


def deterministic_outline_problems(outline: ShortOutline) -> list[str]:
    problems: list[str] = []
    if len(outline.chapters) != 3:
        problems.append(f"dàn ý có {len(outline.chapters)} chương, phải đúng 3 chương")
    for number, chapter in enumerate(outline.chapters, start=1):
        if not chapter.core_task.strip():
            problems.append(f"chương {number} thiếu nhiệm vụ cốt lõi")
    if not outline.ending.strip() or not outline.resolution.strip():
        problems.append("thiếu kết thúc hoặc phần khép lại")
    tasks = [c.core_task.strip().lower() for c in outline.chapters]
    if len(set(tasks)) != len(tasks):
        problems.append("hai chương có cùng nhiệm vụ cốt lõi")
    return problems


def outline_review_prompt(seed: StorySeed, outline: ShortOutline) -> str:
    return f"""Kiểm tra dàn ý truyện ngắn ba chương theo các điểm sau và trả về passed cùng danh sách problems:
1. Mạch truyện (story_arc) có rõ không.
2. Ba hồi có đủ và cân đối không.
3. Mỗi chương có nhiệm vụ riêng, không có chương chuyển tiếp không.
4. Bước ngoặt có phân bố hợp lý không.
5. Kết thúc có trả lời câu hỏi mở đầu và hô ứng với mở đầu không.
6. Dàn ý có trung thành với seed (tên, tuổi, mốc thời gian, quan hệ) không.
Mỗi problem phải nêu cụ thể chỗ sai. Nếu không có vấn đề, passed = true và problems rỗng.

Seed:
{json.dumps(seed.model_dump(), ensure_ascii=False, indent=2)}

Dàn ý:
{json.dumps(outline.model_dump(), ensure_ascii=False, indent=2)}"""


def outline_revision_prompt(seed: StorySeed, outline: ShortOutline, problems: list[str]) -> str:
    listed = "\n".join(f"- {p}" for p in problems)
    return f"""Sửa dàn ý dưới đây để khắc phục toàn bộ các vấn đề, giữ nguyên những phần không bị nêu.

Vấn đề:
{listed}

{outline_prompt(seed)}

Dàn ý hiện tại:
{json.dumps(outline.model_dump(), ensure_ascii=False, indent=2)}"""


def review_passes(review: OutlineReview) -> bool:
    return review.passed and not review.problems

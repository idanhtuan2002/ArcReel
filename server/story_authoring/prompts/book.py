"""Prompts of a book (ADR-0116): the skeleton, each volume's chapter rows, the volume review, a chapter's digest
and a part's summary. Donor surfaces: huohuo ``novel_outline`` (phased outline, chapter role, chapter-end hooks)
and its memory update after each chapter; shenbi ``volume-outlining`` (objective, key results, turning point),
``foreshadowing-lifecycle`` and ``memory-distill``."""

from __future__ import annotations

import json
from collections.abc import Sequence

from server.story_authoring.book import BookOutline, BookRow, Hook, PlannedRow
from server.story_authoring.prompts.schemas import StoryBibleOut, StorySeed

BOOK_SYSTEM = (
    "Bạn là biên tập viên cấu trúc tiểu thuyết tiếng Việt chất lượng xuất bản. Chỉ trả về JSON đúng schema, viết "
    "bằng tiếng Việt."
)
MEMORY_SYSTEM = (
    "Bạn ghi chép bộ nhớ cho một tiểu thuyết tiếng Việt. Chỉ ghi điều chương văn viết ra, không đoán, không thêm. "
    "Chỉ trả về JSON đúng schema; giữ nguyên tên người và địa danh như văn bản."
)

ROLE_GUIDE = (
    "setup (dựng tình thế, cài đặt), advance (đẩy mạch truyện lên), turn (bước ngoặt, đảo chiều), payoff (trả "
    "phục bút, thu hoạch), climax (cao trào), breath (lắng lại, chiều sâu cảm xúc)"
)


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=1)


def book_outline_prompt(
    seed: StorySeed, bible: StoryBibleOut, *, chapters: int, volumes: Sequence[tuple[int, int]]
) -> str:
    ranges = "; ".join(f"quyển {i} gồm chương {a}–{b}" for i, (a, b) in enumerate(volumes, start=1))
    return f"""Lập khung cho một tiểu thuyết {chapters} chương, chia {len(volumes)} quyển: {ranges}.

Trả về:
- logline, story_arc (cả hành trình trong một đoạn), central_question (câu hỏi lớn người đọc theo đến cuối).
- ending: kết thúc cụ thể trả lời câu hỏi lớn; final_image: hình ảnh khép truyện, hô ứng mở đầu.
- volumes: đúng {len(volumes)} quyển theo thứ tự; mỗi quyển có title, objective (mục tiêu của quyển), 3–5 key_results
  (kết quả cụ thể phải đạt trong quyển), turning_point (bước ngoặt cuối quyển, đẩy sang quyển sau), new_characters
  và new_locations (tối đa 3 mỗi loại, chỉ khi quyển cần người hay nơi mới; không lặp tên đã có; nhân vật mới có
  gender, address, voice và flaw như trong seed).
Quy tắc: mỗi quyển leo thang so với quyển trước; xung đột trung tâm chỉ được giải ở quyển cuối; không có quyển
chuyển tiếp; giữ đúng tên, tuổi, giới tính, cách gọi và quan hệ của seed.

Seed:
{_json(seed.model_dump())}

Story Bible:
{_json(bible.model_dump())}"""


def book_rows_prompt(
    outline: BookOutline,
    *,
    volume: int,
    first: int,
    count: int,
    total: int,
    earlier: Sequence[PlannedRow],
    open_hooks: Sequence[Hook],
    next_id: int = 1,
) -> str:
    entry = outline.volumes[volume]
    recent = [
        {"chương": r.chapter, "nhiệm vụ": r.core_task, "vai trò": r.role.value, "bước ngoặt": r.turning_point}
        for r in earlier[-6:]
    ]
    hooks = [
        {"id": h.hook_id, "nội dung": h.text, "cài ở chương": h.planted, "giải muộn nhất ở chương": h.due}
        for h in open_hooks
    ]
    final = (
        f"\n- Chương {total} là chương cuối của tiểu thuyết: vai trò climax hoặc payoff, giải xung đột trung tâm và "
        "mọi phục bút còn mở."
        if first + count - 1 == total
        else "\n- Không giải xung đột trung tâm trong các chương này."
    )
    return f"""Viết dàn ý từng chương cho chương {first}–{first + count - 1} (đúng {count} mục, theo thứ tự) thuộc quyển
{volume + 1} «{entry.title}».

Mỗi mục: core_task (việc cụ thể nhân vật chính làm trong chương), threads_advanced (mạch truyện được đẩy),
turning_point (bước ngoặt / móc cuối chương khiến người đọc muốn đọc tiếp), role (một trong: {ROLE_GUIDE}),
plants (0–1 phục bút mới cài trong chương, một câu cụ thể; chỉ cài khi truyện cần, đừng cài tràn lan), payoffs (id các phục bút được giải trong
chương). Phục bút mới được đánh số theo thứ tự xuất hiện, bắt đầu từ h{next_id}; một chương sau có thể giải phục bút
cài ở chương trước bằng id đó, không bao giờ giải ngay trong chương cài.
Quy tắc:
- Không để ba chương liền nhau cùng role; nhịp phải lên xuống.
- Mỗi chương có nhiệm vụ riêng, không có chương chuyển tiếp rỗng.
- Phục bút còn mở phải được giải muộn nhất ở chương ghi bên cạnh; phục bút mới phải có thể giải trong 12 chương.
- Các chương của quyển phải đạt đủ key_results và kết ở turning_point của quyển.{final}

Khung tiểu thuyết:
{_json(outline.model_dump(exclude={"volumes"}))}

Quyển {volume + 1}:
{_json(entry.model_dump())}

Các chương ngay trước:
{_json(recent) if recent else "(chưa có)"}

Phục bút đang mở:
{_json(hooks) if hooks else "(không có)"}"""


def book_rows_revision_prompt(base: str, rows: Sequence[BookRow], problems: Sequence[str]) -> str:
    listed = "\n".join(f"- {p}" for p in problems)
    return f"""Sửa dàn ý chương dưới đây để khắc phục mọi vấn đề, giữ nguyên phần không bị nêu.

Vấn đề:
{listed}

{base}

Dàn ý hiện tại:
{_json([r.model_dump(mode="json") for r in rows])}"""


def book_rows_review_prompt(outline: BookOutline, volume: int, rows: Sequence[PlannedRow]) -> str:
    entry = outline.volumes[volume]
    return f"""Kiểm tra dàn ý chương của quyển {volume + 1} và trả về passed cùng danh sách problems:
1. Các chương có đạt đủ key_results của quyển và kết ở turning_point của quyển không.
2. Mỗi chương có nhiệm vụ riêng, có nhân quả với chương trước không.
3. Nhịp có lên xuống, có cao trào đúng chỗ không.
4. Có mâu thuẫn với khung tiểu thuyết (tên, quan hệ, quy tắc) không.
Mỗi problem nêu cụ thể chương và chỗ sai. Không có vấn đề thì passed = true, problems rỗng.

Khung tiểu thuyết:
{_json(outline.model_dump(exclude={"volumes"}))}

Quyển {volume + 1}:
{_json(entry.model_dump())}

Dàn ý chương:
{_json([r.model_dump(mode="json") for r in rows])}"""


def chapter_digest_prompt(chapter: int, text: str, hooks: Sequence[tuple[str, str]]) -> str:
    listed = "\n".join(f"- {hook_id}: {content}" for hook_id, content in hooks) or "(không có)"
    return f"""Ghi bộ nhớ cho chương {chapter} vừa được duyệt:
- summary: tóm tắt chương (tối đa 600 ký tự): ai làm gì, hậu quả, chương kết ở đâu.
- events: 1–6 sự kiện chính theo thứ tự.
- characters: mỗi nhân vật xuất hiện, tên đúng như văn bản, và trạng thái ở cuối chương (ở đâu, muốn gì, biết gì,
  bị thương hay mất gì, quan hệ đổi ra sao).
- hooks: phục bút trong danh sách dưới đây mà chương chạm tới (touched) hoặc giải xong (resolved).
- new_threads: 0–3 câu hỏi, lời hứa, bí mật hay mối đe dọa MỚI mở ra trong chương mà chưa có trong danh sách.
- time_place: thời điểm và nơi chốn ở cuối chương.

Phục bút đang mở:
{listed}

CHƯƠNG {chapter}:
<<<
{text}
>>>"""


def part_summary_prompt(part: int, summaries: Sequence[tuple[int, str]]) -> str:
    listed = "\n".join(f"- Chương {c}: {s}" for c, s in summaries)
    return f"""Tóm tắt phần {part} của tiểu thuyết trong một đoạn (tối đa 1200 ký tự) từ tóm tắt các chương dưới đây:
diễn biến chính theo thứ tự, thay đổi lớn của nhân vật, tình thế cuối phần. Chỉ dùng điều đã ghi.

{listed}"""


__all__ = [
    "BOOK_SYSTEM",
    "MEMORY_SYSTEM",
    "book_outline_prompt",
    "book_rows_prompt",
    "book_rows_review_prompt",
    "book_rows_revision_prompt",
    "chapter_digest_prompt",
    "part_summary_prompt",
]

"""Scene drafting prompt: write one scene from its compiled context pack only.

Donor surfaces (``R2_STORY_DONOR_BASELINE.json`` S04):

- Novel Studio ``src/lib/ai/prompts.ts`` (sha256 ``e112fbc8…a2f4``) ``draftSystemPrompt`` and
  ``chapterDraftPrompt``: write only from the context pack; do not change deaths, allegiances, places, item
  ownership or world rules; do not resolve later climaxes early; no knowledge a character should not have;
  keep the style bible; end on a concrete hook; prose only; do not skip process by summary.
- Shenbi ``skills/shenbi-chapter-drafting/SKILL.md`` (``27e978b3…32c7``) craft rules and
  ``anti-ai-reference.md`` (``264dd9c9…6519``): the narrator draws no conclusions for the reader, no
  report-like or meta language, scene-driven rather than narrated, show emotion through action, varied
  paragraph lengths, dialogue fitted to each character, and a short budget of stock phrases.

Recorded deviations: Vietnamese; scene-sized instead of chapter-sized; the context pack is rendered as labelled
plain text instead of raw JSON; Shenbi's PRE_WRITE_CHECK and metadata blocks are dropped because the output
schema carries prose only; the stock-phrase list is the Vietnamese equivalent of the donor's Chinese list.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence

from r2.contracts import NarrativeContextPack
from r2.contracts.narrative_context import ContextChannel, NarrativeContextSegment
from server.story_authoring.prompts.schemas import ChapterPlan, PlannedScene

DRAFT_SYSTEM = (
    "Bạn là người viết văn xuôi tiếng Việt cho một truyện ngắn. Bạn chỉ được dựa vào phần Bối cảnh được cung cấp, "
    "không dựa vào trí nhớ hội thoại, và không giải thích gì ngoài văn bản truyện."
)

CRAFT_RULES = (
    "Viết bằng cảnh, hành động và lời thoại; không kể tóm tắt lướt qua.",
    "Thể hiện cảm xúc qua hành động và phản ứng cơ thể, không viết kiểu 'anh cảm thấy buồn'.",
    "Người kể không kết luận thay người đọc; không có câu kiểu 'khiến người ta phải suy ngẫm'.",
    "Không có ngôn ngữ báo cáo, tiêu đề, ghi chú, số thứ tự cảnh hay lời bình về chính câu chuyện.",
    "Đoạn văn dài ngắn xen kẽ; lời thoại đúng giọng, đúng cách xưng hô của từng nhân vật.",
    "Mỗi cụm sau chỉ dùng tối đa một lần: 'dường như', 'như thể', 'bất giác', 'khẽ mỉm cười', 'ánh mắt thoáng'.",
)

HARD_RULES = (
    "Không thay đổi sự thật đã khóa: người đã mất, quan hệ, địa điểm, vật thuộc về ai, mốc thời gian.",
    "Không giải quyết trước cao trào của các cảnh sau.",
    "Nhân vật không được biết điều họ chưa thể biết.",
    "Không thêm nhân vật có tên hay địa danh mới ngoài những tên đã có trong bối cảnh.",
    "Không chép lại câu nào của các cảnh trước; chỉ viết tiếp mạch truyện bằng câu chữ mới.",
    "Không dùng ký hiệu định dạng như dấu sao; lời trích hay chữ viết trong thư, sổ đặt trong ngoặc kép.",
)


def _fact_lines(segment: NarrativeContextSegment, names: Mapping[str, str]) -> list[str]:
    try:
        facts = [json.loads(item) for item in json.loads(segment.content)]
    except (ValueError, TypeError):
        return [segment.content]
    lines = []
    for fact in facts:
        if isinstance(fact, dict):
            subject = names.get(str(fact.get("subject_ref")), str(fact.get("subject_ref")))
            lines.append(f"- {subject}: {fact.get('value')}")
    return lines


def _constraint_lines(segment: NarrativeContextSegment) -> list[str]:
    try:
        constraints = json.loads(segment.content)
    except ValueError:
        return [segment.content]
    beats = constraints.get("creative_constraints") or []
    return [f"- {beat}" for beat in beats]


def render_context(pack: NarrativeContextPack, names: Mapping[str, str]) -> str:
    """The pack as labelled Vietnamese text: locked facts, scene intent, style rules, then the last paragraphs of
    the scene just before and the openings of older ones (the full earlier text invites copying)."""
    facts: list[str] = []
    intent: list[str] = []
    beats: list[str] = []
    style: list[str] = []
    earlier: list[str] = []
    for segment in (*pack.segments, *pack.recent_accepted_context, *pack.retrieved_context):
        if segment.channel in (ContextChannel.AUTHOR_TRUTH, ContextChannel.POV_KNOWN):
            facts.extend(_fact_lines(segment, names))
        elif segment.channel is ContextChannel.AUTHORIAL_INTENT:
            if segment.source_ref.endswith("#forbidden"):
                beats.extend(_constraint_lines(segment))
            else:
                intent.append(segment.content)
        elif segment.channel is ContextChannel.CREATIVE_POLICY:
            style.append(f"- {segment.content}")
        elif segment.channel is ContextChannel.RECENT_ACCEPTED:
            earlier.append(segment.content)
    parts = [
        "[Sự thật đã khóa]\n" + ("\n".join(facts) or "(không có)"),
        "[Mục đích cảnh]\n" + ("\n".join(intent) or "(không có)"),
        "[Nhịp bắt buộc]\n" + ("\n".join(beats) or "(không có)"),
        "[Quy tắc văn phong]\n" + ("\n".join(style) or "(không có)"),
    ]
    if earlier:
        latest = [p for p in earlier[0].split("\n\n") if p.strip()]
        parts.append("[Đoạn cuối cảnh liền trước — để nối mạch, không chép lại]\n" + "\n\n".join(latest[-2:]))
    if len(earlier) > 1:
        openings = [_opening(text) for text in earlier[1:]]
        parts.append("[Mở đầu các cảnh trước đó, mới nhất trước]\n" + "\n".join(f"- {o}" for o in openings))
    return "\n\n".join(parts)


def _opening(text: str, limit: int = 200) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[:limit].rsplit(" ", 1)[0] + "…"


def paragraph_bounds(target_syllables: int) -> tuple[int, int]:
    minimum = max(4, target_syllables // 120)
    return minimum, max(minimum + 2, target_syllables // 60)


def scene_draft_prompt(
    *,
    context: str,
    scene: PlannedScene,
    plan: ChapterPlan,
    chapter_number: int,
    scene_number: int,
    is_last_scene_of_chapter: bool,
    is_final_scene: bool,
    target_syllables: int,
    revision_note: str | None = None,
) -> str:
    duties: list[str] = []
    if is_last_scene_of_chapter:
        changes = "; ".join(plan.required_changes_by_end)
        duties.append(f"Cảnh này kết thúc chương {chapter_number}: trước khi hết cảnh phải xảy ra: {changes}.")
        if not is_final_scene:
            duties.append("Kết cảnh bằng một móc nối cụ thể khiến người đọc muốn đọc chương sau.")
    if is_final_scene:
        duties.append("Đây là cảnh cuối của truyện: khép lại xung đột trung tâm một cách trọn vẹn, không bỏ lửng.")
    if plan.withheld_cards:
        duties.append("Giữ kín, chưa hé lộ: " + "; ".join(plan.withheld_cards) + ".")
    if plan.do_not:
        duties.append("Tránh: " + "; ".join(plan.do_not) + ".")
    if scene.dialogue_required:
        duties.append("Cảnh phải có lời thoại trực tiếp giữa các nhân vật.")
    note = f"\n[Yêu cầu sửa của tác giả]\n{revision_note}\n" if revision_note else ""
    return f"""Viết cảnh {scene_number} của chương {chapter_number}. Mỗi phần tử của mảng là một đoạn văn.

[Cảnh này]
- Diễn biến: {scene.summary}
- Nhịp: {"; ".join(scene.beats)}
- Điểm nhìn: {scene.pov}; nhân vật: {", ".join(scene.characters)}; nơi chốn: {scene.location}
- Chuyển biến cảm xúc: {scene.emotional_turn}
- Chức năng trong truyện: {scene.plot_function}
- Độ dài: khoảng {target_syllables} chữ.
{chr(10).join("- " + duty for duty in duties)}
{note}
[Quy tắc cứng]
{chr(10).join("- " + rule for rule in HARD_RULES)}

[Kỹ thuật viết]
{chr(10).join("- " + rule for rule in CRAFT_RULES)}

[Bối cảnh]
{context}"""


def target_syllables_for(scenes: Sequence[PlannedScene], *, story_target: int = 9000, chapters: int = 3) -> int:
    """Even split of the story target across the chapter's scenes, clamped to the scene window."""
    per_chapter = story_target // chapters
    return max(600, min(1000, per_chapter // max(1, len(scenes))))

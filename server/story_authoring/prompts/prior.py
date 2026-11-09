"""Reading a story that already exists, before continuing it or writing a variant of it (ADR-0115).

The prior text is read in chunks (each summarized on its own: events, character states, open threads, places) and
then condensed into one canon lock: who the characters are and where they stand, the places, the threads still
open, how the text ends, and its voice. Every name in the lock must be written in the prior text (DramaClaw's name
attestation); the lock never invents. Donor surfaces: huohuo ``rebuildNovelContinuityFromChapters`` (per-chapter
state rebuild, ``novel-continuity.ts:621``) and the canon-lock prefix (``NC:141``); shenbi ``import-analysis``
(passes, nothing guessed) and ``sequel-writing`` (context rebuilt from the text, committed text never edited).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from lib.text_attestation import named_in

PRIOR_CHUNK_CHARS = 8000
#: A continuation reads at most the last chunks; a variant must read all of a story within this bound.
MAX_PRIOR_CHUNKS = 12
PRIOR_TAIL_CHARS = 1500

PRIOR_SYSTEM = (
    "Bạn là mô-đun đọc hiểu cho một truyện tiếng Việt đã viết sẵn. Chỉ ghi lại điều văn bản viết ra, không đoán, "
    "không thêm. Chỉ trả về JSON đúng schema; viết bằng tiếng Việt; giữ nguyên tên người và địa danh như văn bản."
)


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CharacterState(_Model):
    name: str = Field(min_length=1, max_length=60)
    state: str = Field(min_length=1, max_length=400)


class PriorSummary(_Model):
    events: list[str] = Field(min_length=1, max_length=14)
    characters: list[CharacterState] = Field(max_length=12)
    open_threads: list[str] = Field(max_length=10)
    places: list[str] = Field(max_length=8)


class LockedCharacter(_Model):
    name: str = Field(min_length=1, max_length=60)
    role: str = Field(min_length=1, max_length=200)
    relation_to_protagonist: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=500)
    current_state: str = Field(min_length=1, max_length=500)


class LockedPlace(_Model):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(min_length=1, max_length=400)


class CanonLock(_Model):
    title_hint: str = Field(min_length=1, max_length=120)
    genre: str = Field(min_length=1, max_length=120)
    tone: str = Field(min_length=1, max_length=200)
    pov: str = Field(min_length=1, max_length=200)
    characters: list[LockedCharacter] = Field(min_length=1, max_length=12)
    places: list[LockedPlace] = Field(max_length=10)
    chapter_events: list[str] = Field(min_length=1, max_length=40)
    open_threads: list[str] = Field(max_length=12)
    ending_state: str = Field(min_length=1, max_length=800)
    style_notes: str = Field(min_length=1, max_length=600)


def split_prior(text: str, *, size: int = PRIOR_CHUNK_CHARS) -> list[str]:
    """The text in chunks of about ``size`` characters, cut at paragraph breaks (or sentence ends) when possible."""
    text = text.strip()
    chunks: list[str] = []
    while len(text) > size:
        cut = text.rfind("\n\n", size // 2, size)
        if cut < 0:
            cut = max(text.rfind(". ", size // 2, size), text.rfind(".\n", size // 2, size))
            cut = cut + 1 if cut >= 0 else size
        chunks.append(text[:cut].strip())
        text = text[cut:].strip()
    if text:
        chunks.append(text)
    return chunks


def prior_summary_prompt(chunk: str, index: int, total: int) -> str:
    return f"""Đây là đoạn {index}/{total} của một truyện đã viết sẵn. Ghi lại, theo đúng thứ tự trong đoạn:
- events: các sự kiện chính (mỗi mục một câu, ai làm gì, hậu quả).
- characters: mỗi nhân vật xuất hiện, tên đúng như văn bản, và trạng thái của họ ở cuối đoạn.
- open_threads: những câu hỏi, lời hứa, bí mật hay mối đe dọa còn bỏ ngỏ ở cuối đoạn.
- places: tên các địa điểm xuất hiện.
Không suy đoán điều văn bản không viết.

ĐOẠN {index}:
<<<
{chunk}
>>>"""


def canon_lock_prompt(
    summaries: list[PriorSummary], tail: str, *, mode: Literal["continuation", "variant"], omitted: bool
) -> str:
    purpose = (
        "để viết TIẾP phần sau của truyện: trạng thái ở cuối văn bản là điểm xuất phát"
        if mode == "continuation"
        else "để viết một PHIÊN BẢN KHÁC của chính truyện này: cần đủ diễn biến từ đầu đến cuối"
    )
    note = "\n(Phần đầu của truyện quá dài nên chỉ có các đoạn gần cuối.)" if omitted else ""
    return f"""Từ các bản tóm tắt theo đoạn và đoạn kết nguyên văn dưới đây, lập bản khóa canon của truyện {purpose}.
Trả về:
- title_hint, genre, tone, pov: tên truyện (hoặc tên gợi ý), thể loại, giọng điệu, ngôi kể như văn bản.
- characters: các nhân vật quan trọng, tên đúng như văn bản; role, relation_to_protagonist, description (ngoại hình,
  tính cách), current_state (họ ở đâu, muốn gì, biết gì, quan hệ ra sao ở cuối truyện).
- places: các địa điểm quan trọng.
- chapter_events: diễn biến chính theo thứ tự thời gian, mỗi mục một câu.
- open_threads: các mạch còn bỏ ngỏ ở cuối truyện.
- ending_state: tình thế ở câu cuối cùng của văn bản.
- style_notes: giọng văn, nhịp câu, cách xưng hô cần giữ.
Chỉ dùng điều văn bản viết ra.{note}

TÓM TẮT THEO ĐOẠN:
{json.dumps([s.model_dump() for s in summaries], ensure_ascii=False, indent=1)}

ĐOẠN KẾT NGUYÊN VĂN:
<<<
{tail}
>>>"""


def attest(lock: CanonLock, text: str) -> CanonLock:
    """The lock without characters or places the prior text never names; raises when no character is left."""
    characters = [c for c in lock.characters if named_in(c.name, text)]
    if not characters:
        raise ValueError("the canon lock names no character of the text")
    places = [p for p in lock.places if named_in(p.name, text)]
    return lock.model_copy(update={"characters": characters, "places": places})


def prior_context(lock: CanonLock, *, mode: Literal["continuation", "variant"], direction: str, part: int) -> str:
    """The block the planning prompts receive: the canon lock and what the author asks of this part."""
    if mode == "continuation":
        task = (
            f"Đây là PHẦN {part} — phần viết tiếp của truyện đã có. Giữ nguyên mọi nhân vật, tên, quan hệ, quy tắc thế "
            "giới và giọng văn; bắt đầu từ tình thế cuối cùng (ending_state), không kể lại phần trước, không thay đổi điều "
            "đã xảy ra; phát triển hoặc khép lại các mạch còn mở; có thể thêm nhân vật mới khi cần."
        )
        ask = "HƯỚNG ĐI TÁC GIẢ MUỐN CHO PHẦN NÀY"
    else:
        task = (
            "Đây là một PHIÊN BẢN KHÁC của chính truyện đã có. Giữ những gì yêu cầu không đổi (mặc định: xương sống cốt "
            "truyện theo đúng thứ tự diễn biến, các nhân vật chính và kết cục); chỉ thay đổi đúng những gì yêu cầu nêu, "
            "một cách nhất quán từ đầu đến cuối; không thêm hay bớt sự kiện ngoài yêu cầu."
        )
        ask = "YÊU CẦU BIẾN THỂ"
    return f"""TRUYỆN ĐÃ CÓ — {task}
BẢN KHÓA CANON:
{json.dumps(lock.model_dump(), ensure_ascii=False, indent=1)}

{ask}:
{direction}"""


class VariantReview(_Model):
    missing: list[int] = Field(max_length=40)
    contradicted: list[int] = Field(max_length=40)
    notes: list[str] = Field(max_length=6)


def variant_review_prompt(events: list[str], outline: object, plans: Sequence[object], instruction: str) -> str:
    """The variant's outline and chapter plans against the source's events in order (ADR-0117)."""
    listed = "\n".join(f"{i}. {e}" for i, e in enumerate(events, start=1))
    planned = [
        {"chapter_goal": getattr(p, "chapter_goal", ""), "scenes": [s.summary for s in getattr(p, "scenes", [])]}
        for p in plans
    ]
    return f"""So sánh dàn ý một PHIÊN BẢN KHÁC với các diễn biến của truyện gốc.
Yêu cầu biến thể (chỉ được thay đổi những gì yêu cầu này nêu):
{instruction}

Trả về:
- missing: số thứ tự các diễn biến gốc mà dàn ý mới bỏ mất (không có tương đương nào).
- contradicted: số thứ tự các diễn biến gốc mà dàn ý mới làm trái (kết quả khác) khi yêu cầu không cho đổi.
- notes: tối đa 6 ghi chú ngắn.
Đổi giọng, ngôi kể, bối cảnh hay tên theo đúng yêu cầu không phải lỗi. Không có lỗi thì trả danh sách rỗng.

DIỄN BIẾN TRUYỆN GỐC:
{listed}

DÀN Ý MỚI:
{json.dumps(getattr(outline, "model_dump", dict)(), ensure_ascii=False, indent=1)}

KẾ HOẠCH CÁC CHƯƠNG MỚI:
{json.dumps(planned, ensure_ascii=False, indent=1)}"""


__all__ = [
    "MAX_PRIOR_CHUNKS",
    "PRIOR_SYSTEM",
    "PRIOR_TAIL_CHARS",
    "CanonLock",
    "PriorSummary",
    "VariantReview",
    "attest",
    "canon_lock_prompt",
    "prior_context",
    "prior_summary_prompt",
    "split_prior",
    "variant_review_prompt",
]

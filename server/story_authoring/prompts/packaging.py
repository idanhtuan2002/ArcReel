"""Packaging: title candidates, blurbs, selling points with evidence, tags.

Donor surface S11 Shenbi ``skills/shenbi-short-packaging/SKILL.md`` (sha256 ``f4cb77e0…2efb``): several versions
for the Human to choose from, a blurb that hooks without spoiling the core reversal, every selling point backed
by evidence found in the text. Recorded deviations: Vietnamese; the cover prompt and platform-specific tag
systems are not taken (the video flow designs its own visuals); evidence is a verbatim quote that
:func:`unverified_selling_points` checks against the manuscript, so an invented quote is dropped; blurbs are
checked by the judge route (``audits.unfaithful_blurbs``), and a claim the manuscript lacks reaches the Human as a
finding while the export leads with an unflagged blurb.
"""

from __future__ import annotations

from collections.abc import Sequence

from server.story_authoring.prompts.schemas import Packaging

PACKAGING_SYSTEM = (
    "Bạn là biên tập viên xuất bản truyện ngắn tiếng Việt. Chỉ trả về JSON đúng schema, viết bằng tiếng Việt."
)


def packaging_prompt(*, manuscript: str, working_title: str, premise: str) -> str:
    return f"""Làm phần đóng gói xuất bản cho truyện ngắn dưới đây.

- titles: 3–5 tên truyện, mỗi tên một kiểu khác nhau, ghi trong kind (thẳng thắn, ẩn dụ, gây tò mò, cảm xúc); tên
  dài 2–6 chữ, là tiếng Việt tự nhiên, đọc lên trôi chảy, không lặp chữ, không ghép từ vô nghĩa.
- blurbs: 2–3 bản giới thiệu, mỗi bản một giọng (thẳng thắn, gây tò mò, cảm xúc), 60–150 chữ: câu mở móc người
  đọc, nhân vật chính, xung đột trung tâm, gợi ý bước ngoặt mà KHÔNG tiết lộ kết thúc. Chỉ nêu điều truyện thật sự kể.
- selling_points: 3–5 điểm hấp dẫn, mỗi điểm một khía cạnh khác nhau (thể loại, nhân vật chính, xung đột, bối cảnh,
  cảm xúc, điểm mới), viết như một câu chào mời người đọc, tối đa 15 chữ, không tóm tắt cốt truyện; mỗi điểm kèm
  evidence_quote chép NGUYÊN VĂN một câu trong truyện chứng minh điểm đó.
- tags: 5–10 thẻ (thể loại, kiểu nhân vật, cảm xúc, yếu tố truyện, điểm hấp dẫn).

Tên tạm: {working_title}
Tóm lược: {premise}

Truyện:
{manuscript}"""


def unverified_selling_points(packaging: Packaging, manuscript: str) -> list[str]:
    """Selling points whose evidence quote does not occur verbatim in the manuscript."""
    normalized = " ".join(manuscript.split())
    return [p.point for p in packaging.selling_points if " ".join(p.evidence_quote.split()) not in normalized]


#: Words that make a hollow title when a title holds nothing else (donor huohuo bans abstract, selling-point-free
#: titles).
HOLLOW_TITLE_WORDS = frozenset(
    {"thời gian", "năm tháng", "kỷ niệm", "giấc mơ", "bến bờ", "vô đề", "tâm tư", "ký ức", "cuộc đời", "định mệnh"}
)


def title_problems(title: str, cast_names: Sequence[str]) -> list[str]:
    """Why a title breaks the packaging prompt's own rules: 2–8 Vietnamese syllables, no repeated syllable, not only a
    character's name, not only hollow words."""
    from server.story_authoring.checks import count_syllables, is_vietnamese_syllable

    problems: list[str] = []
    words = title.split()
    names = {w.casefold() for name in cast_names for w in name.split()}
    if not 2 <= count_syllables(title) <= 8:
        problems.append("tên phải dài 2–8 tiếng")
    tokens = [w.strip(".,:;!?—–-“”\"'()").casefold() for w in words]
    tokens = [t for t in tokens if t]
    if any(not is_vietnamese_syllable(t) and t not in names for t in tokens):
        problems.append("tên chỉ dùng chữ tiếng Việt")
    if len(set(tokens)) != len(tokens):
        problems.append("tên không lặp chữ")
    if tokens and all(t in names for t in tokens):
        problems.append("tên không chỉ là tên nhân vật")
    rest = " ".join(t for t in tokens if t not in names)
    if rest and all(phrase in HOLLOW_TITLE_WORDS for phrase in _phrases(rest)):
        problems.append("tên phải gợi ra câu chuyện, không chỉ là từ trừu tượng")
    return problems


def _phrases(text: str) -> list[str]:
    words = text.split()
    return [" ".join(words[i : i + 2]) for i in range(0, len(words), 2)]


def best_title(packaging: Packaging, cast_names: Sequence[str], fallback: str) -> str:
    """The first offered title that keeps the rules, else the seed's working title."""
    return next((t.title for t in packaging.titles if not title_problems(t.title, cast_names)), fallback)

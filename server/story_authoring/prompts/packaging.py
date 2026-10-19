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

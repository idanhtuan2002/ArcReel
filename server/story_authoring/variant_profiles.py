"""Named variant profiles: a variant spec an automatic run can apply without a human note (ADR-0115).

Each profile names what changes; by default the plot spine in order, the main characters and the ending stay (the
variant context says so). A human instruction is the same kind of spec written by a person. Donor surfaces: huohuo's
per-genre skill packs and its ``compliance`` (age rating) skill, shenbi ``canon-import`` keep/change lists,
novel-studio ``styleRevision``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VariantProfile:
    profile_id: str
    label: str
    instruction: str


PROFILES: dict[str, VariantProfile] = {
    profile.profile_id: profile
    for profile in (
        VariantProfile(
            "first-person",
            "Ngôi thứ nhất",
            "Kể lại toàn bộ truyện ở ngôi thứ nhất qua lời nhân vật chính: chỉ kể điều nhân vật chính thấy, nghe, "
            "biết và cảm; giữ nguyên mọi sự kiện, nhân vật, thứ tự và kết thúc.",
        ),
        VariantProfile(
            "darker-tone",
            "Giọng u tối, căng thẳng",
            "Đổi giọng điệu sang u tối, căng thẳng, nhiều hiểm họa và bí ẩn hơn (noir); câu ngắn, nhịp gấp; giữ "
            "nguyên các sự kiện, nhân vật và kết thúc.",
        ),
        VariantProfile(
            "light-comedy",
            "Giọng hài nhẹ",
            "Đổi giọng điệu sang hài nhẹ, ấm áp: tình huống dí dỏm, thoại duyên; giữ nguyên các sự kiện chính, "
            "nhân vật và kết thúc, không biến bi kịch thành trò đùa.",
        ),
        VariantProfile(
            "young-readers",
            "Cho độ tuổi 12+",
            "Viết lại cho độc giả từ 12 tuổi: bỏ bạo lực chi tiết, ngôn từ nặng và cảnh nhạy cảm, diễn đạt dễ hiểu; "
            "giữ nguyên cốt truyện, nhân vật và kết thúc.",
        ),
        VariantProfile(
            "western-market",
            "Thị trường phương Tây",
            "Chuyển bối cảnh, tên người, địa danh và phong tục sang một nước nói tiếng Anh hiện đại, đổi nhất quán "
            "từ đầu đến cuối; giữ nguyên quan hệ, động cơ, các sự kiện và kết thúc; vẫn viết bằng tiếng Việt.",
        ),
        VariantProfile(
            "romance-focus",
            "Đẩy tuyến tình cảm",
            "Đưa tuyến tình cảm lên làm trục chính: thêm chiều sâu cảm xúc và khoảnh khắc giữa các nhân vật có quan hệ; "
            "không thêm sự kiện làm đổi kết thúc.",
        ),
        VariantProfile(
            "mystery-focus",
            "Đẩy yếu tố bí ẩn",
            "Kể theo lối trinh thám: giấu thông tin lâu hơn, gài manh mối công bằng, lật mở ở cuối; giữ nguyên sự thật "
            "của truyện và kết thúc.",
        ),
    )
}


def profile_instruction(profile_id: str) -> str:
    """The instruction of a named profile; raises ``KeyError`` for an unknown one."""
    return PROFILES[profile_id].instruction


__all__ = ["PROFILES", "VariantProfile", "profile_instruction"]

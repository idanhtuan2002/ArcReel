"""旁白 script_plan 分镜对源文的近似逐字回对齐。"""

from __future__ import annotations

from server.text_generation import _realign_segments_to_source

SOURCE = "Nam nhặt chiếc chai trên bãi cát. Mẹ cậu khóc, giọng run rẩy. Biển vẫn rì rào như mọi ngày."


def _segments(*texts: str) -> list[dict]:
    return [{"segment_id": f"E1S{i:02d}", "novel_text": text} for i, text in enumerate(texts, start=1)]


def test_verbatim_segments_are_untouched():
    segments = _segments(
        "Nam nhặt chiếc chai trên bãi cát.", "Mẹ cậu khóc, giọng run rẩy.", "Biển vẫn rì rào như mọi ngày."
    )
    expected = [dict(s) for s in segments]

    _realign_segments_to_source(segments, SOURCE)

    assert segments == expected


def test_a_dropped_comma_and_an_extra_punctuation_segment_are_restored_from_the_source():
    segments = _segments(
        "Nam nhặt chiếc chai trên bãi cát.", "Mẹ cậu khóc giọng run rẩy.", "Biển vẫn rì rào như mọi ngày.", "."
    )

    _realign_segments_to_source(segments, SOURCE)

    assert [s["novel_text"] for s in segments] == [
        "Nam nhặt chiếc chai trên bãi cát.",
        "Mẹ cậu khóc, giọng run rẩy.",
        "Biển vẫn rì rào như mọi ngày.",
    ]
    assert [s["segment_id"] for s in segments] == ["E1S01", "E1S02", "E1S03"]


def test_a_paraphrase_is_left_for_the_coverage_check():
    segments = _segments("Nam tìm thấy một cái chai.", "Mẹ cậu khóc, giọng run rẩy.", "Biển vẫn rì rào như mọi ngày.")
    expected = [dict(s) for s in segments]

    _realign_segments_to_source(segments, SOURCE)

    assert segments == expected


def test_a_skipped_sentence_is_restored_into_its_segment_from_the_source():
    first = "Nam nhặt chiếc chai thủy tinh cũ trên bãi cát trắng, tay run run khi thấy tờ giấy cuộn tròn bên trong."
    second = "Mẹ cậu đứng ở bậc cửa, nước mắt lăn dài trên đôi má gầy, giọng run rẩy gọi tên người chồng đã khuất."
    third = "Biển vẫn rì rào như mọi ngày, những con sóng nhỏ vỗ vào bờ cát dưới nắng chiều."
    skipped = "Nam im lặng."
    segments = _segments(first, second, third)

    _realign_segments_to_source(segments, f"{first} {second} {skipped} {third}")

    assert [s["novel_text"] for s in segments] == [first, f"{second} {skipped}", third]


def test_a_dropped_lead_in_of_a_short_episode_is_restored_from_the_source():
    title = "Lá Thư"
    first = (
        "Sương sớm còn đọng trên lá cỏ ven bờ, mùi mặn mòi của biển len lỏi vào từng ngóc ngách làng chài khi Nam "
        "và chị Liên bước chân ra bến cá."
    )
    second = "Hai đứa trẻ khoác chiếc áo cũ vá lại nhiều lần, tay vác rổ tre đi bộ nhanh trên con đường đất."
    lead_in = "Chị Liên vừa liếc nhìn mặt biển gợn sóng vừa hỏi:"
    quote = '"Sáng nay nước rút mau lắm hả Nam?"'
    segments = _segments(f"{title}\n\n{first}", second, quote)

    _realign_segments_to_source(segments, f"{title}\n\n{first} {second} {lead_in} {quote}")

    assert [s["novel_text"] for s in segments] == [f"{title} {first}", f"{second} {lead_in}", quote]


def test_segments_covering_a_small_part_of_a_long_source_are_left_for_the_coverage_check():
    sentence = "Biển vẫn rì rào như mọi ngày, những con sóng nhỏ vỗ vào bờ cát dưới nắng chiều."
    segments = _segments(sentence)
    expected = [dict(s) for s in segments]

    _realign_segments_to_source(segments, " ".join([sentence, *(f"Ngày thứ {i} Nam ra biển." for i in range(9))]))

    assert segments == expected

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

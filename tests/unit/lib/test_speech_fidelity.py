"""A transcript of a film's sound is compared with its narration by words, as OpenMontage's final review does."""

from __future__ import annotations

from lib.speech_fidelity import MIN_WORD_ACCURACY, compare, words

NARRATION = "Ông Ba không trả lời. Ông cúi xuống, hai tay siết lại dây neo quanh cọc tre."


def test_punctuation_and_capitals_of_a_transcript_never_count():
    result = compare(NARRATION, "ông ba không trả lời ông cúi xuống hai tay siết lại dây neo quanh cọc tre")
    assert result.accuracy == 1.0
    assert result.misheard == ()


def test_a_misread_tone_and_a_skipped_clause_lower_the_accuracy_and_are_named():
    result = compare(NARRATION, "Ông Bà không trả lời. Ông cúi xuống.")
    assert result.accuracy < MIN_WORD_ACCURACY
    assert result.misheard[:2] == ("ba", "hai")


def test_symbols_read_aloud_are_found_only_when_the_script_does_not_say_them():
    assert compare("Bến đò cũ.", "Bến đò cũ dấu sao", language="vi").spoken_symbols == ("dấu sao",)
    assert compare("Dấu sao trên vải.", "Dấu sao trên vải.", language="vi").spoken_symbols == ()


def test_a_script_without_spaces_is_compared_by_character():
    assert words("天亮就走。") == ["天", "亮", "就", "走"]
    assert compare("天亮就走。", "天亮就走", language="zh").accuracy == 1.0

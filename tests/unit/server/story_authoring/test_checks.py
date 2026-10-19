from __future__ import annotations

import pytest

from server.story_authoring.checks import (
    VIETNAMESE_PUNCTUATION,
    SceneLengthWindow,
    Severity,
    check_scene_prose,
    count_syllables,
    dialogue_lines,
    ends_cleanly,
    find_intra_chapter_near_duplicate,
    foreign_words,
    is_vietnamese_syllable,
    meta_leaks,
    repeated_trigram_excess,
    strip_copied_sentences,
    strip_intra_chapter_near_duplicate,
    strip_markup,
    strip_replayed_sentences,
    unknown_names,
)

SENTENCES = (
    "Trời vừa hửng sáng thì Minh đẩy cánh cổng, bản lề kêu lên một tiếng dài.",
    "Anh đứng trên bậc thềm nhìn rất lâu, cây táo ngoài sân đã cao hơn trong trí nhớ.",
    "Mẹ nhóm lửa trong bếp, khói chậm rãi bốc lên qua khe mái ngói.",
    "Anh nhớ buổi sáng mười năm trước khi rời đi, cũng sương mù, cũng lặng im như thế.",
    "Lan ngẩng lên từ bên giếng, chiếc thùng gỗ trong tay khẽ chao, nước đổ xuống phiến đá xanh.",
    "“Anh về rồi.” Cô nói, giọng rất khẽ, như sợ làm kinh động điều gì.",
    "Anh không đáp, chỉ đặt ba lô cạnh cửa rồi cúi xuống nhặt chiếc lá rơi.",
)


@pytest.mark.parametrize(
    "word", ["nghiêng", "quyết", "gì", "giường", "người", "khuya", "khuỷu", "hoẵng", "đường", "ạ", "ơi", "Minh"]
)
def test_vietnamese_syllables_are_recognized(word):
    assert is_vietnamese_syllable(word)


@pytest.mark.parametrize("word", ["suddenly", "okay", "and", "smile", "sorry", "please", "really", "fine", "jazz"])
def test_english_words_are_not_vietnamese_syllables(word):
    assert not is_vietnamese_syllable(word)


def test_foreign_words_ignore_vietnamese_homographs_and_count_code_mixing():
    assert foreign_words("Anh ấy bỗng nhiên suddenly dừng lại, okay, rồi to tiếng.") == ["suddenly", "okay"]


def test_syllables_count_words_split_on_hyphens_and_skip_numbers():
    assert count_syllables("Trời vừa hửng sáng, ông Chu-Văn đẩy cửa lúc 6 giờ.") == 11


def test_repeated_trigrams_count_only_beyond_the_second_use():
    assert repeated_trigram_excess("anh nhìn em " * 4) == 7
    assert repeated_trigram_excess(" ".join(SENTENCES)) == 0


def test_replayed_sentences_are_removed_and_first_occurrences_kept():
    text = " ".join([*SENTENCES, *SENTENCES[2:5]])
    cleaned, hits = strip_replayed_sentences(text)
    assert cleaned == " ".join(SENTENCES)
    assert len(hits) == 3


def test_short_repeated_sentences_are_kept():
    text = "Anh gật đầu. Minh đi ra sân. Anh gật đầu."
    assert strip_replayed_sentences(text) == (text, ())


def test_the_donor_heuristic_applied_to_vietnamese_removes_a_sentence_that_is_not_repeated():
    """Evidence for the recorded S08 deviation: the Han-tuned anchor heuristics over-remove on Vietnamese."""
    sentences = [
        "Trời vừa hửng sáng thì Minh đẩy cánh cổng, bản lề kêu lên một tiếng dài và khàn.",
        "Anh đứng trên bậc thềm nhìn rất lâu, cây táo ngoài sân đã cao hơn trong trí nhớ.",
        "Mẹ nhóm lửa trong bếp, khói chậm rãi bốc lên qua khe mái ngói rồi tan vào sương.",
        "Lan ngẩng lên từ bên giếng, chiếc thùng gỗ trong tay khẽ chao, nước đổ xuống đá.",
    ]
    text = " ".join([*sentences, *sentences[1:3]])
    donor_cleaned, _ = strip_intra_chapter_near_duplicate(text, profile=VIETNAMESE_PUNCTUATION)
    runtime_cleaned, _ = strip_replayed_sentences(text)
    assert sentences[3] not in donor_cleaned
    assert runtime_cleaned == " ".join(sentences)


def test_clean_prose_has_no_near_duplicate():
    assert find_intra_chapter_near_duplicate(" ".join(SENTENCES * 1)) is None


def test_meta_leaks_and_endings():
    assert meta_leaks("# Cảnh 1\nMinh mở cửa.\nGhi chú: viết thêm") == ["# Cảnh 1", "Ghi chú: viết thêm"]
    assert meta_leaks(" ".join(SENTENCES)) == []
    assert ends_cleanly("Anh về rồi.”")
    assert not ends_cleanly("Anh về rồi và")


def test_dialogue_lines_count_dash_and_quote_openers():
    assert dialogue_lines("— Anh về rồi à?\n“Ừ.”\nMinh im lặng.") == 2


def test_unknown_names_skip_sentence_starts_dialogue_and_bible_names():
    text = "Minh gặp Lan ở cổng. Hôm ấy Hùng cũng tới. — Bà Tư đâu? Minh hỏi, rồi gọi Hùng lần nữa."
    found = unknown_names(text, {"Minh", "Lan"})
    assert found == {"Hùng": 2}


def _scene(*parts: str) -> str:
    return " ".join(parts)


def test_a_clean_scene_has_only_length_findings():
    findings = check_scene_prose(
        _scene(*SENTENCES),
        node_id="s",
        window=SceneLengthWindow(minimum=50, maximum=200),
        allowed_names={"Minh", "Lan"},
    )
    assert findings == ()


def test_scene_findings_carry_the_policy_severities():
    text = _scene("# Cảnh 2", *SENTENCES, "Anh ấy suddenly okay sorry cười 突然", "Hùng tới. Rồi Hùng đi và")
    findings = {
        f.code: f
        for f in check_scene_prose(text, node_id="s", window=SceneLengthWindow(), allowed_names={"Minh", "Lan"})
    }

    assert findings["CJK"].severity is Severity.HARD_INTEGRITY
    assert findings["UNTERMINATED"].severity is Severity.HARD_INTEGRITY
    assert findings["META_LEAK"].severity is Severity.HARD_STRUCTURAL
    assert findings["FOREIGN_WORDS"].severity is Severity.NARRATIVE_CRITICAL
    assert findings["LENGTH_WINDOW"].severity is Severity.STYLISTIC
    assert findings["CJK"].blocking
    assert not findings["LENGTH_WINDOW"].blocking
    assert "突" in findings["CJK"].quote


def test_an_over_long_scene_is_hard_structural():
    findings = check_scene_prose(
        _scene(*SENTENCES * 10), node_id="s", window=SceneLengthWindow(hard_maximum=100), allowed_names={"Minh", "Lan"}
    )
    assert [f.code for f in findings if f.severity is Severity.HARD_STRUCTURAL] == ["LENGTH_HARD"]


def test_a_sentence_after_a_single_quote_is_not_a_name():
    text = "Ông nói: 'Nhà này không bán, con à.' Nhưng giọng ấy đã xa. Lan đáp: ‘Dạ.’ Rồi im lặng."
    assert unknown_names(text, {"Lan"}) == {}


EARLIER = "Minh ngồi yên trên bậc thềm chính, tay vẫn ôm chặt phong thư bên người. Gió thổi."


def test_a_sentence_copied_from_an_earlier_scene_is_found_and_removed():
    text = (
        "Lan bước vào sân và đặt giỏ xuống. Minh ngồi yên trên bậc thềm chính, tay vẫn ôm chặt phong thư bên người.\n\n"
        "Gió thổi. Hai anh em im lặng rất lâu dưới hiên nhà."
    )
    findings = check_scene_prose(
        text, node_id="s", window=SceneLengthWindow(1, 1000, 2000), allowed_names={"Minh", "Lan"}, earlier=[EARLIER]
    )
    assert [f.code for f in findings if f.code == "CROSS_SCENE_REPLAY"] == ["CROSS_SCENE_REPLAY"]
    cleaned, copied = strip_copied_sentences(text, [EARLIER])
    assert copied == ("Minh ngồi yên trên bậc thềm chính, tay vẫn ôm chặt phong thư bên người.",)
    assert cleaned == "Lan bước vào sân và đặt giỏ xuống.\n\nGió thổi. Hai anh em im lặng rất lâu dưới hiên nhà."


def test_markdown_emphasis_is_a_structural_finding_with_a_deterministic_fix():
    text = "Cha viết: *'Ngày mai sẽ gửi thư cho con.'* Minh lặng người."
    findings = check_scene_prose(text, node_id="s", window=SceneLengthWindow(1, 1000, 2000), allowed_names=set())
    assert "MARKUP" in {f.code for f in findings}
    assert strip_markup(text) == "Cha viết: 'Ngày mai sẽ gửi thư cho con.' Minh lặng người."

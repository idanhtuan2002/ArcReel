"""An adapted episode keeps its source's words and speakers: quotes stay with who says them, nobody absent speaks,
and a narration script invents no dialogue or long narration."""

from __future__ import annotations

from lib.adaptation_fidelity import SpokenLine, fidelity_problems, quotes, source_speaker

# The episode source of the trial in which an adaptation gave Ông Ba's words to Chú Tư and invented a closing line.
SOURCE = """Ông Ba không trả lời.

Ông cúi xuống, hai tay siết lại dây neo quanh cọc tre, kéo mạnh một cái cho chắc. Nước sông vỗ vào mũi đò, từng \
đợt ục ục, nghe như ai đập tay vào mạn gỗ mục.

“Bố sáu mươi tám rồi,” Hải nói, “đâu còn phải thức khuya dậy sớm vì con đò nữa.” Ông Ba đứng thẳng lên, phủi bụi \
trên ống quần, mắt vẫn nhìn xuống khoang đò.

“Con nói phải rồi.” Ông Ba nói, giọng gọn.

“Nhưng bến này chưa ai dọn. Đò còn đó thì còn phải coi.”"""
NAMES = ["Ông Ba", "Hải", "Linh", "Chú Tư"]


def _check(lines: list[SpokenLine], mode: str = "narration", previous_tail: str = "") -> list[str]:
    return fidelity_problems(lines, mode=mode, source=SOURCE, previous_tail=previous_tail, names=NAMES)


def test_the_source_names_a_speaker_only_where_it_says_so_plainly():
    spans = quotes(SOURCE)
    assert [source_speaker(SOURCE, spans, index, NAMES) for index in range(len(spans))] == [
        "Hải",  # "…,” Hải nói
        "Hải",  # Hải nói, “… — the action after it names Ông Ba without a speech verb
        "Ông Ba",
        None,  # a quote alone in its paragraph is left to the reader
    ]


def test_a_faithful_adaptation_passes():
    lines = [
        SpokenLine(1, "narration", "", "Ông Ba không trả lời, chỉ siết lại dây neo quanh cọc tre."),
        SpokenLine(1, "dialogue", "Hải", "Bố sáu mươi tám rồi, đâu còn phải thức khuya dậy sớm vì con đò nữa."),
        SpokenLine(1, "dialogue", "Ông Ba", "Con nói phải rồi."),
        SpokenLine(2, "dialogue", "Ông Ba", "Nhưng bến này chưa ai dọn. Đò còn đó thì còn phải coi."),
    ]
    assert _check(lines) == []


def test_the_trial_adaptation_is_refused_for_each_of_its_faults():
    lines = [
        SpokenLine(1, "narration", "", "Không có câu trả lời nào."),
        SpokenLine(1, "dialogue", "Chú Tư", "Đã chắc rồi đó."),
        SpokenLine(1, "dialogue", "Hải", "Bố sáu mươi tám rồi, mà chẳng cần thức khuya dậy sớm vì con đò nữa"),
        SpokenLine(2, "dialogue", "Chú Tư", "Bến nọ vẫn chẳng ai quét, đò vẫn ở đó, nên mình phải chèo"),
        SpokenLine(
            2,
            "narration",
            "",
            "Và tại sao ông lại nói rằng bến chưa bao giờ được dọn, dù cả tuần nay chẳng có ai gọi đò",
        ),
    ]
    problems = _check(lines)
    assert len(problems) == 3
    assert sum("'Chú Tư' speaks but is not in this episode's source" in problem for problem in problems) == 2
    assert "says what the source does not" in problems[2]


def test_a_quoted_line_given_to_another_character_is_refused_in_both_forms():
    swapped = [
        SpokenLine(1, "dialogue", "Ông Ba", "Bố sáu mươi tám rồi, đâu còn phải thức khuya dậy sớm vì con đò nữa"),
        SpokenLine(1, "dialogue", "Hải", "Con nói phải rồi."),
    ]
    for mode in ("narration", "drama"):
        problems = _check(swapped, mode)
        assert len(problems) == 2
        assert "in the source 'Hải' says" in problems[0]
        assert "not 'Ông Ba'" in problems[0]
        assert "in the source 'Ông Ba' says" in problems[1]
        assert "not 'Hải'" in problems[1]


def test_drama_may_dramatize_new_dialogue_for_a_character_of_the_episode_but_narration_may_not():
    invented = [SpokenLine(1, "dialogue", "Hải", "Bố nghỉ đi, để con lo cái bến này.")]
    assert _check(invented, "drama") == []
    (problem,) = _check(invented, "narration")
    assert "is not in the source" in problem


def test_a_speaker_named_only_at_the_end_of_the_previous_episode_may_speak():
    line = [SpokenLine(1, "dialogue", "Linh", "Ông Ba ơi, con về rồi.")]
    assert "not in this episode's source" in _check(line, "drama")[0]
    assert _check(line, "drama", previous_tail="Linh đứng ở đầu bến, gọi với theo.") == []


def test_english_and_chinese_attributions_are_read():
    english = '"We leave at dawn," said Ann. Tom shrugged. "Then I stay," Tom replied.'
    spans = quotes(english)
    assert [source_speaker(english, spans, index, ["Ann", "Tom"]) for index in range(len(spans))] == ["Ann", "Tom"]
    chinese = "林说：“天亮就走。”王伟摇头。“那我留下。”王伟答道。"
    spans = quotes(chinese)
    assert [source_speaker(chinese, spans, index, ["林", "王伟"]) for index in range(len(spans))] == ["林", "王伟"]
    problems = fidelity_problems(
        [SpokenLine(1, "dialogue", "王伟", "天亮就走。")],
        mode="drama",
        source=chinese,
        previous_tail="",
        names=["林", "王伟"],
    )
    assert len(problems) == 1
    assert "in the source '林' says" in problems[0]


def test_short_narration_lines_and_cjk_sources_are_not_judged_by_their_words():
    assert _check([SpokenLine(1, "narration", "", "Gió nổi lên, đêm đã khuya.")]) == []
    chinese = "林说：“天亮就走。”"
    lines = [SpokenLine(1, "narration", "", "第二天清晨，渡口空无一人，只剩下一条旧船在风里轻轻摇晃。")]
    assert fidelity_problems(lines, mode="narration", source=chinese, previous_tail="", names=["林"]) == []

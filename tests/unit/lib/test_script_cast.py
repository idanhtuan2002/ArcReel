"""A segment that names a registered character it does not list as appearing is reported, never refused."""

from __future__ import annotations

from lib.script_cast import UnlistedCast, unlisted_cast
from server.text_generation import unlisted_cast_soft_violations

CHARACTERS = ["Ông Ba", "Hải", "Linh"]
SEGMENTS = [
    {"segment_id": "E2S01", "novel_text": "Ông Ba không trả lời.", "characters_in_segment": ["Ông Ba"]},
    {
        "segment_id": "E2S02",
        "novel_text": "“Bố sáu mươi tám rồi,” Hải nói. Ông Ba đứng thẳng lên.",
        "characters_in_segment": ["Hải"],
    },
    {"segment_id": "E2S03", "novel_text": "Nước sông vỗ vào mũi đò.", "characters_in_segment": []},
]


def test_named_but_unlisted_characters_are_found_per_segment():
    assert unlisted_cast(SEGMENTS, CHARACTERS) == [UnlistedCast(1, "E2S02", ("Ông Ba",))]


def test_a_name_inside_a_longer_word_is_not_a_mention():
    segments = [{"segment_id": "E1S01", "novel_text": "Linhh chạy.", "characters_in_segment": []}]
    assert unlisted_cast(segments, CHARACTERS) == []


def test_the_script_plan_receipt_says_it_without_refusing():
    (line,) = unlisted_cast_soft_violations(SEGMENTS, CHARACTERS)
    assert "E2S02" in line
    assert "['Ông Ba']" in line
    assert "仅被提及则无需改动" in line
    assert unlisted_cast_soft_violations(SEGMENTS, []) == []

"""Deterministic checks against scenes real local-model runs wrote (``tests/fixtures/story_real``): each check fires
exactly on the scenes that carry its failure and on no scene of a committed story."""

from __future__ import annotations

import itertools
import json
from pathlib import Path

from server.story_authoring.cast_checks import pov_findings, pov_person_findings
from server.story_authoring.checks import (
    count_syllables,
    foreign_script,
    json_leaks,
    meta_narration,
    notes_leaks,
    strip_json_leaks,
    strip_notes_leaks,
)
from server.story_authoring.prompts.schemas import SeedCharacter

FIXTURES = Path(__file__).parents[3] / "fixtures" / "story_real"
CAST = [
    SeedCharacter(
        name="X", role="r", relation_to_protagonist="r", description="d", goal="g", gender="nam", address="anh"
    )
]


def _scenes() -> dict[str, str]:
    scenes: dict[str, str] = {}
    for path in sorted(FIXTURES.glob("*.json")):
        story = json.loads(path.read_text(encoding="utf-8"))
        for chapter in story["chapters"]:
            for number, text in enumerate(chapter["scenes"], 1):
                scenes[f"{story['run_id'][6:14]} {chapter['chapter']}.{number}"] = text
    return scenes


def test_the_new_checks_fire_only_on_the_scenes_that_drifted():
    scenes = _scenes()
    assert len(scenes) == 42
    hits = {
        key: sorted(
            [
                *(["JSON_LEAK"] if json_leaks(text) else []),
                *(["NOTES_LEAK"] if notes_leaks(text) else []),
                *(["META_NARRATION"] if meta_narration(text) else []),
                *(["FOREIGN_SCRIPT"] if foreign_script(text) else []),
                *(f.code for f in pov_findings(CAST, None, text, node_id=key)),
                *(
                    f.code
                    for f in pov_person_findings("ngôi thứ ba", text, node_id=key, syllables=count_syllables(text))
                ),
            ]
        )
        for key, text in scenes.items()
    }
    assert {key: codes for key, codes in hits.items() if codes} == {
        "31adf836 1.1": ["FOREIGN_SCRIPT", "NARRATION_EM"],
        "31adf836 1.2": ["JSON_LEAK", "NARRATION_EM"],
        "31adf836 1.3": ["POV_PERSON"],
        "14eec8e8 2.5": ["META_NARRATION"],
        "3a267760 1.2": ["POV_PERSON"],
        "7d7ff17b 3.1": ["NOTES_LEAK"],
    }


def test_json_keys_around_paragraphs_are_removed_and_the_prose_kept():
    leaked = _scenes()["31adf836 1.2"]
    clean = strip_json_leaks(leaked)
    assert json_leaks(clean) == []
    assert '"paragraph' not in clean
    assert "{" not in clean
    assert "Giọng nói của em lại vang lên, đầy tự tin" in clean
    assert count_syllables(clean) > 0.95 * count_syllables(leaked) - 40


def test_a_paragraph_of_notes_on_the_cast_is_removed():
    leaked = _scenes()["7d7ff17b 3.1"]
    clean = strip_notes_leaks(leaked)
    assert notes_leaks(clean) == []
    assert "minh: cô gái" not in clean
    assert clean.count("\n\n") == leaked.count("\n\n") - 1


def _seams() -> list[tuple[str, dict, dict]]:
    seams = []
    for path in sorted(FIXTURES.glob("*.json")):
        story = json.loads(path.read_text(encoding="utf-8"))
        chapters = story["chapters"]
        seams.extend(
            (f"{story['run_id'][6:14]} {a['chapter']}", a, b)
            for a, b in itertools.pairwise(chapters)
            if a["scenes"] and a.get("beats") and b.get("beats")
        )
    return seams


def test_no_real_chapter_writes_the_next_ones_beats_and_one_that_does_is_found():
    from server.story_authoring.craft_checks import next_chapter_leak_findings

    seams = _seams()
    assert len(seams) == 10
    for key, chapter, following in seams:
        text = "\n\n".join(chapter["scenes"])
        assert next_chapter_leak_findings(text, chapter["beats"], following["beats"], node_id=key) == (), key
    overshoots = [(key, a, b) for key, a, b in seams if len(b["scenes"]) >= 3]
    assert len(overshoots) == 7
    for key, chapter, following in overshoots:
        # The chapter goes on into two of the next chapter's scenes.
        text = "\n\n".join(chapter["scenes"] + following["scenes"][:2])
        [leak] = next_chapter_leak_findings(text, chapter["beats"], following["beats"], node_id=key)
        assert leak.code == "NEXT_CHAPTER_LEAK"
        assert leak.quote in text


def test_an_age_is_checked_only_where_the_text_states_it_for_certain():
    from server.story_authoring.cast_checks import age_findings

    lan = SeedCharacter(
        name="Lan", role="r", relation_to_protagonist="r", description="d", goal="g", gender="nữ", address="cô", age=24
    )
    assert age_findings([lan], list(_scenes().items())) == ()
    wrong = [("s", "Lan, hai mươi tám tuổi, đứng trước cửa."), ("t", "Lan năm nay 25 tuổi.")]
    [found] = age_findings([lan], wrong)
    assert (found.code, found.node_id, found.quote) == ("CAST_AGE", "s", "Lan, hai mươi tám tuổi")
    # A memory or a relative's age beside the name is not read as hers; in a book years pass.
    assert age_findings([lan], [("s", "Lan nhớ năm mười tuổi, em trai Lan 9 tuổi.")]) == ()
    assert age_findings([lan], [("s", "Lan năm nay 30 tuổi.")], years_pass=True) == ()
    assert "24 tuổi" in lan.locked_line()

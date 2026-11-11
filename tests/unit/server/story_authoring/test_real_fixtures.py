"""Deterministic checks against scenes real local-model runs wrote (``tests/fixtures/story_real``): each check fires
exactly on the scenes that carry its failure and on no scene of a committed story."""

from __future__ import annotations

import json
from pathlib import Path

from server.story_authoring.cast_checks import pov_findings, pov_person_findings
from server.story_authoring.checks import (
    count_syllables,
    foreign_script,
    json_leaks,
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

"""A narration delivery cue is voiced by the voices that support it and never subtitled."""

from __future__ import annotations

from lib.narration_delivery import canonical_narration_text, synthesis_text
from lib.speech_artifact_provenance import project_subtitle_utterances
from lib.speech_composition import admit_script_unit


def _segment(cue: object) -> dict:
    return {
        "segment_id": "E1S01",
        "novel_text": "Cô đứng lặng trước cánh cửa cũ.",
        "characters_in_segment": [],
        "video_prompt": {"action": "a", "camera_motion": "Static", "ambiance_audio": "", "dialogue": []},
        "narration_cue": cue,
    }


def test_the_cue_leads_the_narration_text_but_not_the_subtitles():
    preparation = admit_script_unit("segments", _segment("sigh")).preparation

    assert canonical_narration_text(preparation) == "[thở dài] Cô đứng lặng trước cánh cửa cũ."
    assert [u.text for u in project_subtitle_utterances(preparation)] == ["Cô đứng lặng trước cánh cửa cũ."]


def test_no_cue_or_an_unknown_one_leaves_the_text_as_written():
    for cue in (None, "none", "scream"):
        preparation = admit_script_unit("segments", _segment(cue)).preparation
        assert canonical_narration_text(preparation) == "Cô đứng lặng trước cánh cửa cũ."


def test_only_voices_that_speak_the_tags_receive_them():
    text = "[cười] Anh bật cười."

    assert synthesis_text(text, "vieneu-tts-v3-turbo") == text
    assert synthesis_text(text, "gpt-4o-mini-tts") == "Anh bật cười."

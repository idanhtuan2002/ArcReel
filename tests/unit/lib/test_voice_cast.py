"""Voices for the speaking characters of a drama (ADR-0166)."""

from __future__ import annotations

import asyncio
import json

import pytest

from lib.text_backends.base import TextGenerationRequest, TextGenerationResult
from lib.voice_cast import CastVoice, Speaker, VoiceCast, VoiceCastError, assign_voices, cast_problems, speakers_of

CATALOG = [
    CastVoice("Charon", "Charon (Informative)", "low"),
    CastVoice("Kore", "Kore (Firm)", "high"),
    CastVoice("Puck", "Puck (Upbeat)", "low"),
    CastVoice("Leda", "Leda (Youthful)", "high"),
    CastVoice("Zephyr", "Zephyr (Bright)"),
]
SPEAKERS = [Speaker("Ông Bảy", "lão lái đò sáu mươi tuổi, trầm lặng", 6), Speaker("Hòa", "cô gái hai mươi tuổi", 4)]


def _cast(*picks: tuple[str, str, str]) -> VoiceCast:
    return VoiceCast.model_validate(
        {"picks": [{"character": c, "sex": s, "age": "adult", "voice": v, "reason": ""} for c, s, v in picks]}
    )


def test_a_cast_is_checked_for_catalog_narrator_register_and_shared_voices():
    good = _cast(("Ông Bảy", "male", "Puck"), ("Hòa", "female", "Leda"))
    assert cast_problems(good, SPEAKERS, CATALOG, narrator="Charon") == []
    wrong = _cast(("Ông Bảy", "male", "Leda"), ("Hòa", "female", "Leda"))
    problems = cast_problems(wrong, SPEAKERS, CATALOG, narrator="Charon")
    assert "Ông Bảy is male but Leda is a high voice" in problems
    assert any("share a voice" in p for p in problems)
    narrator = _cast(("Ông Bảy", "male", "Charon"), ("Hòa", "female", "Nova"))
    problems = cast_problems(narrator, SPEAKERS, CATALOG, narrator="Charon")
    assert "Ông Bảy: Charon is the narrator's voice" in problems
    assert "Hòa: 'Nova' is not in the catalog" in problems
    assert cast_problems(_cast(("Hòa", "female", "Kore")), SPEAKERS, CATALOG, narrator="Charon") == [
        "no voice for ['Ông Bảy']"
    ]
    unmeasured = _cast(("Ông Bảy", "male", "Zephyr"), ("Hòa", "female", "Kore"))
    assert cast_problems(unmeasured, SPEAKERS, CATALOG, narrator="Charon") == []


def test_a_refused_cast_goes_back_with_its_problems():
    answers = [
        {"picks": [{"character": "Ông Bảy", "sex": "male", "age": "elder", "voice": "Kore"}]},
        {
            "picks": [
                {"character": "Ông Bảy", "sex": "male", "age": "elder", "voice": "Puck"},
                {"character": "Hòa", "sex": "female", "age": "young", "voice": "Leda"},
            ]
        },
    ]
    prompts: list[str] = []

    async def generate(request: TextGenerationRequest) -> TextGenerationResult:
        prompts.append(request.prompt)
        return TextGenerationResult(text=json.dumps(answers.pop(0)), model="m", provider="p")

    voices = asyncio.run(assign_voices(SPEAKERS, CATALOG, narrator="Charon", generate=generate))
    assert voices == {"Ông Bảy": "Puck", "Hòa": "Leda"}
    assert "Charon" not in prompts[0].split("Voices (")[1].split("\n", 1)[1]
    assert "Ông Bảy is male but Kore is a high voice" in prompts[1]

    async def bad(_request: TextGenerationRequest) -> TextGenerationResult:
        return TextGenerationResult(text="{}", model="m", provider="p")

    with pytest.raises(VoiceCastError, match="NO_PASSING_CAST"):
        asyncio.run(assign_voices(SPEAKERS, CATALOG, narrator="Charon", generate=bad))


def test_speakers_are_the_characters_with_dialogue_lines():
    units = [
        {
            "utterances": [
                {"kind": "dialogue", "speaker": "Hòa", "text": "Bác ơi!"},
                {"kind": "dialogue", "speaker": "Ông Bảy", "text": "Ừ."},
            ]
        },
        {"utterances": [{"kind": "voiceover", "speaker": None, "text": "Đêm xuống."}]},
        {"utterances": [{"kind": "dialogue", "speaker": "Hòa", "text": "Mình đi thôi."}]},
    ]
    found = speakers_of(units, {"Hòa": {"description": "cô gái"}})
    assert [(s.name, s.lines, s.description) for s in found] == [("Hòa", 2, "cô gái"), ("Ông Bảy", 1, "")]


def test_the_speakers_to_cast_are_the_characters_of_spoken_scenes_without_a_voice_for_the_route():
    from lib.voice_cast import record_voices, speakers_to_cast

    scenes = [
        {"scene_id": "E1S01", "utterances": [{"kind": "dialogue", "speaker": "Hòa", "text": "Bác ơi!"}]},
        {"scene_id": "E1S02", "video_prompt": {"dialogue": [{"speaker": "Ông Ba", "line": "Chuyến cuối."}]}},
        {"scene_id": "E1S03", "utterances": [{"kind": "dialogue", "speaker": "Hòa", "text": "Cháu đi."}]},
    ]
    characters = {
        "Hòa": {"description": "cô gái", "tts_voice": "Leda", "tts_voice_route": "custom-2/old-tts"},
        "Ông Ba": {"description": "lão lái đò", "tts_voice": "Puck", "tts_voice_route": "custom-7/gemini-tts"},
    }
    missing = speakers_to_cast("scenes", scenes, characters, route="custom-7/gemini-tts")
    assert missing == [Speaker("Hòa", "cô gái", 2)]

    project = {"characters": characters}
    record_voices(project, {"Hòa": "Kore"}, route="custom-7/gemini-tts")
    assert project["characters"]["Hòa"] == {
        "description": "cô gái",
        "tts_voice": "Kore",
        "tts_voice_route": "custom-7/gemini-tts",
    }
    assert speakers_to_cast("scenes", scenes, project["characters"], route="custom-7/gemini-tts") == []


def test_a_speaker_who_is_not_a_registered_character_is_neither_cast_nor_registered():
    from lib.voice_cast import record_voices, speakers_to_cast

    scenes = [{"scene_id": "E1S01", "utterances": [{"kind": "dialogue", "speaker": "Người lạ", "text": "Đi thôi."}]}]
    characters = {"Hòa": {"description": "cô gái"}}
    assert speakers_to_cast("scenes", scenes, characters, route="r") == []
    project = {"characters": {"Hòa": {"description": "cô gái"}}}
    record_voices(project, {"Hòa": "Kore", "Người lạ": "Puck"}, route="r")
    assert set(project["characters"]) == {"Hòa"}

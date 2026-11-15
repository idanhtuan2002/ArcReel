"""Character lines spoken by TTS in their speakers' voices (ADR-0166)."""

from __future__ import annotations

import pytest

from lib.artifact_manifest import ArtifactBasisDescriptor
from lib.narration_delivery import (
    USE_TTS,
    NarrationTtsStatus,
    TtsSynthesisSettings,
    build_character_audio_basis_from_canonical_text,
    build_narration_audio_basis,
    canonical_speech_text,
    character_lines,
    prepare_narration_delivery,
    tts_spoken,
    with_character_voices,
)
from lib.speech_composition import (
    SpeechFieldLocation,
    SpeechMode,
    SpeechOwner,
    SpeechPreparation,
    SpeechUtterance,
)

SETTINGS = TtsSynthesisSettings(provider_id="custom-7", model_id="gemini-3.8-flash-tts", voice="Charon", speed=None)
ROUTE = "custom-7/gemini-3.8-flash-tts"


def _project(delivery: str | None = "tts") -> dict:
    project: dict = {
        "characters": {
            "Hòa": {"description": "cô gái", "tts_voice": "Leda", "tts_voice_route": ROUTE},
            "Ông Bảy": {"description": "lão lái đò", "tts_voice": "Puck", "tts_voice_route": ROUTE},
            "Lan": {"description": "cô bé", "tts_voice": "Kore", "tts_voice_route": "custom-2/vieneu-tts-v3-turbo"},
        }
    }
    if delivery is not None:
        project["character_speech_delivery"] = delivery
    return project


def _dialogue(*lines: tuple[str, str]) -> SpeechPreparation:
    return SpeechPreparation(
        unit_id="E1S02",
        mode=SpeechMode.CHARACTER_SPEECH,
        utterances=tuple(
            SpeechUtterance(
                owner=SpeechOwner.CHARACTER,
                text=text,
                speaker=speaker,
                location=SpeechFieldLocation(("utterances", index, "text")),
            )
            for index, (speaker, text) in enumerate(lines)
        ),
    )


def test_voices_are_the_characters_chosen_for_the_current_route_only_when_the_project_voices_them():
    voiced = with_character_voices(SETTINGS, _project())
    assert voiced.character_voices == (("Hòa", "Leda"), ("Ông Bảy", "Puck"))
    assert with_character_voices(SETTINGS, _project(None)).character_voices is None
    assert with_character_voices(voiced, _project("video")).character_voices is None
    assert tts_spoken(SpeechMode.CHARACTER_SPEECH, _project())
    assert not tts_spoken(SpeechMode.CHARACTER_SPEECH, _project(None))
    assert tts_spoken(SpeechMode.NARRATOR_VOICEOVER, _project(None))
    assert not tts_spoken(SpeechMode.SILENT, _project())


def test_a_character_unit_has_a_line_basis_that_restores_from_its_recorded_text():
    settings = with_character_voices(SETTINGS, _project())
    unit = _dialogue(("Hòa", " Bác ơi, đò còn chạy không? "), ("Ông Bảy", "Chuyến cuối."))
    assert character_lines(unit, settings) == [
        ("Hòa", "Leda", "Bác ơi, đò còn chạy không?"),
        ("Ông Bảy", "Puck", "Chuyến cuối."),
    ]
    basis = build_narration_audio_basis(unit, settings)
    assert basis.kind_version == 2
    text = canonical_speech_text(unit, settings)
    assert text == "Hòa: Bác ơi, đò còn chạy không?\nÔng Bảy: Chuyến cuối."
    assert build_character_audio_basis_from_canonical_text(text, settings).digest == basis.digest
    rerouted = with_character_voices(SETTINGS, {**_project(), "characters": {"Hòa": _project()["characters"]["Hòa"]}})
    assert build_narration_audio_basis(_dialogue(("Hòa", "Bác ơi")), rerouted).digest != basis.digest


def test_a_speaker_without_a_voice_for_the_route_has_no_basis():
    settings = with_character_voices(SETTINGS, _project())
    with pytest.raises(ValueError, match="'Lan' has no voice"):
        build_narration_audio_basis(_dialogue(("Lan", "Chị ơi!")), settings)


def test_a_character_unit_is_deliverable_by_tts_only_when_its_characters_are_voiced():
    unit = _dialogue(("Hòa", "Bác ơi"))
    voiced = prepare_narration_delivery(
        delivery=USE_TTS,
        preparation=unit,
        artifact_path="audio/E1S02.wav",
        settings=with_character_voices(SETTINGS, _project()),
        evidence=None,
    )
    assert voiced.tts_status is NarrationTtsStatus.MISSING
    silent = prepare_narration_delivery(
        delivery=USE_TTS,
        preparation=unit,
        artifact_path="audio/E1S02.wav",
        settings=with_character_voices(SETTINGS, _project("video")),
        evidence=None,
    )
    assert silent.tts_status is NarrationTtsStatus.NOT_APPLICABLE


def test_a_voiced_character_version_keeps_its_voices_for_currency():
    from lib.artifact_version_provenance import parse_typed_audio_settings

    settings = with_character_voices(SETTINGS, _project())
    unit = _dialogue(("Hòa", "Bác ơi"), ("Ông Bảy", "Chuyến cuối."))
    basis = build_narration_audio_basis(unit, settings)
    record = {
        "prompt": canonical_speech_text(unit, settings),
        "tts_provider_id": SETTINGS.provider_id,
        "tts_model_id": SETTINGS.model_id,
        "tts_voice": SETTINGS.voice,
        "tts_speed": None,
        "tts_character_voices": [list(pair) for pair in settings.character_voices or ()],
        "tts_basis_digest": basis.digest,
        "tts_actual_duration_seconds": 2.5,
        "artifact_audio_basis": ArtifactBasisDescriptor.from_basis(basis).to_dict(),
        "artifact_episode": 1,
        "execution_script_file": "scripts/episode_1.json",
    }
    parsed = parse_typed_audio_settings(record)
    assert parsed.character_voices == settings.character_voices
    assert build_narration_audio_basis(unit, parsed).digest == basis.digest

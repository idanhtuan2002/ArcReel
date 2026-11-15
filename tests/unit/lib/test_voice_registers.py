"""A route's voices carry the registers measured for the endpoint whose catalog they are (ADR-0166)."""

from __future__ import annotations

from lib.audio_backends.base import VoiceOption
from lib.voice_registers import route_cast_catalog


def test_a_measured_catalog_is_found_by_its_voices_and_an_unmeasured_one_is_unknown():
    gemini = route_cast_catalog([VoiceOption("Charon", "Charon"), VoiceOption("Aoede", "Aoede")])
    assert [(voice.id, voice.register) for voice in gemini] == [("Charon", "low"), ("Aoede", "high")]
    local = route_cast_catalog([VoiceOption("vi-female-1", "Nữ 1"), VoiceOption("vi-male-1", "Nam 1")])
    assert {voice.register for voice in local} == {"unknown"}

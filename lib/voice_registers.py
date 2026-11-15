"""Measured voice registers of the audio routes' catalogs (ADR-0166), for the voice cast.

``voice_registers.json`` holds, per endpoint, each voice's median pitch and register, written by
``scripts/r2/measure_voice_registers.py``. A voice that was not measured has the register ``unknown``.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from functools import cache
from pathlib import Path

from lib.audio_backends.base import VoiceOption
from lib.voice_cast import CastVoice

REGISTRY_PATH = Path(__file__).with_name("voice_registers.json")
#: Median pitch below which a voice is ``low`` (between typical adult male and female speaking pitch).
SPLIT_HZ = 150.0


@cache
def _registry() -> dict[str, dict[str, dict[str, object]]]:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8")) if REGISTRY_PATH.exists() else {}


def cast_catalog(endpoint: str, voices: Sequence[VoiceOption]) -> list[CastVoice]:
    """The route's voices with their measured registers."""
    measured = _registry().get(endpoint, {})
    out: list[CastVoice] = []
    for voice in voices:
        register = str((measured.get(voice.id) or {}).get("register") or "unknown")
        out.append(CastVoice(voice.id, voice.label, register if register in ("low", "high") else "unknown"))
    return out


def route_cast_catalog(voices: Sequence[VoiceOption]) -> list[CastVoice]:
    """The route's voices with the registers of the measured endpoint that holds most of them (voice ids name an
    endpoint's catalog); every register is ``unknown`` when no endpoint holds at least half of them."""
    ids = {voice.id for voice in voices}
    best, held = "", 0
    for endpoint, measured in _registry().items():
        count = len(ids & measured.keys())
        if count > held:
            best, held = endpoint, count
    return cast_catalog(best if ids and held * 2 >= len(ids) else "", voices)


__all__ = ["REGISTRY_PATH", "SPLIT_HZ", "cast_catalog", "route_cast_catalog"]

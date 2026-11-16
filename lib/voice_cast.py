"""Voices for the speaking characters of a drama (ADR-0166), after huohuo's ``drama_voice_assign``.

The text route reads each speaking character's description and its number of lines, states the character's sex and
age band, and picks one voice from the audio route's catalog. The choice is checked without the model: every speaking
character gets a catalog voice, the narrator's voice is not reused, no two characters share a voice while the catalog
has enough voices, and a voice whose register was measured (``low`` / ``high`` median pitch) fits the stated sex
(``male`` → ``low``, ``female`` → ``high``). A refused choice goes back with its problems; three refusals fail.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from lib.text_backends.base import TextGenerationRequest, TextGenerationResult

type Generate = Callable[[TextGenerationRequest], Awaitable[TextGenerationResult]]

MAX_ATTEMPTS = 3
_REGISTER_OF_SEX = {"male": "low", "female": "high"}


class VoiceCastError(RuntimeError):
    """No acceptable voice cast was found; the message names why."""


@dataclass(frozen=True)
class CastVoice:
    id: str
    label: str
    #: Measured median pitch class of the voice; ``unknown`` when it was not measured.
    register: Literal["low", "high", "unknown"] = "unknown"


@dataclass(frozen=True)
class Speaker:
    name: str
    description: str
    lines: int


class VoicePick(BaseModel):
    model_config = ConfigDict(extra="forbid")
    character: str
    sex: Literal["male", "female", "unknown"]
    age: Literal["child", "young", "adult", "elder"]
    voice: str
    reason: str = Field(default="", max_length=200)


class VoiceCast(BaseModel):
    model_config = ConfigDict(extra="forbid")
    picks: list[VoicePick]


def cast_problems(
    cast: VoiceCast, speakers: Sequence[Speaker], catalog: Sequence[CastVoice], narrator: str
) -> list[str]:
    by_id = {voice.id: voice for voice in catalog}
    names = {speaker.name for speaker in speakers}
    picked = {pick.character: pick for pick in cast.picks}
    problems: list[str] = []
    missing = sorted(names - picked.keys())
    if missing:
        problems.append(f"no voice for {missing}")
    extra = sorted(picked.keys() - names)
    if extra:
        problems.append(f"{extra} are not speaking characters of this story")
    for pick in cast.picks:
        voice = by_id.get(pick.voice)
        if voice is None:
            problems.append(f"{pick.character}: {pick.voice!r} is not in the catalog")
            continue
        if pick.voice == narrator:
            problems.append(f"{pick.character}: {pick.voice} is the narrator's voice")
        wanted = _REGISTER_OF_SEX.get(pick.sex)
        if wanted and voice.register not in ("unknown", wanted):
            problems.append(f"{pick.character} is {pick.sex} but {pick.voice} is a {voice.register} voice")
    voices = [pick.voice for pick in cast.picks if pick.character in names]
    if len(set(voices)) < len(voices) and len(catalog) - 1 >= len(names):
        shared = sorted({v for v in voices if voices.count(v) > 1})
        problems.append(f"characters share a voice ({shared}); give each character its own voice")
    return problems


def _prompt(speakers: Sequence[Speaker], catalog: Sequence[CastVoice], narrator: str, problems: Sequence[str]) -> str:
    voices = "\n".join(
        f"- {voice.id}: {voice.label}" + ("" if voice.register == "unknown" else f" ({voice.register} voice)")
        for voice in catalog
        if voice.id != narrator
    )
    people = "\n".join(
        f"- {speaker.name} ({speaker.lines} lines): {speaker.description.strip()[:400]}"
        for speaker in sorted(speakers, key=lambda s: -s.lines)
    )
    retry = (
        ("\nThe previous cast was refused:\n- " + "\n- ".join(problems) + "\nFix every point.\n") if problems else ""
    )
    return f"""Cast a voice for every speaking character of a drama, from the voice catalog of its speech model.

Characters (most lines first):
{people}

Voices (the narrator keeps {narrator}; do not use it):
{voices}

For each character state its sex and age band from the description, then pick the voice that fits: male characters
a low voice, female characters a high voice; children and youths a light, young voice, elders a mature one; the
temperament in the description decides between close voices (lively: bright and quick; calm: even and lower;
gentle: soft; commanding: full and clear). The characters with the most lines get the most distinctive voices and
must be easy to tell apart; every character gets its own voice.{retry}
Answer with JSON: {{"picks": [{{"character", "sex", "age", "voice", "reason"}}]}}."""


async def assign_voices(
    speakers: Sequence[Speaker], catalog: Sequence[CastVoice], *, narrator: str, generate: Generate
) -> dict[str, str]:
    """Each speaking character's voice id; raises :class:`VoiceCastError` after three refused casts."""
    if not speakers:
        return {}
    problems: list[str] = []
    for _attempt in range(MAX_ATTEMPTS):
        result = await generate(
            TextGenerationRequest(prompt=_prompt(speakers, catalog, narrator, problems), response_schema=VoiceCast)
        )
        try:
            cast = VoiceCast.model_validate(json.loads(result.text))
        except (ValueError, ValidationError) as error:
            problems = [f"the answer is not valid JSON for the schema: {str(error)[:300]}"]
            continue
        problems = cast_problems(cast, speakers, catalog, narrator)
        if not problems:
            return {pick.character: pick.voice for pick in cast.picks}
    raise VoiceCastError("NO_PASSING_CAST: " + "; ".join(problems)[:300])


def speakers_of(
    script_units: Sequence[Mapping[str, object]], characters: Mapping[str, Mapping[str, object]]
) -> list[Speaker]:
    """The characters that speak in the units' utterances, with their descriptions and line counts."""
    counts: dict[str, int] = {}
    for unit in script_units:
        for utterance in unit.get("utterances") or []:  # type: ignore[union-attr]
            if isinstance(utterance, Mapping) and utterance.get("kind") == "dialogue":
                speaker = str(utterance.get("speaker") or "").strip()
                if speaker:
                    counts[speaker] = counts.get(speaker, 0) + 1
    return [
        Speaker(name, str((characters.get(name) or {}).get("description") or ""), count)
        for name, count in counts.items()
    ]


def speakers_to_cast(
    skeleton_kind: str,
    units: Sequence[Mapping[str, object]],
    characters: Mapping[str, object],
    *,
    route: str,
) -> list[Speaker]:
    """The registered characters who speak in the units, as speech admission reads them, and have no voice for ``route``
    (``<provider_id>/<model_id>``), most lines first; each with its description and number of lines."""
    from lib.speech_composition import SpeechMode, SpeechOwner, admit_script_unit

    counts: dict[str, int] = {}
    for unit in units:
        admission = admit_script_unit(skeleton_kind, unit)
        if admission.mode is not SpeechMode.CHARACTER_SPEECH:
            continue
        for utterance in admission.preparation.utterances:
            if utterance.owner is SpeechOwner.CHARACTER and utterance.speaker and utterance.text.strip():
                counts[utterance.speaker] = counts.get(utterance.speaker, 0) + 1
    speakers: list[Speaker] = []
    for name, lines in sorted(counts.items(), key=lambda item: (-item[1], item[0])):
        entry = characters.get(name)
        if not isinstance(entry, Mapping):
            continue  # not a registered character: the script's validation refuses it, a cast never registers it
        voice = entry.get("tts_voice")
        if isinstance(voice, str) and voice.strip() and entry.get("tts_voice_route") == route:
            continue
        speakers.append(Speaker(name, str(entry.get("description") or ""), lines))
    return speakers


def record_voices(project: dict, voices: Mapping[str, str], *, route: str) -> None:
    """Write each cast voice on its registered character as ``tts_voice`` with the ``route`` it was chosen for; a
    name that is no registered character is skipped, never registered."""
    characters = project.get("characters")
    if not isinstance(characters, dict):
        return
    for name, voice in voices.items():
        entry = characters.get(name)
        if not isinstance(entry, dict):
            continue
        entry["tts_voice"] = voice
        entry["tts_voice_route"] = route


__all__ = [
    "CastVoice",
    "Speaker",
    "VoiceCast",
    "VoiceCastError",
    "VoicePick",
    "assign_voices",
    "cast_problems",
    "record_voices",
    "speakers_of",
    "speakers_to_cast",
]

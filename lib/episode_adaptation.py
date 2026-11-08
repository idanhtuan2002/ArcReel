"""Episode adaptation: one story episode becomes a screen script before script planning (ADR-0114).

The story is a product on its own and is never shortened. For a narration or drama project whose
``episode_adaptation`` setting is ``screen``, each planned episode's source slice (``source/episode_N.txt``) is
adapted by the project's script text model into a screen script:

- narration: a narrator's script for a vertical short — hook first, compressed, concrete, dialogue quoted for the
  narrator to read;
- drama: a scene-headed screenplay where dialogue carries the conflict and narration becomes action and sparing
  voiceover.

The answer is structured (logline, conflict, cast, cliffhanger, scenes with their purpose, the verbatim source
excerpt each adapts, and their lines) and accepted only when the mechanical checks of :func:`check_adaptation` pass;
a failed draft is asked again, at most ``MAX_ATTEMPTS`` times, with the failed checks. The accepted script is written
as ``adaptations/episode_N.txt`` (which script planning then reads instead of the source slice) beside
``adaptations/episode_N.json`` (draft, checks, and the basis digest of everything the adaptation read). A changed
basis makes the adaptation stale.
"""

from __future__ import annotations

import bisect
import hashlib
import itertools
import json
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from lib.cjk_ranges import CJK_RANGES
from lib.episode_ledger import episode_outline_context
from lib.episode_paths import episode_source_path, episode_source_relpath
from lib.episode_target_volume import resolve_episode_target_volume
from lib.speech_rate import estimate_spoken_seconds, project_speech_rate_override, speech_rate_units_per_second

type AdaptationMode = Literal["screen", "verbatim"]

SETTING = "episode_adaptation"
ADAPTATIONS_DIR = "adaptations"
PROMPT_VERSION = "episode-adaptation.v1"
MAX_ATTEMPTS = 3
#: Mechanical bounds (ADR-0114 §4).
EXCERPT_MIN_SKELETON = 8
FIRST_EXCERPT_MAX = 0.35
LAST_EXCERPT_MIN = 0.65
HOOK_MAX_SECONDS = 6.0
TARGET_LOW, TARGET_HIGH = 0.8, 1.2
SOURCE_LOW, SOURCE_HIGH = 0.4, 1.0
DRAMA_SCENES = (2, 8)
DRAMA_MAX_VOICEOVER = 0.3
PREVIOUS_TAIL_CHARS = 600
SPOKEN = frozenset({"narration", "dialogue", "voiceover"})


class AdaptationError(RuntimeError):
    """The episode cannot be adapted (missing input, or no draft passed its checks)."""


# --- settings and paths ----------------------------------------------------------------------------------------------


def adaptation_mode(project: Mapping[str, Any] | None) -> AdaptationMode:
    """``screen`` only when the project asks for it and is a narration or drama project; otherwise ``verbatim``."""
    if not isinstance(project, Mapping) or project.get("content_mode") not in {"narration", "drama"}:
        return "verbatim"
    return "screen" if project.get(SETTING) == "screen" else "verbatim"


def adaptation_text_relpath(episode: int) -> str:
    return f"{ADAPTATIONS_DIR}/episode_{episode}.txt"


def adaptation_record_relpath(episode: int) -> str:
    return f"{ADAPTATIONS_DIR}/episode_{episode}.json"


def script_source_relpath(project: Mapping[str, Any] | None, episode: int) -> str:
    """The text script planning reads for ``episode``: its adaptation under ``screen``, else its source slice."""
    if adaptation_mode(project) == "screen":
        return adaptation_text_relpath(episode)
    return episode_source_relpath(episode)


# --- the answer ------------------------------------------------------------------------------------------------------


class AdaptedLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["narration", "dialogue", "voiceover", "action"]
    speaker: str = Field(default="", max_length=40)
    manner: str = Field(default="", max_length=60)
    text: str = Field(min_length=1, max_length=800)


class AdaptedScene(BaseModel):
    model_config = ConfigDict(extra="forbid")

    heading: str = Field(default="", max_length=120)
    purpose: str = Field(min_length=1, max_length=300)
    source_excerpt: str = Field(min_length=1, max_length=400)
    lines: list[AdaptedLine] = Field(min_length=1, max_length=40)


class EpisodeAdaptationDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    logline: str = Field(min_length=1, max_length=400)
    conflict: str = Field(min_length=1, max_length=400)
    cast: list[str] = Field(min_length=1, max_length=10)
    cliffhanger: str = Field(min_length=1, max_length=400)
    scenes: list[AdaptedScene] = Field(min_length=1, max_length=12)


# --- inputs and basis ------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class AdaptationInputs:
    episode: int
    mode: Literal["narration", "drama"]
    language: str | None
    source: str
    outline: dict[str, Any] | None
    next_outline: dict[str, Any] | None
    previous_tail: str
    characters: tuple[str, ...]
    target_seconds: float | None
    speech_rate_override: float | None

    def basis(self) -> str:
        body = {
            "version": PROMPT_VERSION,
            "episode": self.episode,
            "mode": self.mode,
            "language": self.language,
            "source": self.source,
            "outline": self.outline,
            "next_outline": self.next_outline,
            "previous_tail": self.previous_tail,
            "characters": list(self.characters),
            "target_seconds": self.target_seconds,
            "speech_rate_override": self.speech_rate_override,
        }
        raw = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return "sha256:" + hashlib.sha256(raw).hexdigest()

    def seconds(self, text: str) -> float:
        return estimate_spoken_seconds(text, self.language, self.speech_rate_override)


def read_inputs(project_path: Path, project: Mapping[str, Any], episode: int) -> AdaptationInputs:
    """Everything an adaptation of ``episode`` reads; raises :class:`AdaptationError` without a source slice."""
    mode = project.get("content_mode")
    if mode not in {"narration", "drama"}:
        raise AdaptationError("only narration and drama projects are adapted")
    path = episode_source_path(project_path, episode)
    if not path.is_file():
        raise AdaptationError(f"episode {episode} has no planned source; plan episodes first")
    source = path.read_text(encoding="utf-8").strip()
    if not source:
        raise AdaptationError(f"episode {episode} source is empty")
    previous = episode_source_path(project_path, episode - 1) if episode > 1 else None
    previous_tail = (
        previous.read_text(encoding="utf-8").strip()[-PREVIOUS_TAIL_CHARS:] if previous and previous.is_file() else ""
    )
    outline, next_outline = episode_outline_context(project, episode)
    language = project.get("source_language") if isinstance(project.get("source_language"), str) else None
    volume = resolve_episode_target_volume(project, language=language)
    override = project_speech_rate_override(project)
    target: float | None = None
    if volume is not None:
        # An explicit unit target is spoken at the project's speech rate; a duration target is the duration itself.
        target = (
            float(volume.seconds)
            if volume.seconds is not None
            else volume.units / speech_rate_units_per_second(language, override)
        )
    characters = project.get("characters")
    return AdaptationInputs(
        episode=episode,
        mode=mode,
        language=language,
        source=source,
        outline=outline,
        next_outline=next_outline,
        previous_tail=previous_tail,
        characters=tuple(sorted(str(name) for name in characters)) if isinstance(characters, Mapping) else (),
        target_seconds=target,
        speech_rate_override=override,
    )


# --- checks ----------------------------------------------------------------------------------------------------------


def _skeleton(text: str) -> tuple[str, list[int]]:
    """Lower-case letters and digits of ``text`` (accents kept) with each one's offset in ``text``."""
    chars, offsets = [], []
    for index, char in enumerate(unicodedata.normalize("NFC", text)):
        if char.isalnum():
            chars.append(char.lower())
            offsets.append(index)
    return "".join(chars), offsets


_CJK_STARTS = [start for start, _ in CJK_RANGES]


def _cjk(text: str) -> bool:
    for char in text:
        code = ord(char)
        position = bisect.bisect_right(_CJK_STARTS, code) - 1
        if position >= 0 and code <= CJK_RANGES[position][1]:
            return True
    return False


def spoken_text(draft: EpisodeAdaptationDraft) -> list[str]:
    return [line.text for scene in draft.scenes for line in scene.lines if line.kind in SPOKEN]


def screen_seconds(draft: EpisodeAdaptationDraft, inputs: AdaptationInputs) -> float:
    """The episode's length: its spoken lines, and for drama also its action lines (estimated at the speech rate,
    since an action takes about as long to show as to read)."""
    kinds = SPOKEN | ({"action"} if inputs.mode == "drama" else set())
    return sum(inputs.seconds(line.text) for scene in draft.scenes for line in scene.lines if line.kind in kinds)


def check_adaptation(draft: EpisodeAdaptationDraft, inputs: AdaptationInputs) -> list[str]:
    """The checks a draft fails, as sentences the model can act on; empty when it is accepted."""
    problems: list[str] = []
    source_skeleton, _ = _skeleton(inputs.source)
    total = max(1, len(source_skeleton))
    positions: list[tuple[int, int]] = []
    for number, scene in enumerate(draft.scenes, start=1):
        excerpt, _ = _skeleton(scene.source_excerpt)
        if len(excerpt) < EXCERPT_MIN_SKELETON:
            problems.append(f"scene {number}: source_excerpt is too short; copy a full sentence from the source")
            continue
        start = source_skeleton.find(excerpt)
        if start < 0:
            problems.append(
                f"scene {number}: source_excerpt is not in the episode source; copy it word for word: "
                f"{scene.source_excerpt[:80]!r}"
            )
            continue
        positions.append((start, start + len(excerpt)))
    if positions:
        if any(later[0] < earlier[0] for earlier, later in itertools.pairwise(positions)):
            problems.append("scenes must follow the source order (each source_excerpt after the previous one)")
        if positions[0][0] / total > FIRST_EXCERPT_MAX:
            problems.append("the first scene must adapt the beginning of the episode source")
        if max(end for _, end in positions) / total < LAST_EXCERPT_MIN:
            problems.append("the last scene must adapt the end of the episode source; keep its ending")
    cast = {name.strip() for name in draft.cast if name.strip()}
    problems.extend(
        f"cast member {name!r} is neither a registered character nor named in the source"
        for name in sorted(cast)
        if name not in inputs.characters and _skeleton(name)[0] not in source_skeleton
    )
    for number, scene in enumerate(draft.scenes, start=1):
        for line in scene.lines:
            if line.kind in {"dialogue", "voiceover"}:
                if not line.speaker.strip():
                    problems.append(f"scene {number}: every {line.kind} line needs its speaker")
                elif line.speaker.strip() not in cast:
                    problems.append(f"scene {number}: speaker {line.speaker!r} is not in the cast")
    spoken = spoken_text(draft)
    if not spoken:
        problems.append("the adaptation has no spoken line")
    else:
        if inputs.seconds(spoken[0]) > HOOK_MAX_SECONDS:
            problems.append(f"the first spoken line is the hook; keep it under {HOOK_MAX_SECONDS:.0f} seconds")
        seconds = screen_seconds(draft, inputs)
        if inputs.target_seconds:
            low, high = TARGET_LOW * inputs.target_seconds, TARGET_HIGH * inputs.target_seconds
            reference = f"the episode's target of {inputs.target_seconds:.0f} seconds"
        else:
            source_seconds = inputs.seconds(inputs.source)
            low, high = SOURCE_LOW * source_seconds, SOURCE_HIGH * source_seconds
            reference = f"the source's {source_seconds:.0f} spoken seconds"
        if not low <= seconds <= high:
            problems.append(
                f"{'screen' if inputs.mode == 'drama' else 'spoken'} length is {seconds:.0f} seconds; it must be "
                f"between {low:.0f} and {high:.0f} ({reference})"
            )
        if inputs.mode == "drama":
            voiceover = sum(
                inputs.seconds(line.text) for scene in draft.scenes for line in scene.lines if line.kind == "voiceover"
            )
            spoken_seconds = sum(inputs.seconds(text) for text in spoken)
            if spoken_seconds and voiceover / spoken_seconds > DRAMA_MAX_VOICEOVER:
                problems.append("voiceover is over 30% of the spoken length; move the story into dialogue and action")
    kinds = {line.kind for scene in draft.scenes for line in scene.lines}
    if inputs.mode == "drama":
        low_scenes, high_scenes = DRAMA_SCENES
        if not low_scenes <= len(draft.scenes) <= high_scenes:
            problems.append(f"a drama episode has {low_scenes}-{high_scenes} scenes")
        if "narration" in kinds:
            problems.append("drama has no narrator: turn narration into action, dialogue or voiceover")
        if any(not scene.heading.strip() for scene in draft.scenes):
            problems.append("every drama scene needs its heading (setting · place | time)")
        if "dialogue" not in kinds:
            problems.append("a drama episode carries its conflict in dialogue")
    elif kinds & {"action", "voiceover"}:
        problems.append("a narration script has only narration lines and quoted dialogue")
    rendered = render_script(draft, inputs.mode)
    if _cjk(rendered) and not _cjk(inputs.source):
        problems.append("write in the source's language only; the answer contains CJK characters")
    return problems


# --- rendering -------------------------------------------------------------------------------------------------------


def render_script(draft: EpisodeAdaptationDraft, mode: str) -> str:
    """The adapted episode as the text script planning reads."""
    blocks: list[str] = []
    for number, scene in enumerate(draft.scenes, start=1):
        lines: list[str] = []
        if mode == "drama":
            lines.append(f"## S{number:02d} | {scene.heading.strip()}")
        for line in scene.lines:
            text = line.text.strip()
            manner = f"({line.manner.strip()}) " if line.manner.strip() else ""
            if mode == "drama":
                if line.kind == "dialogue":
                    lines.append(f"{line.speaker.strip()}: {manner}{text}")
                elif line.kind == "voiceover":
                    lines.append(f"{line.speaker.strip()} (V.O.): {manner}{text}")
                else:
                    lines.append(text)
            elif line.kind == "dialogue":
                lines.append(f"{line.speaker.strip()}: “{text}”")
            else:
                lines.append(text)
        blocks.append("\n\n".join(lines))
    return "\n\n".join(blocks).strip() + "\n"


# --- prompt ----------------------------------------------------------------------------------------------------------

_FORMS = {
    "narration": """FORM — narrator's screen script for a vertical short video read by one narrator:
- Open with the hook: the first spoken line is a single short sentence (under {hook:.0f} seconds) that throws the
  viewer into the episode's tension; do not open with setting or backstory.
- Compress: keep every event that moves the plot, cut repetition, description and inner monologue that the picture
  or one line can carry. Short, concrete, spoken sentences in the present moment.
- Use kind "narration" for the narrator; use kind "dialogue" (with speaker) only for a character's short, decisive
  line, which the narrator will quote. No "action" or "voiceover" lines.
- End on the cliffhanger: the last line leaves the question the next episode answers.""",
    "drama": """FORM — screenplay for a vertical short drama:
- {scenes_low}-{scenes_high} scenes. Each scene has a heading "setting · place | time" in the source's language (e.g.
  "Nội · Nhà kho cũ | Đêm"), at least one emotional turn or reveal, close interaction between few characters.
- Dialogue carries the conflict (kind "dialogue", with speaker and a short manner such as "lạnh lùng"); turn the
  narrator's description into "action" lines that a camera can film; inner thoughts become a look, a gesture, an
  object, or a short "voiceover" (at most 30% of the spoken length). No "narration" lines.
- No camera terms (shot sizes, angles, movements); the storyboard decides them.
- The first spoken line is the hook (under {hook:.0f} seconds); the last scene ends on the cliffhanger.""",
}

PROMPT = """You adapt one episode of a published story into a screen script. The story stays as it is; the film is
an adaptation of this episode only.

FIDELITY — never change what happens, who does it, or how the episode ends; add no event, character or fact the
source does not contain. You may cut, reorder within a scene, compress and dramatize.

{form}

LENGTH — the spoken lines (narration, dialogue, voiceover) together take {length}.

STRUCTURE — answer with JSON:
- logline: one sentence (who wants what, against what).
- conflict: the episode's central conflict.
- cast: the names of the characters who speak or act, written exactly as the source or the registered list writes
  them.
- cliffhanger: the open question the episode ends on.
- scenes: in source order. Each scene: heading, purpose (the turn or reveal it carries), source_excerpt (one full
  sentence copied word for word from the episode source that this scene adapts — the first scene adapts the
  beginning, the last scene the ending), and lines (kind, speaker, manner, text).
Write every text in the source's language.

REGISTERED CHARACTERS: {characters}
{continuity}
EPISODE {episode} SOURCE:
<<<
{source}
>>>
"""


def build_prompt(inputs: AdaptationInputs, previous_problems: list[str] | None = None) -> str:
    if inputs.target_seconds:
        length = (
            f"about {inputs.target_seconds:.0f} seconds when read aloud "
            f"(between {TARGET_LOW * inputs.target_seconds:.0f} and {TARGET_HIGH * inputs.target_seconds:.0f})"
        )
    else:
        length = "less time than reading the source aloud, without losing a plot event"
    form = _FORMS[inputs.mode].format(hook=HOOK_MAX_SECONDS, scenes_low=DRAMA_SCENES[0], scenes_high=DRAMA_SCENES[1])
    continuity = []
    if inputs.outline:
        continuity.append(f"THIS EPISODE IN THE PLAN: {json.dumps(inputs.outline, ensure_ascii=False)}")
    if inputs.previous_tail:
        continuity.append(f"THE PREVIOUS EPISODE ENDED WITH:\n<<<\n{inputs.previous_tail}\n>>>")
    if inputs.next_outline:
        continuity.append(
            "THE NEXT EPISODE OPENS WITH (lead the cliffhanger into it, do not tell it): "
            f"{json.dumps(inputs.next_outline, ensure_ascii=False)}"
        )
    prompt = PROMPT.format(
        form=form,
        length=length,
        characters=", ".join(inputs.characters) or "(none registered)",
        continuity="\n".join(continuity) + ("\n" if continuity else ""),
        episode=inputs.episode,
        source=inputs.source,
    )
    if previous_problems:
        prompt += "\nYOUR PREVIOUS ANSWER FAILED THESE CHECKS; FIX ALL OF THEM:\n" + "\n".join(
            f"- {problem}" for problem in previous_problems
        )
    return prompt


# --- status and execution --------------------------------------------------------------------------------------------


def adaptation_state(
    project_path: Path, project: Mapping[str, Any], episode: int
) -> Literal["current", "stale", "missing"]:
    """Whether ``episode`` has an accepted adaptation of exactly what it would read now."""
    record_path = project_path / adaptation_record_relpath(episode)
    text_path = project_path / adaptation_text_relpath(episode)
    if not record_path.is_file() or not text_path.is_file():
        return "missing"
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
        inputs = read_inputs(project_path, project, episode)
    except (OSError, ValueError, AdaptationError):
        return "stale"
    text_digest = "sha256:" + hashlib.sha256(text_path.read_bytes()).hexdigest()
    if record.get("basis") != inputs.basis() or record.get("text_digest") != text_digest:
        return "stale"
    return "current"


__all__ = [
    "SETTING",
    "AdaptationError",
    "AdaptationInputs",
    "EpisodeAdaptationDraft",
    "adaptation_mode",
    "adaptation_record_relpath",
    "adaptation_state",
    "adaptation_text_relpath",
    "build_prompt",
    "check_adaptation",
    "read_inputs",
    "render_script",
    "script_source_relpath",
]

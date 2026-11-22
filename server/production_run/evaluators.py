"""Blind model review of one final film by one frozen reviewer route.

The reviewer sees sampled frames of the final, its subtitle sidecar and the episode's narration text, and nothing
about the writer, the other reviewer or the run. Per frame it is asked one-picture questions — is the picture broken
(black, noise, test pattern); is it upside down, asked both alone and as "which of this picture and its 180-degree
rotation is upright", either answer counting; does it illustrate the narration line shown at its moment — and
then, with every frame and its line, for the language, an anchored 1–5 score per creative dimension and its
findings. Fixed rules turn the answers into CRITICAL findings (``frame_answer_findings``): two or more broken or
upside-down frames, or two or more frames that do not illustrate their line. The ``probabilities`` method instead
reads each answer's yes/no probability from the first token's log-probabilities and applies calibrated thresholds
(``illustration_findings``: frames that on average do not illustrate their line). Subtitles and the picture's fill are
judged by the fixed technical checks of ``final_checks``, which are part of every review. A transport error, timeout
or a response outside the schema is a FAILED assessment, never a pass.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import subprocess
import tempfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.custom_provider import parse_provider_id
from lib.db.repositories.custom_provider_repo import CustomProviderRepository
from r2.automation.assessment import CREATIVE_DIMENSIONS, AssessmentFinding, ModelAssessment
from r2.automation.identity import digest_value
from r2.automation.profiles import route_digest
from r2.contracts.automation import ModelRoute, RunStage
from r2.contracts.common import ensure_json_value
from server.production_run.final_checks import (
    cast_findings,
    length_findings,
    picture_findings,
    sound_findings,
    speech_findings,
    subtitle_findings,
    timing_findings,
    variety_findings,
)
from server.production_run.vision_chat import AccessFor, ollama_access, vision_chat

logger = logging.getLogger(__name__)

FRAME_COUNT = 8
CONTEXT_TOKENS = 16384
#: The most tokens a local reviewer's verdict may take; a model looping over its findings ends here instead of at the
#: request timeout.
VERDICT_TOKENS = 2048

FRAME_WIDTH = 432
UPRIGHT_QUESTION = "Is this photo upside down (rotated 180 degrees, sky at the bottom)? Answer with exactly one English word: yes or no."
MATCH_QUESTION = (
    "Narration line: «{cue}». Does this picture illustrate that narration line (same characters, setting or event)? "
    "Answer with exactly one English word: yes or no."
)
DRAMA_MATCH_QUESTION = (
    "Spoken line: «{cue}». Does this picture show the scene where that line is spoken (same characters, setting or "
    "event)? Answer with exactly one English word: yes or no."
)
BROKEN_QUESTION = (
    "Is this picture broken: mostly black or blank, random noise or corruption, or a color-bar test pattern? "
    "Answer with exactly one English word: yes or no."
)
ORIENTATION_QUESTION = (
    "The two pictures, A (left) and B (right), are the same photo; one of them is rotated 180 degrees. "
    "Which one is upright, A or B? Answer with exactly one letter: A or B."
)
MIN_FLIPPED_FRAMES = 2
#: The questions method asks "upside down?" of each frame alone; a reflection or an aerial shot draws a few false
#: yes answers, while a really flipped final draws one on nearly every frame, so it needs more than half of them.
MIN_FLIPPED_FRAMES_QUESTIONS = 5
MIN_BROKEN_FRAMES = 2
MIN_MISMATCHED_FRAMES = 2

PROMPT = """Bạn là người duyệt chất lượng phim ngắn tiếng Việt dạng kể chuyện (9:16, 30–60 giây).
Bạn nhận {frame_count} khung hình lấy đều theo thứ tự thời gian, phụ đề và lời kể. Bạn không nghe được âm thanh.
Mỗi khung đi kèm câu phụ đề đang hiện (hoặc gần nhất) lúc đó:
{frame_cues}

Bước 1 — chấm điểm 1–5 cho story, visual, audio, continuity, pacing theo mốc:
5 xuất sắc; 4 đạt chất lượng phát hành, chỉ có điểm chưa hoàn hảo nhỏ; 3 có lỗi rõ làm người xem khó chịu;
2 lỗi nặng; 1 hỏng. "audio" chấm lời kể qua văn bản: tiếng Việt tự nhiên, đúng chính tả, khớp phụ đề và hình.
Không trừ điểm vì phong cách ảnh AI, ánh sáng, chi tiết nhân vật hơi khác giữa các cảnh, hay câu chuyện đơn giản.
Phim hình ảnh bình thường, khớp lời kể và kể mạch lạc thì chấm 4 hoặc 5.

Bước 2 — "findings": chỉ ghi lỗi thật, mỗi lỗi có code, severity (CRITICAL/MAJOR/MINOR), repair_stage
(SCRIPT_PLAN, SCRIPT, MEDIA, RENDER hoặc null) và detail ngắn. "language" là mã ngôn ngữ của lời kể (ví dụ "vi").

PHỤ ĐỀ:
{subtitles}

LỜI KỂ:
{narration}
"""

WATCH_PROMPT = """Bạn là người duyệt chất lượng phim ngắn tiếng Việt dạng kể chuyện (9:16, 30–60 giây).
Bạn được xem toàn bộ video kèm âm thanh lời kể, cùng phụ đề và văn bản lời kể bên dưới.

Bước 1 — chấm điểm 1–5 cho story, visual, audio, continuity, pacing theo mốc:
5 xuất sắc; 4 đạt chất lượng phát hành, chỉ có điểm chưa hoàn hảo nhỏ; 3 có lỗi rõ làm người xem khó chịu;
2 lỗi nặng; 1 hỏng. "audio" chấm giọng đọc nghe được: tiếng Việt tự nhiên, rõ, khớp phụ đề và hình.
Không trừ điểm vì phong cách ảnh AI, ánh sáng, chi tiết nhân vật hơi khác giữa các cảnh, hình tĩnh ít chuyển động,
hay câu chuyện đơn giản. Phim hình ảnh bình thường, khớp lời kể và kể mạch lạc thì chấm 4 hoặc 5.

Bước 2 — "findings": chỉ ghi lỗi thật nhìn hoặc nghe thấy được (hình đen, nhiễu, lộn ngược, sai câu chuyện, sai
ngôn ngữ, phụ đề hỏng, tiếng lệch hình...), mỗi lỗi có code, severity (CRITICAL/MAJOR/MINOR), repair_stage
(SCRIPT_PLAN, SCRIPT, MEDIA, RENDER hoặc null) và detail ngắn. "language" là mã ngôn ngữ của lời kể (ví dụ "vi").

PHỤ ĐỀ:
{subtitles}

LỜI KỂ:
{narration}
"""

EN_PROMPT = """You review the quality of a short English narrated story film (9:16, 30–60 seconds).
You receive {frame_count} frames sampled evenly in time order, the subtitles and the narration. You cannot hear the sound.
Each frame comes with the subtitle line shown at that moment (or the nearest one):
{frame_cues}

Step 1 — score story, visual, audio, continuity, pacing from 1 to 5:
5 excellent; 4 release quality, only small imperfections; 3 clear faults that bother the viewer;
2 severe faults; 1 broken. "audio" scores the narration through its text: natural, correctly spelled English that
matches the subtitles and the pictures.
Do not take points off for an AI image style, lighting, small differences in a character's details between scenes,
or a simple story. A film with normal pictures that match the narration and tell it coherently scores 4 or 5.

Step 2 — "findings": only real faults, each with a code, severity (CRITICAL/MAJOR/MINOR), repair_stage
(SCRIPT_PLAN, SCRIPT, MEDIA, RENDER or null) and a short detail. "language" is the language code of the narration
(for example "en").

SUBTITLES:
{subtitles}

NARRATION:
{narration}
"""

EN_WATCH_PROMPT = """You review the quality of a short English narrated story film (9:16, 30–60 seconds).
You watch the whole video with its narration audio, with the subtitles and the narration text below.

Step 1 — score story, visual, audio, continuity, pacing from 1 to 5:
5 excellent; 4 release quality, only small imperfections; 3 clear faults that bother the viewer;
2 severe faults; 1 broken. "audio" scores the voice you hear: natural, clear English that matches the subtitles
and the pictures.
Do not take points off for an AI image style, lighting, small differences in a character's details between scenes,
still pictures with little motion, or a simple story. A film with normal pictures that match the narration and tell
it coherently scores 4 or 5.

Step 2 — "findings": only real faults you can see or hear (black picture, noise, upside down, wrong story, wrong
language, broken subtitles, sound out of sync...), each with a code, severity (CRITICAL/MAJOR/MINOR), repair_stage
(SCRIPT_PLAN, SCRIPT, MEDIA, RENDER or null) and a short detail. "language" is the language code of the narration
(for example "en").

SUBTITLES:
{subtitles}

NARRATION:
{narration}
"""

DRAMA_PROMPT = """Bạn là người duyệt chất lượng phim ngắn tiếng Việt dạng kịch, có lời thoại nhân vật (9:16, 30–60 giây).
Bạn nhận {frame_count} khung hình lấy đều theo thứ tự thời gian, phụ đề và lời thoại. Bạn không nghe được âm thanh.
Mỗi khung đi kèm câu phụ đề đang hiện (hoặc gần nhất) lúc đó:
{frame_cues}

Bước 1 — chấm điểm 1–5 cho story, visual, audio, continuity, pacing theo mốc:
5 xuất sắc; 4 đạt chất lượng phát hành, chỉ có điểm chưa hoàn hảo nhỏ; 3 có lỗi rõ làm người xem khó chịu;
2 lỗi nặng; 1 hỏng. "audio" chấm lời thoại qua văn bản: tiếng Việt tự nhiên, đúng chính tả, mỗi câu đúng nhân vật
đang nói, khớp phụ đề và hình; giọng các nhân vật được chấm khi nghe được.
Không trừ điểm vì phong cách ảnh AI, ánh sáng, chi tiết nhân vật hơi khác giữa các cảnh, hình tĩnh không mấp máy môi,
hay câu chuyện đơn giản. Phim hình ảnh bình thường, lời thoại đúng người, đúng cảnh và mạch lạc thì chấm 4 hoặc 5.
Mục nào chấm 3 trở xuống thì phải có ít nhất một finding mức MAJOR hoặc CRITICAL nêu đúng lỗi đó; lỗi chỉ ở mức MINOR, hoặc không chỉ ra được lỗi cụ thể, thì mục đó chấm 4 hoặc 5.

Bước 2 — "findings": chỉ ghi lỗi thật, mỗi lỗi có code, severity (CRITICAL/MAJOR/MINOR), repair_stage
(SCRIPT_PLAN, SCRIPT, MEDIA, RENDER hoặc null) và detail ngắn. "language" là mã ngôn ngữ của lời thoại (ví dụ "vi").

PHỤ ĐỀ:
{subtitles}

LỜI THOẠI:
{narration}
"""

DRAMA_WATCH_PROMPT = """Bạn là người duyệt chất lượng phim ngắn tiếng Việt dạng kịch, có lời thoại nhân vật (9:16, 30–60 giây).
Bạn được xem toàn bộ video kèm âm thanh, cùng phụ đề và văn bản lời thoại bên dưới.

Bước 1 — chấm điểm 1–5 cho story, visual, audio, continuity, pacing theo mốc:
5 xuất sắc; 4 đạt chất lượng phát hành, chỉ có điểm chưa hoàn hảo nhỏ; 3 có lỗi rõ làm người xem khó chịu;
2 lỗi nặng; 1 hỏng. "audio" chấm lời thoại nghe được: tiếng Việt tự nhiên, rõ; mỗi nhân vật một giọng riêng, hợp giới
tính, tuổi và tính cách, dễ phân biệt các nhân vật chính; câu thoại khớp phụ đề và cảnh.
Không trừ điểm vì phong cách ảnh AI, ánh sáng, chi tiết nhân vật hơi khác giữa các cảnh, hình tĩnh không mấp máy môi,
hay câu chuyện đơn giản. Phim hình ảnh bình thường, giọng đúng nhân vật và mạch lạc thì chấm 4 hoặc 5.
Mục nào chấm 3 trở xuống thì phải có ít nhất một finding mức MAJOR hoặc CRITICAL nêu đúng lỗi đó; lỗi chỉ ở mức MINOR, hoặc không chỉ ra được lỗi cụ thể, thì mục đó chấm 4 hoặc 5.

Bước 2 — "findings": chỉ ghi lỗi thật nhìn hoặc nghe thấy được (hình đen, nhiễu, lộn ngược, sai câu chuyện, sai
ngôn ngữ, phụ đề hỏng, hai nhân vật cùng giọng, giọng sai giới tính, tiếng lệch hình...), mỗi lỗi có code, severity
(CRITICAL/MAJOR/MINOR), repair_stage (SCRIPT_PLAN, SCRIPT, MEDIA, RENDER hoặc null) và detail ngắn. "language" là mã
ngôn ngữ của lời thoại (ví dụ "vi").

PHỤ ĐỀ:
{subtitles}

LỜI THOẠI:
{narration}
"""

#: The frame label in the review prompt's per-frame cue lines, by narration language.
_FRAME_WORD = {"vi": "Khung", "en": "Frame"}


def review_prompts(language: str, form: str = "narration") -> tuple[str, str]:
    """The (frames, watch) review prompts for films of ``form`` (``narration`` or ``drama``, ADR-0166) in
    ``language``; other pairs have no reviewer."""
    if form == "drama":
        if language == "vi":
            return DRAMA_PROMPT, DRAMA_WATCH_PROMPT
        raise ValueError(f"no drama review prompt for language {language!r}")
    if language == "vi":
        return PROMPT, WATCH_PROMPT
    if language == "en":
        return EN_PROMPT, EN_WATCH_PROMPT
    raise ValueError(f"no review prompt for language {language!r}")


def match_question(form: str = "narration") -> str:
    """The per-frame question whether a picture shows its line: a narration line, or a drama's spoken line."""
    return DRAMA_MATCH_QUESTION if form == "drama" else MATCH_QUESTION


SCHEMA = {
    "type": "object",
    "required": ["language", "scores", "findings"],
    "properties": {
        "language": {"type": "string"},
        "scores": {
            "type": "object",
            "required": list(CREATIVE_DIMENSIONS),
            "properties": {d: {"type": "integer", "minimum": 1, "maximum": 5} for d in CREATIVE_DIMENSIONS},
        },
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["code", "severity", "repair_stage", "detail"],
                "properties": {
                    "code": {"type": "string"},
                    "severity": {"enum": ["CRITICAL", "MAJOR", "MINOR"]},
                    "repair_stage": {"enum": ["SCRIPT_PLAN", "SCRIPT", "MEDIA", "RENDER", None]},
                    "detail": {"type": "string"},
                },
            },
        },
    },
}

#: The verdict schema a local reviewer's decoding grammar enforces: SCHEMA with at most ``VERDICT_FINDINGS`` findings of
#: at most ``FINDING_CHARS`` characters each, so a model looping over findings closes its answer within
#: ``VERDICT_TOKENS``. Like ``VERDICT_TOKENS`` it bounds the transport, not what the reviewer is asked.
VERDICT_FINDINGS = 8
FINDING_CHARS = 300
BOUNDED_SCHEMA = {
    **SCHEMA,
    "properties": {
        **SCHEMA["properties"],
        "findings": {
            **SCHEMA["properties"]["findings"],
            "maxItems": VERDICT_FINDINGS,
            "items": {
                **SCHEMA["properties"]["findings"]["items"],
                "properties": {
                    **SCHEMA["properties"]["findings"]["items"]["properties"],
                    "detail": {"type": "string", "maxLength": FINDING_CHARS},
                },
            },
        },
    },
}


QUESTIONS = "questions"
PROBABILITIES = "probabilities"
#: The reviewer watches the whole final, picture and narration audio together (Gemini models).
WATCH = "watch"
PROBABILITY_CUT = 0.5
MAX_MEAN_ILLUSTRATES = 0.15
# Review method of each qualified reviewer model, chosen on the calibration split; unlisted models ask questions.
REVIEW_METHODS: dict[str, str] = {"qwen2.5vl:7b": PROBABILITIES, "gemma3:4b": QUESTIONS}


def review_method(route: ModelRoute, protocol: str | None = None) -> str:
    """The review method of a route: a model's calibrated method, else watching the final for a Gemini model
    served by the Gemini API (``protocol`` from its provider endpoint; ``None`` when unknown), else questions."""
    if route.model_id in REVIEW_METHODS:
        return REVIEW_METHODS[route.model_id]
    if route.model_id.startswith("gemini-") and protocol in {None, "gemini"}:
        return WATCH
    return QUESTIONS


def _offending_keys(
    answers: list, offending: Callable[[Any], bool], frame_keys: list[str] | None, unit_key: str
) -> list[str]:
    """The distinct unit keys of the frames whose answer is offending, in frame order; the episode key when frames
    cannot be placed in a segment or none is offending."""
    if not frame_keys:
        return [unit_key]
    keys = [key for answer, key in zip(answers, frame_keys, strict=False) if offending(answer)]
    return list(dict.fromkeys(keys)) or [unit_key]


def segment_keys(evidence: FinalEvidence, times: list[float]) -> list[str]:
    """Each sampled frame's unit key: its segment when the render manifest places it, otherwise the episode."""
    keys = []
    for seconds in times:
        segment = next((unit for unit, end in evidence.segments if seconds < end), None)
        keys.append(f"{evidence.unit_key}:segment:{segment}" if segment else evidence.unit_key)
    return keys


def illustration_findings(
    probabilities: list[float | None], *, unit_key: str, frame_keys: list[str] | None = None
) -> list[AssessmentFinding]:
    """The ``probabilities`` method's rule: frames that on average do not illustrate their line are CRITICAL, one
    finding per segment holding a frame below the cut."""
    known = [p for p in probabilities if p is not None]
    if not known or sum(known) / len(known) >= MAX_MEAN_ILLUSTRATES:
        return []
    keys = _offending_keys(probabilities, lambda p: p is not None and p <= PROBABILITY_CUT, frame_keys, unit_key)
    return [
        AssessmentFinding(
            code="FRAMES_NOT_ILLUSTRATING_NARRATION",
            severity="CRITICAL",
            unit_key=key,
            repair_stage=RunStage.MEDIA,
            detail=f"mean probability {sum(known) / len(known):.2f} that a frame illustrates its line",
        )
        for key in keys
    ]


def first_token_probability(logprobs: list[dict] | None, *, yes: str, no: str) -> float | None:
    """P(``yes``) between the two answers among the first generated token's top alternatives."""
    if not logprobs:
        return None
    mass = {"yes": 0.0, "no": 0.0}
    for entry in logprobs[0].get("top_logprobs") or []:
        token = str(entry.get("token", "")).strip().lower().strip("*\"'")
        if token == yes.lower():
            mass["yes"] += math.exp(float(entry["logprob"]))
        elif token == no.lower():
            mass["no"] += math.exp(float(entry["logprob"]))
    total = mass["yes"] + mass["no"]
    return mass["yes"] / total if total else None


def frame_answer_findings(
    flipped: list[bool | None],
    illustrates: list[bool | None],
    broken: list[bool | None] | None = None,
    *,
    unit_key: str,
    min_flipped: int = MIN_FLIPPED_FRAMES,
    frame_keys: list[str] | None = None,
) -> list[AssessmentFinding]:
    """Findings from the reviewer's one-picture answers: broken, upside-down and non-illustrating frames.

    Each rule counts over the whole episode, as qualified; once it fires, it names every segment holding an
    offending frame (``frame_keys``, one unit key per frame) so a repair can regenerate exactly those segments."""
    broken = broken or []
    rules = [
        ("FRAME_BROKEN", broken, lambda a: a is True, MIN_BROKEN_FRAMES, "{n} frames black, noisy or a test pattern"),
        ("FRAME_UPSIDE_DOWN", flipped, lambda a: a is True, min_flipped, "{n} frames upside down"),
        (
            "FRAME_NOT_ILLUSTRATING_NARRATION",
            illustrates,
            lambda a: a is False,
            MIN_MISMATCHED_FRAMES,
            "{n} frames do not illustrate their narration line",
        ),
    ]
    found: list[AssessmentFinding] = []
    for code, answers, offending, threshold, detail in rules:
        count = sum(1 for answer in answers if offending(answer))
        if count < threshold:
            continue
        found.extend(
            AssessmentFinding(
                code=code,
                severity="CRITICAL",
                unit_key=key,
                repair_stage=RunStage.MEDIA,
                detail=detail.format(n=count),
            )
            for key in _offending_keys(answers, offending, frame_keys, unit_key)
        )
    return found


def yes_no(text: str) -> bool | None:
    word = text.strip().lower().lstrip("*\"' ")
    if word.startswith("yes"):
        return True
    if word.startswith("no"):
        return False
    return None


def upright_letter(text: str) -> bool | None:
    """``True`` when the answer names B, the rotated copy, as upright; ``False`` for A."""
    letter = text.strip().lstrip("*\"' ").upper()[:1]
    return {"A": False, "B": True}.get(letter)


def orientation_pair(frame: bytes, *, ffmpeg: str = "ffmpeg") -> bytes:
    """``frame`` (A, left) beside its 180-degree rotation (B, right)."""
    with tempfile.TemporaryDirectory() as work:
        source, pair = Path(work) / "frame.jpg", Path(work) / "pair.jpg"
        source.write_bytes(frame)
        subprocess.run(
            [
                ffmpeg,
                "-nostdin",
                "-loglevel",
                "error",
                "-i",
                str(source),
                "-filter_complex",
                "[0]split[a][b];[b]hflip,vflip[r];[a][r]hstack",
                "-y",
                str(pair),
            ],
            check=True,
            timeout=60,
        )
        return pair.read_bytes()


def frame_times(duration: float, count: int = FRAME_COUNT) -> list[float]:
    return [(index + 0.5) * duration / count for index in range(count)]


def cue_at(srt: str, seconds: float) -> str:
    """The subtitle shown at ``seconds``; between cues, the nearest one; empty only without any cue."""
    nearest: tuple[float, str] | None = None
    for block in srt.replace("\r\n", "\n").split("\n\n"):
        lines = [line for line in block.strip().splitlines() if line.strip()]
        timing = next((line for line in lines if "-->" in line), None)
        if timing is None:
            continue
        start, end = (_srt_seconds(part.strip()) for part in timing.split("-->"))
        text = " ".join(lines[lines.index(timing) + 1 :])
        distance = 0.0 if start <= seconds < end else min(abs(seconds - start), abs(seconds - end))
        if nearest is None or distance < nearest[0]:
            nearest = (distance, text)
    return nearest[1] if nearest else ""


def _srt_seconds(stamp: str) -> float:
    hours, minutes, rest = stamp.replace(",", ".").split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(rest)


@dataclass(frozen=True)
class FinalEvidence:
    unit_key: str
    final_path: Path
    subtitle_path: Path
    narration_text: str
    subject_digest: str
    #: The final's segments in play order as (unit id, end second), from the render manifest; empty when unknown.
    segments: tuple[tuple[str, float], ...] = ()
    #: The run's episode target in seconds (``RunPolicy.target_duration_seconds``); ``None`` when the project has none.
    target_seconds: float | None = None
    #: The narration language the review prompt is written for (``RunPolicy.language``).
    language: str = "vi"
    #: The film's form the review prompt is written for (``review_form`` of the run's launch profile).
    form: str = "narration"
    #: The shot size of each segment in play order, from the episode script; empty when unknown.
    shot_types: tuple[str, ...] = ()
    #: Segments whose narration names registered characters they do not list, as (segment id, names).
    unlisted_cast: tuple[tuple[str, tuple[str, ...]], ...] = ()
    #: A transcript of the final's sound, when a transcription route made one; ``None`` leaves speech unchecked.
    speech_transcript: str | None = None
    #: A drama's lines with their speakers ("Name: line", one per line) for the review prompt, which judges whether
    #: each line is the right character's; ``narration_text`` keeps the bare lines the subtitles are checked against.
    dialogue: str | None = None


class QualifiedEvaluator(Protocol):
    async def assess(self, *, route: ModelRoute, evidence: FinalEvidence) -> ModelAssessment: ...


def _min_flipped(method: str) -> int:
    return MIN_FLIPPED_FRAMES_QUESTIONS if method == QUESTIONS else MIN_FLIPPED_FRAMES


def prompt_digest(method: str = QUESTIONS, language: str = "vi", form: str = "narration") -> str:
    """The digest of everything a reviewer of ``method`` is asked for a film narrated in ``language`` and the fixed
    rules applied to its answers (a Vietnamese review hashes as it did before other languages existed)."""
    frames_prompt, watch_prompt = review_prompts(language, form)
    scope: dict[str, str] = {} if language == "vi" else {"language": language}
    if form != "narration":
        scope["form"] = form
    if method == WATCH:
        return digest_value(
            "r2.production-review-prompt.v9",
            ensure_json_value({"method": method, "prompt": watch_prompt, "schema": SCHEMA, **scope}),
        )
    questions = (
        [BROKEN_QUESTION, ORIENTATION_QUESTION, match_question(form)]
        if method == PROBABILITIES
        else [BROKEN_QUESTION, UPRIGHT_QUESTION, ORIENTATION_QUESTION, match_question(form)]
    )
    return digest_value(
        "r2.production-review-prompt.v9",
        ensure_json_value(
            {
                "method": method,
                "prompt": frames_prompt,
                "schema": SCHEMA,
                "questions": questions,
                "thresholds": [MIN_BROKEN_FRAMES, _min_flipped(method), MIN_MISMATCHED_FRAMES],
                "probabilities": [PROBABILITY_CUT, MAX_MEAN_ILLUSTRATES] if method == PROBABILITIES else None,
                "frames": [FRAME_COUNT, FRAME_WIDTH],
                **scope,
            }
        ),
    )


def evidence_digest(evidence: FinalEvidence) -> str:
    return digest_value(
        "r2.production-review-evidence.v1",
        {
            "subject": evidence.subject_digest,
            "subtitles": evidence.subtitle_path.read_text(encoding="utf-8"),
            "narration": evidence.narration_text,
        },
    )


def final_duration(final: Path) -> float:
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(final)],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    return max(float(probe.stdout.strip() or 0), 1.0)


def sample_frames(final: Path, *, count: int = FRAME_COUNT, ffmpeg: str = "ffmpeg") -> list[bytes]:
    """JPEG frames of ``final`` at ``frame_times``."""
    with tempfile.TemporaryDirectory() as work:
        frames = []
        for index, seconds in enumerate(frame_times(final_duration(final), count)):
            target = Path(work) / f"frame_{index:02d}.jpg"
            subprocess.run(
                [
                    ffmpeg,
                    "-nostdin",
                    "-loglevel",
                    "error",
                    "-ss",
                    f"{seconds:.3f}",
                    "-i",
                    str(final),
                    "-frames:v",
                    "1",
                    "-vf",
                    f"scale={FRAME_WIDTH}:-2",
                    str(target),
                ],
                check=True,
                timeout=120,
            )
            frames.append(target.read_bytes())
        return frames


class FrameReviewer:
    """A reviewer route that looks at sampled frames, served by any vision chat endpoint (Ollama, OpenAI-compatible,
    Gemini); the questions, answers and their digests do not depend on the endpoint."""

    def __init__(
        self,
        *,
        access_for: AccessFor,
        timeout_seconds: float = 600,
        transport: httpx.AsyncBaseTransport | None = None,
        backoff_seconds: float = 10,
    ) -> None:
        self._access_for = access_for
        self._timeout = timeout_seconds
        self._transport = transport
        self._backoff = backoff_seconds

    async def assess(self, *, route: ModelRoute, evidence: FinalEvidence) -> ModelAssessment:
        base = {
            "reviewer_route_digest": route_digest(route),
            "model_identity": route.model_identity,
            "subject_digest": evidence.subject_digest,
            "evidence_digest": evidence_digest(evidence),
        }
        method = QUESTIONS
        try:
            access = await self._access_for(route.provider_id, route.model_id)
            method = review_method(route, access.protocol)
            if method == WATCH:
                raise ValueError("a watching reviewer cannot review frames")
            subtitles = evidence.subtitle_path.read_text(encoding="utf-8")
            duration = await asyncio.to_thread(final_duration, evidence.final_path)
            frames = await asyncio.to_thread(sample_frames, evidence.final_path)
            pairs = [await asyncio.to_thread(orientation_pair, frame) for frame in frames]
            checks = subtitle_findings(subtitles, evidence.narration_text, unit_key=evidence.unit_key)
            checks += await asyncio.to_thread(picture_findings, evidence.final_path, unit_key=evidence.unit_key)
            checks += timing_findings(subtitles, unit_key=evidence.unit_key)
            checks += await asyncio.to_thread(sound_findings, evidence.final_path, unit_key=evidence.unit_key)
            checks += length_findings(duration, evidence.target_seconds, unit_key=evidence.unit_key)
            checks += variety_findings(evidence.shot_types, unit_key=evidence.unit_key)
            checks += cast_findings(evidence.unlisted_cast, unit_key=evidence.unit_key)
            checks += speech_findings(
                evidence.narration_text,
                evidence.speech_transcript,
                language=evidence.language,
                unit_key=evidence.unit_key,
            )
            cues = "\n".join(
                f"{_FRAME_WORD.get(evidence.language, 'Frame')} {index + 1} ({seconds:.1f}s): "
                f"«{cue_at(subtitles, seconds) or '—'}»"
                for index, seconds in enumerate(frame_times(duration, len(frames)))
            )
            prompt = review_prompts(evidence.language, evidence.form)[0].format(
                frame_count=len(frames),
                frame_cues=cues,
                subtitles=subtitles[:6000],
                narration=(evidence.dialogue or evidence.narration_text)[:6000],
            )
            times = frame_times(duration, len(frames))
            async with vision_chat(
                access,
                route.model_id,
                timeout_seconds=self._timeout,
                transport=self._transport,
                backoff_seconds=self._backoff,
            ) as chat:

                async def ask(question: str, frame: bytes, parse: Callable[[str], bool | None] = yes_no) -> bool | None:
                    reply = await chat.ask(question, [frame], max_tokens=8, context_tokens=CONTEXT_TOKENS)
                    return parse(reply.text)

                async def probability(question: str, frame: bytes, yes: str, no: str) -> float | None:
                    reply = await chat.ask(
                        question, [frame], max_tokens=1, top_logprobs=10, context_tokens=CONTEXT_TOKENS
                    )
                    return first_token_probability(reply.logprobs, yes=yes, no=no)

                def above(value: float | None) -> bool | None:
                    return None if value is None else value > PROBABILITY_CUT

                broken: list[bool | None] = []
                illustrates: list[bool | None] = []
                flipped: list[bool | None] = []
                illustrating: list[float | None] = []
                for frame, pair, seconds in zip(frames, pairs, times, strict=True):
                    if method == PROBABILITIES:
                        flipped.append(above(await probability(ORIENTATION_QUESTION, pair, "B", "A")))
                        broken.append(above(await probability(BROKEN_QUESTION, frame, "yes", "no")))
                        cue = cue_at(subtitles, seconds) or "—"
                        illustrating.append(
                            await probability(match_question(evidence.form).format(cue=cue), frame, "yes", "no")
                        )
                        continue
                    compared = await ask(ORIENTATION_QUESTION, pair, upright_letter)
                    broken.append(await ask(BROKEN_QUESTION, frame))
                    alone = await ask(UPRIGHT_QUESTION, frame)
                    flipped.append(True if True in (alone, compared) else None if None in (alone, compared) else False)
                    illustrates.append(
                        await ask(match_question(evidence.form).format(cue=cue_at(subtitles, seconds) or "—"), frame)
                    )
                final = await chat.ask(
                    prompt,
                    frames,
                    schema=BOUNDED_SCHEMA,
                    max_tokens=VERDICT_TOKENS,
                    context_tokens=CONTEXT_TOKENS,
                    think=None,
                    shift=False,
                )
            answer = json.loads(strip_fence(final.text))
            frame_keys = segment_keys(evidence, times)
            checks += frame_answer_findings(
                flipped,
                illustrates,
                broken,
                unit_key=evidence.unit_key,
                min_flipped=_min_flipped(method),
                frame_keys=frame_keys,
            )
            if method == PROBABILITIES:
                checks += illustration_findings(illustrating, unit_key=evidence.unit_key, frame_keys=frame_keys)
            return ModelAssessment.model_validate(
                {
                    **base,
                    "prompt_digest": prompt_digest(method, evidence.language, evidence.form),
                    "outcome": "COMPLETED",
                    "language": str(answer["language"]).strip().lower()[:8],
                    "scores": answer["scores"],
                    "findings": [
                        *checks,
                        *(
                            AssessmentFinding(
                                code=str(f["code"]).upper()[:64] or "UNSPECIFIED",
                                severity=f["severity"],
                                unit_key=evidence.unit_key,
                                repair_stage=RunStage(f["repair_stage"]) if f.get("repair_stage") else None,
                                detail=str(f.get("detail", ""))[:500],
                            )
                            for f in answer["findings"]
                        ),
                    ],
                }
            )
        except (httpx.HTTPError, KeyError, TypeError, ValueError, subprocess.SubprocessError):
            logger.warning("review of %s by %s failed", evidence.unit_key, route.model_identity, exc_info=True)
            return ModelAssessment.model_validate(
                {**base, "prompt_digest": prompt_digest(method, evidence.language, evidence.form), "outcome": "FAILED"}
            )


class OllamaReviewer(FrameReviewer):
    """A frame reviewer whose every route is served by the Ollama at its provider's base URL."""

    def __init__(
        self,
        *,
        base_url_for: Callable[[str], Awaitable[str]],
        timeout_seconds: float = 600,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        super().__init__(access_for=ollama_access(base_url_for), timeout_seconds=timeout_seconds, transport=transport)


def strip_fence(text: str) -> str:
    """A JSON answer without the Markdown code fence some chat endpoints wrap it in."""
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[1] if "\n" in stripped else ""
        stripped = stripped.rsplit("```", 1)[0]
    return stripped.strip()


def provider_base_url(sessions: async_sessionmaker[AsyncSession]) -> Callable[[str], Awaitable[str]]:
    """The configured base URL of a custom provider, read at the moment a review is sent."""

    async def base_url(provider_id: str) -> str:
        async with sessions() as session:
            provider = await CustomProviderRepository(session).get_provider(parse_provider_id(provider_id))
        if provider is None:
            raise KeyError(provider_id)
        return provider.base_url

    return base_url


__all__ = [
    "FinalEvidence",
    "FrameReviewer",
    "OllamaReviewer",
    "QualifiedEvaluator",
    "evidence_digest",
    "prompt_digest",
    "provider_base_url",
]

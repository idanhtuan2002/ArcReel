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
from server.production_run.final_checks import picture_findings, subtitle_findings
from server.production_run.vision_chat import AccessFor, ollama_access, vision_chat

FRAME_COUNT = 8
CONTEXT_TOKENS = 16384

FRAME_WIDTH = 432
UPRIGHT_QUESTION = "Is this photo upside down (rotated 180 degrees, sky at the bottom)? Answer with exactly one English word: yes or no."
MATCH_QUESTION = (
    "Narration line: «{cue}». Does this picture illustrate that narration line (same characters, setting or event)? "
    "Answer with exactly one English word: yes or no."
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


class QualifiedEvaluator(Protocol):
    async def assess(self, *, route: ModelRoute, evidence: FinalEvidence) -> ModelAssessment: ...


def _min_flipped(method: str) -> int:
    return MIN_FLIPPED_FRAMES_QUESTIONS if method == QUESTIONS else MIN_FLIPPED_FRAMES


def prompt_digest(method: str = QUESTIONS) -> str:
    """The digest of everything a reviewer of ``method`` is asked and the fixed rules applied to its answers."""
    if method == WATCH:
        return digest_value(
            "r2.production-review-prompt.v9",
            ensure_json_value({"method": method, "prompt": WATCH_PROMPT, "schema": SCHEMA}),
        )
    questions = (
        [BROKEN_QUESTION, ORIENTATION_QUESTION, MATCH_QUESTION]
        if method == PROBABILITIES
        else [BROKEN_QUESTION, UPRIGHT_QUESTION, ORIENTATION_QUESTION, MATCH_QUESTION]
    )
    return digest_value(
        "r2.production-review-prompt.v9",
        ensure_json_value(
            {
                "method": method,
                "prompt": PROMPT,
                "schema": SCHEMA,
                "questions": questions,
                "thresholds": [MIN_BROKEN_FRAMES, _min_flipped(method), MIN_MISMATCHED_FRAMES],
                "probabilities": [PROBABILITY_CUT, MAX_MEAN_ILLUSTRATES] if method == PROBABILITIES else None,
                "frames": [FRAME_COUNT, FRAME_WIDTH],
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
            cues = "\n".join(
                f"Khung {index + 1} ({seconds:.1f}s): «{cue_at(subtitles, seconds) or '—'}»"
                for index, seconds in enumerate(frame_times(duration, len(frames)))
            )
            prompt = PROMPT.format(
                frame_count=len(frames),
                frame_cues=cues,
                subtitles=subtitles[:6000],
                narration=evidence.narration_text[:6000],
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
                        illustrating.append(await probability(MATCH_QUESTION.format(cue=cue), frame, "yes", "no"))
                        continue
                    compared = await ask(ORIENTATION_QUESTION, pair, upright_letter)
                    broken.append(await ask(BROKEN_QUESTION, frame))
                    alone = await ask(UPRIGHT_QUESTION, frame)
                    flipped.append(True if True in (alone, compared) else None if None in (alone, compared) else False)
                    illustrates.append(await ask(MATCH_QUESTION.format(cue=cue_at(subtitles, seconds) or "—"), frame))
                final = await chat.ask(
                    prompt, frames, schema=SCHEMA, context_tokens=CONTEXT_TOKENS, think=None, shift=False
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
                    "prompt_digest": prompt_digest(method),
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
            return ModelAssessment.model_validate({**base, "prompt_digest": prompt_digest(method), "outcome": "FAILED"})


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

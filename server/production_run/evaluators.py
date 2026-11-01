"""Blind model review of one final film by one frozen reviewer route.

The reviewer sees sampled frames of the final, its subtitle sidecar and the episode's narration text, and nothing
about the writer, the other reviewer or the run. Per frame it is asked one-picture questions — is the picture broken
(black, noise, test pattern); is it upside down, asked both alone and as "which of this picture and its 180-degree
rotation is upright", either answer counting; does it illustrate the narration line shown at its moment — and
then, with every frame and its line, for the language, an anchored 1–5 score per creative dimension and its
findings. Fixed rules turn the answers into CRITICAL findings (``frame_answer_findings``): two or more broken or
upside-down frames, or two or more frames that do not illustrate their line. Subtitles and the picture's fill are
judged by the fixed technical checks of ``final_checks``, which are part of every review. A transport error, timeout
or a response outside the schema is a FAILED assessment, never a pass.
"""

from __future__ import annotations

import asyncio
import base64
import json
import subprocess
import tempfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.custom_provider import parse_provider_id
from lib.db.repositories.custom_provider_repo import CustomProviderRepository
from lib.generation_resources import device_job, local_job
from lib.text_backends.ollama import normalize_ollama_base_url
from r2.automation.assessment import CREATIVE_DIMENSIONS, AssessmentFinding, ModelAssessment
from r2.automation.identity import digest_value
from r2.automation.profiles import route_digest
from r2.contracts.automation import ModelRoute, RunStage
from r2.contracts.common import ensure_json_value
from server.production_run.final_checks import picture_findings, subtitle_findings

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

OBSERVATION_STEP = """Bước 0 — quan sát, ghi vào "frames" đúng {frame_count} mục theo thứ tự:
- content: khung hình thực sự cho thấy gì (ngắn gọn);
- matches_narration: true nếu hình hợp với câu phụ đề của chính khung đó (cùng nhân vật, bối cảnh hoặc sự việc),
  false nếu hình nói về chuyện khác hẳn;
- upside_down: true nếu hình bị lộn ngược (trời ở dưới, người chổng ngược);
- defect: BLACK (đen/trống), NOISE (nhiễu hạt, vỡ hình), TEST_PATTERN (sọc màu thử sóng), TINY_OR_CROPPED (hình nhỏ
  giữa nền đen hoặc bị cắt mất phần chính), DISTORTED (méo, kéo giãn), hoặc NONE.

"""
FRAME_DEFECTS = ("NONE", "BLACK", "NOISE", "TEST_PATTERN", "TINY_OR_CROPPED", "DISTORTED")

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


OBSERVATION_SCHEMA = {
    **SCHEMA,
    "required": ["frames", *SCHEMA["required"]],
    "properties": {
        "frames": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["content", "matches_narration", "upside_down", "defect"],
                "properties": {
                    "content": {"type": "string"},
                    "matches_narration": {"type": "boolean"},
                    "upside_down": {"type": "boolean"},
                    "defect": {"enum": list(FRAME_DEFECTS)},
                },
            },
        },
        **SCHEMA["properties"],
    },
}

QUESTIONS = "questions"
OBSERVATIONS = "observations"
# Review method of each qualified reviewer model, chosen on the calibration split; unlisted models ask questions.
REVIEW_METHODS: dict[str, str] = {"qwen2.5vl:7b": OBSERVATIONS, "gemma3:4b": QUESTIONS}


def review_method(route: ModelRoute) -> str:
    return REVIEW_METHODS.get(route.model_id, QUESTIONS)


def review_prompt(method: str) -> str:
    return (
        PROMPT.replace("Bước 1 — chấm điểm", OBSERVATION_STEP + "Bước 1 — chấm điểm")
        if method == OBSERVATIONS
        else PROMPT
    )


def observed_findings(answer: dict, *, unit_key: str) -> list[AssessmentFinding]:
    """Findings from the scoring answer's own frame observations (the ``observations`` method)."""
    frames = [frame for frame in answer.get("frames") or [] if isinstance(frame, dict)]
    broken = [str(f.get("defect", "NONE")) for f in frames if str(f.get("defect", "NONE")) != "NONE"]
    flipped = sum(1 for f in frames if f.get("upside_down") is True)
    unrelated = sum(1 for f in frames if f.get("matches_narration") is False)
    found: list[AssessmentFinding] = []
    if len(broken) >= MIN_BROKEN_FRAMES:
        found.append(
            AssessmentFinding(
                code="OBSERVED_BROKEN_FRAMES",
                severity="CRITICAL",
                unit_key=unit_key,
                repair_stage=RunStage.MEDIA,
                detail=", ".join(sorted(set(broken))) + f" in {len(broken)} frames",
            )
        )
    if flipped >= MIN_FLIPPED_FRAMES:
        found.append(
            AssessmentFinding(
                code="OBSERVED_UPSIDE_DOWN",
                severity="CRITICAL",
                unit_key=unit_key,
                repair_stage=RunStage.MEDIA,
                detail=f"{flipped} frames upside down",
            )
        )
    if frames and 2 * unrelated >= len(frames):
        found.append(
            AssessmentFinding(
                code="OBSERVED_UNRELATED_FRAMES",
                severity="CRITICAL",
                unit_key=unit_key,
                repair_stage=RunStage.MEDIA,
                detail=f"{unrelated} of {len(frames)} frames unrelated to their narration",
            )
        )
    return found


def frame_answer_findings(
    flipped: list[bool | None],
    illustrates: list[bool | None],
    broken: list[bool | None] | None = None,
    *,
    unit_key: str,
) -> list[AssessmentFinding]:
    """Findings from the reviewer's one-picture answers: broken, upside-down and non-illustrating frames."""
    found: list[AssessmentFinding] = []
    damaged = sum(1 for answer in broken or [] if answer is True)
    upside_down = sum(1 for answer in flipped if answer is True)
    mismatched = sum(1 for answer in illustrates if answer is False)
    if damaged >= MIN_BROKEN_FRAMES:
        found.append(
            AssessmentFinding(
                code="FRAME_BROKEN",
                severity="CRITICAL",
                unit_key=unit_key,
                repair_stage=RunStage.MEDIA,
                detail=f"{damaged} frames black, noisy or a test pattern",
            )
        )
    if upside_down >= MIN_FLIPPED_FRAMES:
        found.append(
            AssessmentFinding(
                code="FRAME_UPSIDE_DOWN",
                severity="CRITICAL",
                unit_key=unit_key,
                repair_stage=RunStage.MEDIA,
                detail=f"{upside_down} frames upside down",
            )
        )
    if mismatched >= MIN_MISMATCHED_FRAMES:
        found.append(
            AssessmentFinding(
                code="FRAME_NOT_ILLUSTRATING_NARRATION",
                severity="CRITICAL",
                unit_key=unit_key,
                repair_stage=RunStage.MEDIA,
                detail=f"{mismatched} frames do not illustrate their narration line",
            )
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


class QualifiedEvaluator(Protocol):
    async def assess(self, *, route: ModelRoute, evidence: FinalEvidence) -> ModelAssessment: ...


def prompt_digest(method: str = QUESTIONS) -> str:
    """The digest of everything a reviewer of ``method`` is asked and the fixed rules applied to its answers."""
    observing = method == OBSERVATIONS
    return digest_value(
        "r2.production-review-prompt.v8",
        ensure_json_value(
            {
                "method": method,
                "prompt": review_prompt(method),
                "schema": OBSERVATION_SCHEMA if observing else SCHEMA,
                "questions": [ORIENTATION_QUESTION]
                if observing
                else [BROKEN_QUESTION, UPRIGHT_QUESTION, ORIENTATION_QUESTION, MATCH_QUESTION],
                "thresholds": [MIN_BROKEN_FRAMES, MIN_FLIPPED_FRAMES, MIN_MISMATCHED_FRAMES],
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


class OllamaReviewer:
    """A reviewer route served by an Ollama chat endpoint that accepts images."""

    def __init__(
        self,
        *,
        base_url_for: Callable[[str], Awaitable[str]],
        timeout_seconds: float = 600,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url_for = base_url_for
        self._timeout = timeout_seconds
        self._transport = transport

    async def assess(self, *, route: ModelRoute, evidence: FinalEvidence) -> ModelAssessment:
        base = {
            "reviewer_route_digest": route_digest(route),
            "model_identity": route.model_identity,
            "prompt_digest": prompt_digest(review_method(route)),
            "subject_digest": evidence.subject_digest,
            "evidence_digest": evidence_digest(evidence),
        }
        method = review_method(route)
        try:
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
            url = normalize_ollama_base_url(await self._base_url_for(route.provider_id))
            body = {
                "model": route.model_id,
                "stream": False,
                "truncate": False,
                "shift": False,
                "format": OBSERVATION_SCHEMA if method == OBSERVATIONS else SCHEMA,
                "messages": [
                    {
                        "role": "user",
                        "content": review_prompt(method).format(
                            frame_count=len(frames),
                            frame_cues=cues,
                            subtitles=subtitles[:6000],
                            narration=evidence.narration_text[:6000],
                        ),
                        "images": [base64.b64encode(frame).decode("ascii") for frame in frames],
                    }
                ],
                "options": {"temperature": 0, "num_ctx": CONTEXT_TOKENS},
            }
            times = frame_times(duration, len(frames))
            async with (
                device_job(local_job(url, route.model_id)),
                httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client,
            ):

                async def ask(question: str, frame: bytes, parse: Callable[[str], bool | None] = yes_no) -> bool | None:
                    reply = await client.post(
                        url + "/api/chat",
                        json={
                            "model": route.model_id,
                            "stream": False,
                            "think": False,
                            "truncate": False,
                            "messages": [
                                {
                                    "role": "user",
                                    "content": question,
                                    "images": [base64.b64encode(frame).decode("ascii")],
                                }
                            ],
                            "options": {"temperature": 0, "num_predict": 8, "num_ctx": CONTEXT_TOKENS},
                        },
                    )
                    reply.raise_for_status()
                    return parse(str(reply.json()["message"].get("content") or ""))

                broken: list[bool | None] = []
                illustrates: list[bool | None] = []
                flipped: list[bool | None] = []
                for frame, pair, seconds in zip(frames, pairs, times, strict=True):
                    compared = await ask(ORIENTATION_QUESTION, pair, upright_letter)
                    if method == OBSERVATIONS:
                        flipped.append(compared)
                        continue
                    broken.append(await ask(BROKEN_QUESTION, frame))
                    alone = await ask(UPRIGHT_QUESTION, frame)
                    flipped.append(True if True in (alone, compared) else None if None in (alone, compared) else False)
                    illustrates.append(await ask(MATCH_QUESTION.format(cue=cue_at(subtitles, seconds) or "—"), frame))
                response = await client.post(url + "/api/chat", json=body)
            response.raise_for_status()
            answer = json.loads(response.json()["message"]["content"])
            checks += frame_answer_findings(flipped, illustrates, broken, unit_key=evidence.unit_key)
            if method == OBSERVATIONS:
                checks += observed_findings(answer, unit_key=evidence.unit_key)
            return ModelAssessment.model_validate(
                {
                    **base,
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
            return ModelAssessment.model_validate({**base, "outcome": "FAILED"})


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
    "OllamaReviewer",
    "QualifiedEvaluator",
    "evidence_digest",
    "prompt_digest",
    "provider_base_url",
]

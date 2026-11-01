"""Blind model review of one final film by one frozen reviewer route.

The reviewer sees sampled frames of the final, its subtitle sidecar and the episode's narration text, and nothing
about the writer, the other reviewer or the run. It answers in a fixed schema: the language it heard, a 1–5 score
per creative dimension and findings with the stage that would repair them. A transport error, timeout or a
response outside the schema is a FAILED assessment, never a pass.
"""

from __future__ import annotations

import base64
import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import httpx

from lib.generation_resources import device_job, local_job
from lib.text_backends.ollama import normalize_ollama_base_url
from r2.automation.assessment import CREATIVE_DIMENSIONS, AssessmentFinding, ModelAssessment
from r2.automation.identity import digest_value
from r2.automation.profiles import route_digest
from r2.contracts.automation import ModelRoute, RunStage
from r2.contracts.common import ensure_json_value

FRAME_COUNT = 8

PROMPT = """Bạn là người duyệt chất lượng phim ngắn tiếng Việt dạng kể chuyện (9:16, 30–60 giây).
Bạn nhận các khung hình lấy đều từ phim, phụ đề và lời kể. Hãy chấm độc lập, khắt khe.
Trả về JSON đúng schema:
- language: mã ngôn ngữ của lời kể/phụ đề (ví dụ "vi").
- scores: điểm 1–5 cho story, visual, audio, continuity, pacing (4 nghĩa là đủ chất lượng phát hành).
- findings: lỗi tìm thấy, mỗi lỗi có code, severity (CRITICAL/MAJOR/MINOR), repair_stage
  (SCRIPT_PLAN, SCRIPT, MEDIA, RENDER hoặc null nếu không sửa được) và detail ngắn.
Lỗi CRITICAL gồm: sai ngôn ngữ, thiếu tiếng/phụ đề, nội dung không phù hợp, hình hỏng nặng.

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


@dataclass(frozen=True)
class FinalEvidence:
    unit_key: str
    final_path: Path
    subtitle_path: Path
    narration_text: str
    subject_digest: str


class QualifiedEvaluator(Protocol):
    async def assess(self, *, route: ModelRoute, evidence: FinalEvidence) -> ModelAssessment: ...


def prompt_digest() -> str:
    return digest_value("r2.production-review-prompt.v1", ensure_json_value({"prompt": PROMPT, "schema": SCHEMA}))


def evidence_digest(evidence: FinalEvidence) -> str:
    return digest_value(
        "r2.production-review-evidence.v1",
        {
            "subject": evidence.subject_digest,
            "subtitles": evidence.subtitle_path.read_text(encoding="utf-8"),
            "narration": evidence.narration_text,
        },
    )


def sample_frames(final: Path, *, count: int = FRAME_COUNT, ffmpeg: str = "ffmpeg") -> list[bytes]:
    with tempfile.TemporaryDirectory() as work:
        pattern = str(Path(work) / "frame_%02d.jpg")
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(final)],
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
        duration = max(float(probe.stdout.strip() or 0), 1.0)
        subprocess.run(
            [
                ffmpeg,
                "-nostdin",
                "-loglevel",
                "error",
                "-i",
                str(final),
                "-vf",
                f"fps={count}/{duration:.3f},scale=288:-2",
                "-frames:v",
                str(count),
                pattern,
            ],
            check=True,
            timeout=300,
        )
        return [path.read_bytes() for path in sorted(Path(work).glob("frame_*.jpg"))]


class OllamaReviewer:
    """A reviewer route served by an Ollama chat endpoint that accepts images."""

    def __init__(self, *, base_url_for: dict[str, str], timeout_seconds: float = 600) -> None:
        self._base_url_for = base_url_for
        self._timeout = timeout_seconds

    async def assess(self, *, route: ModelRoute, evidence: FinalEvidence) -> ModelAssessment:
        base = {
            "reviewer_route_digest": route_digest(route),
            "model_identity": route.model_identity,
            "prompt_digest": prompt_digest(),
            "subject_digest": evidence.subject_digest,
            "evidence_digest": evidence_digest(evidence),
        }
        try:
            frames = sample_frames(evidence.final_path)
            url = normalize_ollama_base_url(self._base_url_for[route.provider_id])
            body = {
                "model": route.model_id,
                "stream": False,
                "format": SCHEMA,
                "messages": [
                    {
                        "role": "user",
                        "content": PROMPT.format(
                            subtitles=evidence.subtitle_path.read_text(encoding="utf-8")[:6000],
                            narration=evidence.narration_text[:6000],
                        ),
                        "images": [base64.b64encode(frame).decode("ascii") for frame in frames],
                    }
                ],
                "options": {"temperature": 0},
            }
            async with device_job(local_job(url, route.model_id)), httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(url + "/api/chat", json=body)
            response.raise_for_status()
            answer = json.loads(response.json()["message"]["content"])
            return ModelAssessment.model_validate(
                {
                    **base,
                    "outcome": "COMPLETED",
                    "language": str(answer["language"]).strip().lower()[:8],
                    "scores": answer["scores"],
                    "findings": [
                        AssessmentFinding(
                            code=str(f["code"]).upper()[:64] or "UNSPECIFIED",
                            severity=f["severity"],
                            unit_key=evidence.unit_key,
                            repair_stage=RunStage(f["repair_stage"]) if f.get("repair_stage") else None,
                            detail=str(f.get("detail", ""))[:500],
                        )
                        for f in answer["findings"]
                    ],
                }
            )
        except (httpx.HTTPError, KeyError, TypeError, ValueError, subprocess.SubprocessError):
            return ModelAssessment.model_validate({**base, "outcome": "FAILED"})


__all__ = ["FinalEvidence", "OllamaReviewer", "QualifiedEvaluator", "evidence_digest", "prompt_digest"]

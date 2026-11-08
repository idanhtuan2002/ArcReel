"""Host media probe: one real sample through a project's image, video or audio route before a run may use it.

A launch profile names the media routes its qualification was measured on. Any other route of the same role — a
cloud image model, a video model, another voice engine added from the UI — becomes usable for automatic runs once
this probe has made one sample through it and the sample passed the same deterministic checks a run applies to
every unit (``unit_checks``). The sample is made through the app's own backend assembly (so the release paid-route
gate applies) inside the usage ledger (so its cost is recorded). The evidence names the exact route digest, so a
changed model, endpoint or key needs a new probe. Evidence lives in the host receipts directory, never in a
project folder.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.audio_backends.base import AudioSynthesisRequest
from lib.backend_assembly import assemble_backend
from lib.config.resolver import ConfigResolver
from lib.image_backends.base import ImageGenerationRequest
from lib.ledger import Ledger
from lib.video_backends.base import VideoGenerationRequest
from r2.automation.profiles import route_digest
from r2.contracts.automation import ModelRoute
from server.production_run.unit_checks import clip_problem, narration_problem, storyboard_problem

MEDIA_ROLES = ("image", "video", "audio")
PROBE_SCHEMA = "r2.media-route-probe.v1"
PROBE_DIRECTORY = "media-routes"
PROBE_PROJECT = "media-route-probe"
PROBE_LINE = "Buổi sáng, hai đứa trẻ thả diều trên cánh đồng lúa xanh."
PROBE_PROMPT = (
    "Vertical storyboard frame for a Vietnamese short video: morning, two children fly a kite over a green rice "
    "field, soft light, clear subject, no text."
)
PROBE_CLIP_SECONDS = 5


RECEIPTS_ENV = "ARCREEL_REVIEWER_RECEIPTS"


def receipts_dir() -> Path | None:
    """The host's qualification receipts directory (a host setting, never request input)."""
    value = os.environ.get(RECEIPTS_ENV)
    return Path(value) if value else None


def _digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def probe_path(receipts: Path, route: ModelRoute) -> Path:
    """Where the evidence of ``route``'s probe is kept."""
    return receipts / PROBE_DIRECTORY / f"{route.role}-{route_digest(route).removeprefix('sha256:')[:32]}.json"


def _start_frame(path: Path, *, width: int, height: int) -> None:
    """A plain drawn picture to animate when probing a video route."""
    image = Image.new("RGB", (width, height), (96, 160, 96))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, width, height // 2), fill=(150, 200, 235))
    draw.ellipse((width // 3, height // 6, width // 3 + width // 4, height // 6 + width // 4), fill=(250, 220, 90))
    image.save(path, format="PNG")


async def probe_media_route(
    sessions: async_sessionmaker[AsyncSession],
    *,
    route: ModelRoute,
    receipts: Path,
    voice: str,
    width: int,
    height: int,
    user_id: str,
) -> dict[str, Any]:
    """Make one sample through ``route``, check it and record the evidence; a backend error is recorded as failed."""
    if route.role not in MEDIA_ROLES:
        raise ValueError("NOT_A_MEDIA_ROUTE")
    evidence_path = probe_path(receipts, route)
    work = evidence_path.with_suffix("")
    work.mkdir(parents=True, exist_ok=True)
    portrait = height >= width
    aspect = "9:16" if portrait else "16:9"
    sample = work / {"image": "sample.png", "video": "sample.mp4", "audio": "sample.wav"}[route.role]
    sample.unlink(missing_ok=True)
    problem: str | None
    error: str | None = None
    try:
        async with ConfigResolver(sessions).session() as resolver:
            backend = await assemble_backend(
                provider_id=route.provider_id, media_type=route.role, model_id=route.model_id, resolver=resolver
            )
        ledger = Ledger(session_factory=sessions)
        if route.role == "image":
            async with ledger.record(
                project_name=PROBE_PROJECT,
                call_type="image",
                model=route.model_id,
                provider=route.provider_id,
                prompt=PROBE_PROMPT,
                aspect_ratio=aspect,
                user_id=user_id,
                output_path=str(sample),
            ) as call:
                result = await backend.generate(
                    ImageGenerationRequest(prompt=PROBE_PROMPT, output_path=sample, aspect_ratio=aspect)
                )
                call.success(result)
            problem = storyboard_problem(sample, portrait=portrait)
        elif route.role == "video":
            start = work / "start.png"
            _start_frame(start, width=width, height=height)
            async with ledger.record(
                project_name=PROBE_PROJECT,
                call_type="video",
                model=route.model_id,
                provider=route.provider_id,
                prompt=PROBE_PROMPT,
                duration_seconds=PROBE_CLIP_SECONDS,
                aspect_ratio=aspect,
                generate_audio=False,
                user_id=user_id,
                output_path=str(sample),
            ) as call:
                result = await backend.generate(
                    VideoGenerationRequest(
                        prompt=PROBE_PROMPT,
                        output_path=sample,
                        aspect_ratio=aspect,
                        duration_seconds=PROBE_CLIP_SECONDS,
                        start_image=start,
                        generate_audio=False,
                    )
                )
                call.success(result)
            problem = clip_problem(sample, portrait=portrait)
        else:
            async with ledger.record(
                project_name=PROBE_PROJECT,
                call_type="audio",
                model=route.model_id,
                provider=route.provider_id,
                prompt=PROBE_LINE,
                user_id=user_id,
                output_path=str(sample),
            ) as call:
                result = await backend.synthesize(
                    AudioSynthesisRequest(text=PROBE_LINE, output_path=sample, voice=voice, language_type="Vietnamese")
                )
                call.success(result)
            problem = narration_problem(sample)
    except Exception as failure:  # any backend refusal or failure is the probe's outcome, never a crash
        problem, error = "GENERATION_FAILED", type(failure).__name__
    evidence = {
        "schema": PROBE_SCHEMA,
        "recorded_at": datetime.now(UTC).isoformat(),
        "role": route.role,
        "provider_id": route.provider_id,
        "model_id": route.model_id,
        "model_identity": route.model_identity,
        "route_digest": route_digest(route),
        "sample": sample.name if sample.is_file() else None,
        "sample_digest": _digest(sample) if sample.is_file() else None,
        "problem": problem,
        "error": error,
        "passed": problem is None,
    }
    evidence_path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return evidence


def probe_evidence(receipts: Path | None, route: ModelRoute) -> dict[str, Any] | None:
    """The recorded probe of exactly ``route``, when its sample is still the one it checked."""
    if receipts is None:
        return None
    path = probe_path(receipts, route)
    try:
        evidence = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if evidence.get("schema") != PROBE_SCHEMA or evidence.get("route_digest") != route_digest(route):
        return None
    if evidence.get("passed") is True:
        sample = path.with_suffix("") / str(evidence.get("sample"))
        if not sample.is_file() or _digest(sample) != evidence.get("sample_digest"):
            return None
    return evidence


def passed_probes(receipts: Path | None, routes: tuple[ModelRoute, ...]) -> frozenset[str]:
    """The route digests of ``routes`` whose probe passed."""
    passed = set()
    for route in routes:
        if route.role in MEDIA_ROLES:
            evidence = probe_evidence(receipts, route)
            if evidence is not None and evidence.get("passed") is True:
                passed.add(route_digest(route))
    return frozenset(passed)


__all__ = [
    "MEDIA_ROLES",
    "RECEIPTS_ENV",
    "passed_probes",
    "probe_evidence",
    "probe_media_route",
    "probe_path",
    "receipts_dir",
]

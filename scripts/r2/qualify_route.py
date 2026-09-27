"""Operator canary that qualifies one paid route for a release deployment (ADR-0091, F1 route level).

Running this command is the operator's authorization for one small paid call on the
exact route and model. The call goes through the normal backend assembly and the usage
ledger, so it is recorded and, in a release deployment, budget-checked. Its output is
checked: a non-empty file for image, video and audio, non-empty text for text. On
success the evidence is written under the data root and the route becomes qualified
until the expiry. A failure records nothing.

    uv run python -m scripts.r2.qualify_route --provider openai --media image --model gpt-image-2
    uv run python -m scripts.r2.qualify_route --provider custom-7 --media video --model relay-video --duration 5
    uv run python -m scripts.r2.qualify_route --agent

Trial runs cannot be qualified here; in a release deployment they stay refused.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import hashlib
import json
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from lib.backend_assembly import assemble_backend
from lib.budget_guard import call_reference
from lib.config.resolver import ConfigResolver
from lib.db import async_session_factory
from lib.ledger import Ledger
from r2.host_hardening.paid_routes import PaidRoute, media_route, qualification_canary
from r2.host_hardening.route_qualifications import adapter_version_for, record_qualification

CANARY_PROJECT = "__route_qualification__"
_PROMPT = "A single red apple on a plain white table."


class CanaryFailedError(RuntimeError):
    """The canary call ran but did not produce a usable result."""


def _file_summary(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size == 0:
        raise CanaryFailedError(f"canary produced no output file at {path.name}")
    data = path.read_bytes()
    return {"output_bytes": len(data), "output_sha256": hashlib.sha256(data).hexdigest()}


async def _generate(backend: Any, media: str, workdir: Path, args: argparse.Namespace) -> tuple[Any, dict[str, Any]]:
    if media == "image":
        from lib.image_backends.base import ImageGenerationRequest

        request = ImageGenerationRequest(prompt=_PROMPT, output_path=workdir / "canary.png", aspect_ratio="1:1")
        result = await backend.generate(request)
        return result, _file_summary(request.output_path)
    if media == "video":
        from lib.video_backends.base import VideoGenerationRequest

        request = VideoGenerationRequest(
            prompt=_PROMPT, output_path=workdir / "canary.mp4", duration_seconds=args.duration, aspect_ratio="16:9"
        )
        result = await backend.generate(request)
        return result, _file_summary(request.output_path)
    if media == "audio":
        from lib.audio_backends.base import AudioSynthesisRequest

        if not args.voice:
            raise CanaryFailedError("--voice is required for an audio route")
        request = AudioSynthesisRequest(text="OK.", output_path=workdir / "canary.wav", voice=args.voice)
        result = await backend.synthesize(request)
        return result, _file_summary(request.output_path)
    from lib.text_backends.base import TextGenerationRequest

    result = await backend.generate(
        TextGenerationRequest(prompt="Reply with the single word OK.", max_output_tokens=16)
    )
    text = (getattr(result, "text", "") or "").strip()
    if not text:
        raise CanaryFailedError("canary produced no text")
    return result, {"output_chars": len(text)}


async def run_media_canary(args: argparse.Namespace, *, session_factory=async_session_factory) -> dict[str, Any]:
    route = media_route(args.provider, args.media)
    started = datetime.now(UTC)
    with tempfile.TemporaryDirectory(prefix="arcreel-canary-") as tmp, qualification_canary(route, args.model):
        backend = await assemble_backend(
            provider_id=args.provider,
            media_type=args.media,
            model_id=args.model,
            resolver=ConfigResolver(session_factory),
        )
        ledger = Ledger(session_factory=session_factory)
        async with ledger.record(
            project_name=CANARY_PROJECT,
            call_type=args.media,
            model=args.model,
            provider=args.provider,
            duration_seconds=args.duration if args.media == "video" else None,
        ) as call:
            result, output = await _generate(backend, args.media, Path(tmp), args)
            call.success(result)
        cost_record_ref = call_reference(call.call_id)
    return _finish(route, args, started=started, output=output, cost_record_ref=cost_record_ref)


async def run_agent_canary(args: argparse.Namespace, *, session_factory=async_session_factory) -> dict[str, Any]:
    from lib.config.anthropic_probe import run_test
    from lib.db.repositories.agent_credential_repo import AgentCredentialRepository

    async with session_factory() as session:
        credential = await AgentCredentialRepository(session).get_active()
    if credential is None:
        raise CanaryFailedError("no active Agent credential")
    route = PaidRoute("agent", provider_id=credential.preset_id)
    started = datetime.now(UTC)
    result = await run_test(
        preset_id=credential.preset_id,
        base_url=credential.base_url,
        api_key=credential.api_key,
        model=credential.model,
    )
    if result.overall == "fail" or not result.messages_probe.success:
        raise CanaryFailedError("the Agent provider's message test did not pass")
    args.model = credential.model or ""
    return _finish(route, args, started=started, output={"messages_ok": True}, cost_record_ref=None)


def _finish(
    route: PaidRoute,
    args: argparse.Namespace,
    *,
    started: datetime,
    output: dict[str, Any],
    cost_record_ref: str | None,
) -> dict[str, Any]:
    finished = datetime.now(UTC)
    evidence = {
        "schema_version": 1,
        "route_ref": route.ref,
        "model_id": args.model,
        "adapter_version": adapter_version_for(route),
        "evidence_kind": "REAL_PROVIDER_CALL",
        "result": "PASS",
        "required_skips": 0,
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "cost_record_ref": cost_record_ref,
        "output": output,
    }
    record = record_qualification(
        route=route,
        model_id=args.model,
        evidence=evidence,
        expires_at=finished + timedelta(days=args.ttl_days),
        cost_record_ref=cost_record_ref,
        recorded_by=args.recorded_by,
        now=finished,
    )
    return {"qualified": record.route_ref, "model": record.model_id, "expires_at": record.expires_at}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--agent", action="store_true", help="qualify the active Agent credential's provider")
    target.add_argument("--provider", help="built-in provider id or custom-<id>")
    parser.add_argument("--media", choices=("image", "video", "text", "audio"))
    parser.add_argument("--model")
    parser.add_argument("--duration", type=int, default=5, help="video seconds (a duration the model supports)")
    parser.add_argument("--voice", help="voice id for an audio route")
    parser.add_argument("--ttl-days", type=int, default=30)
    parser.add_argument("--recorded-by", default=getpass.getuser())
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.provider and (not args.media or not args.model):
        parser.error("--provider needs --media and --model")
    try:
        result = asyncio.run(run_agent_canary(args) if args.agent else run_media_canary(args))
    except Exception as exc:
        print(json.dumps({"error": type(exc).__name__, "detail": str(exc)[:500]}), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

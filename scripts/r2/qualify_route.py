"""Operator canary that qualifies one paid route for a release deployment (ADR-0091, F1 route level).

Running this command is the operator's authorization for one small paid call on the
exact route and model. The call goes through the normal backend assembly and the usage
ledger, so it is recorded and, in a release deployment, budget-checked. Its output is
checked: a non-empty file for image, video and audio, non-empty text for text. On
success the evidence is written under the data root and the route becomes qualified
until the expiry. A failure records nothing.

    uv run python -m scripts.r2.qualify_route --provider openai --media image --model gpt-image-2
    uv run python -m scripts.r2.qualify_route --provider custom-7 --media text --model relay-chat
    uv run python -m scripts.r2.qualify_route --provider anthropic-official --media agent --model claude-sonnet-4-6

The qualification is bound to the model the backend actually calls and to the provider's
configuration, by digest (ADR-0091 amendment item 1): a new key, base URL or endpoint needs a new
canary. A route whose adapter level does not hold is refused before any paid call: today that is
every video route, whose shipped adapter profiles are UNQUALIFIED. Trial runs cannot be qualified.

The Agent canary (``--media agent``, ADR-0093) qualifies the active Agent credential. Only the
``anthropic-official`` preset with Claude models can qualify. It runs one tiny query under a cap of
``AGENT_CANARY_CAP_USD`` and passes only if the CLI stops it with ``error_max_budget_usd`` and
reports a cost: that proves the per-connection budget cap is enforced on the live route. Its
``--model`` must equal the credential's model (empty for the CLI default).
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import hashlib
import json
import sys
import tempfile
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from lib.backend_assembly import assemble_backend
from lib.backend_assembly.assembler import paid_route_binding
from lib.budget_guard import call_reference, reconcile_agent_connection, reserve_agent_connection
from lib.config.resolver import ConfigResolver
from lib.db import async_session_factory
from lib.ledger import Ledger
from r2.host_hardening.paid_routes import PaidRoute, media_route, qualification_canary
from r2.host_hardening.route_qualifications import adapter_level_holds, adapter_version_for, record_qualification

CANARY_PROJECT = "__route_qualification__"
_PROMPT = "A single red apple on a plain white table."


class CanaryFailedError(RuntimeError):
    """The canary call ran but did not produce a usable result."""


class CanaryRefusedError(RuntimeError):
    """The route cannot become qualified, so no paid canary call is made."""


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
    if not adapter_level_holds(route, datetime.now(UTC)):
        raise CanaryRefusedError(
            f"{route.ref} has no offline-verified adapter profile, so a canary cannot qualify it; no paid call was made"
        )
    resolver = ConfigResolver(session_factory)
    binding = await paid_route_binding(
        provider_id=args.provider, media_type=args.media, resolver=resolver, model_id=args.model
    )
    started = datetime.now(UTC)
    with tempfile.TemporaryDirectory(prefix="arcreel-canary-") as tmp, qualification_canary(route, args.model):
        backend = await assemble_backend(
            provider_id=args.provider,
            media_type=args.media,
            model_id=args.model,
            resolver=resolver,
        )
        actual_model = getattr(backend, "model", None)
        if actual_model is not None and actual_model != args.model:
            raise CanaryFailedError(
                f"the provider resolves {args.model!r} to {actual_model!r}; qualify an enabled model"
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
    return _finish(route, args, binding=binding, started=started, output=output, cost_record_ref=cost_record_ref)


def _finish(
    route: PaidRoute,
    args: argparse.Namespace,
    *,
    binding: str,
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
        binding=binding,
        evidence=evidence,
        expires_at=finished + timedelta(days=args.ttl_days),
        cost_record_ref=cost_record_ref,
        recorded_by=args.recorded_by,
        now=finished,
    )
    return {"qualified": record.route_ref, "model": record.model_id, "expires_at": record.expires_at}


AGENT_CANARY_CAP_USD = 0.0001
AGENT_CANARY_RESERVATION = Decimal("0.10")
AgentQuery = Callable[[dict[str, str], float, Path], Awaitable[dict[str, Any]]]


async def _agent_query(env: dict[str, str], cap: float, workdir: Path) -> dict[str, Any]:
    """One headless Agent query without tools; returns the CLI's result message fields."""
    from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

    options = ClaudeAgentOptions(
        cwd=str(workdir), env=env, max_budget_usd=cap, max_turns=1, allowed_tools=[], setting_sources=[]
    )
    result: dict[str, Any] = {}
    async for message in query(prompt="Reply with the single word OK.", options=options):
        if isinstance(message, ResultMessage):
            result = {
                "subtype": message.subtype,
                "total_cost_usd": message.total_cost_usd,
                "usage": message.usage,
                "model_usage": sorted((getattr(message, "model_usage", None) or {}).keys()),
            }
    return result


async def run_agent_canary(
    args: argparse.Namespace, *, session_factory=async_session_factory, agent_query: AgentQuery = _agent_query
) -> dict[str, Any]:
    """Qualify the active Agent route: the CLI must enforce a tiny budget cap and report the cost."""
    from lib.db.repositories.agent_credential_repo import AgentCredentialRepository
    from r2.host_hardening.route_qualifications import agent_route_priced
    from server.agent_runtime.options_assembler import agent_route_binding, load_provider_env_overrides

    async with session_factory() as session:
        credential = await AgentCredentialRepository(session).get_active()
    if credential is None:
        raise CanaryRefusedError("no active Agent credential; configure one first")
    route = PaidRoute("agent", provider_id=credential.preset_id)
    model = credential.model or ""
    if credential.preset_id != args.provider or model != args.model:
        raise CanaryRefusedError(
            f"the active Agent credential is {credential.preset_id!r} with model {model!r}; qualify exactly that"
        )
    models = [
        m
        for m in (
            model,
            credential.haiku_model,
            credential.sonnet_model,
            credential.opus_model,
            credential.subagent_model,
        )
        if m
    ]
    if not agent_route_priced(credential.preset_id, model) or not all(
        agent_route_priced(credential.preset_id, m) for m in models
    ):
        raise CanaryRefusedError(
            f"{route.ref} with models {models or ['<CLI default>']} is not priced by the CLI; "
            "only anthropic-official with Claude models can qualify (ADR-0093); no paid call was made"
        )
    binding = agent_route_binding(credential)
    # Load the credentials before reserving: a setup failure then leaves no hold behind.
    env = await load_provider_env_overrides()
    env["CLAUDE_CODE_MAX_RETRIES"] = "0"
    reserved = await reserve_agent_connection(session_factory, amount=AGENT_CANARY_RESERVATION, purpose="agent_canary")
    started = datetime.now(UTC)
    cost = Decimal(0)
    try:
        with tempfile.TemporaryDirectory(prefix="arcreel-agent-canary-") as tmp:
            result = await agent_query(env, AGENT_CANARY_CAP_USD, Path(tmp))
        reported = result.get("total_cost_usd")
        cost = Decimal(str(reported)) if isinstance(reported, int | float) else Decimal(0)
        await Ledger(session_factory=session_factory).backfill(
            project_name=CANARY_PROJECT,
            call_type="text",
            model=model or "claude-cli-default",
            provider="anthropic",
            prompt="agent route canary",
            user_id="default",
            status="success" if result.get("subtype") == "error_max_budget_usd" else "failed",
            cost_amount=float(cost),
            currency="USD",
        )
        if result.get("subtype") != "error_max_budget_usd" or cost <= 0:
            raise CanaryFailedError(
                f"the CLI did not stop at the ${AGENT_CANARY_CAP_USD} cap with a reported cost: "
                f"subtype={result.get('subtype')!r} total_cost_usd={reported!r}"
            )
    finally:
        if reserved is not None:
            await reconcile_agent_connection(session_factory, reservation_ref=reserved[0], actual_usd=cost)
    output = {"subtype": result["subtype"], "total_cost_usd": float(cost), "model_usage": result.get("model_usage")}
    cost_record_ref = reserved[0] if reserved is not None else None
    return _finish(route, args, binding=binding, started=started, output=output, cost_record_ref=cost_record_ref)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--provider", required=True, help="built-in provider id or custom-<id>")
    parser.add_argument("--media", required=True, choices=("image", "video", "text", "audio", "agent"))
    parser.add_argument("--model", required=True, help="model id; for --media agent, '' means the CLI default")
    parser.add_argument("--duration", type=int, default=5, help="video seconds (a duration the model supports)")
    parser.add_argument("--voice", help="voice id for an audio route")
    parser.add_argument("--ttl-days", type=int, default=30)
    parser.add_argument("--recorded-by", default=getpass.getuser())
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        canary = run_agent_canary if args.media == "agent" else run_media_canary
        result = asyncio.run(canary(args))
    except Exception as exc:
        print(json.dumps({"error": type(exc).__name__, "detail": str(exc)[:500]}), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

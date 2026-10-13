"""One operator command that takes the spatial route live once a real Gemini key exists.

Running it is the operator's authorization for two small paid calls on the configured
deployment (``DATABASE_URL``, ``ARCREEL_DATA_DIR``):

1. **Key.** When ``GEMINI_API_KEY`` is set, it is stored as the provider's ``api_key``.
   Otherwise the key already configured is used. The key is never printed.
2. **Canary.** One tiny text call qualifies the exact Gemini text route, model and
   configuration (ADR-0091 route level, the same as ``scripts.r2.qualify_route``).
3. **Smoke.** One spatial vision call, through the production prompt, parser and
   normalizer, on two images (by default the synthetic room in
   ``tests/fixtures/r2/spatial_live``). The call is ledgered under the canary project.

    DATABASE_URL=... ARCREEL_DATA_DIR=... GEMINI_API_KEY=... \\
        uv run python -m scripts.r2.spatial_live_ready --recorded-by "<operator>"

The command stops at the first failed step. Exit code 0 means all three steps passed.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from lib.config.resolver import ConfigResolver
from lib.config.service import ConfigService
from lib.db import async_session_factory
from lib.ledger import Ledger
from lib.text_backends.base import TextGenerationRequest, TextGenerationResult
from lib.text_backends.gemini import GeminiTextBackend
from lib.text_generator import TextGenerator
from scripts.r2.qualify_route import CANARY_PROJECT, run_media_canary
from scripts.r2.spatial_live_smoke import run as run_smoke

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "r2" / "spatial_live"
DEFAULT_MODEL = "gemini-3-flash-preview"


class _CanaryLedgeredModel:
    """The spatial vision call, ledgered under the canary project (no M7 execution exists here)."""

    def __init__(self, generator: TextGenerator) -> None:
        self._generator = generator

    async def generate(self, request: TextGenerationRequest, *, execution_id: str) -> TextGenerationResult:
        return await self._generator.generate(request, CANARY_PROJECT)


async def store_key(provider: str, key: str, *, session_factory=async_session_factory) -> None:
    async with session_factory() as session:
        await ConfigService(session).set_provider_config(provider, "api_key", key)
        await session.commit()


async def vision_model(provider: str, model: str, *, session_factory=async_session_factory):
    """The configured Gemini text backend for ``model``, wrapped so its usage is ledgered."""
    from lib.backend_assembly import assemble_backend

    resolver = ConfigResolver(session_factory)
    async with resolver.session() as configured:
        backend = await assemble_backend(provider_id=provider, media_type="text", model_id=model, resolver=configured)
    if not isinstance(backend, GeminiTextBackend):
        raise SystemExit(f"{provider} does not resolve to a Gemini text backend")
    generator = TextGenerator(backend, Ledger(session_factory=session_factory), provider)
    return _CanaryLedgeredModel(generator), backend.submitted_base_url


async def run(args: argparse.Namespace, *, master: bytes, reverse: bytes) -> tuple[dict[str, Any], dict[str, Any]]:
    summary: dict[str, Any] = {"provider": args.provider, "model": args.model}
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if key:
        await store_key(args.provider, key)
        summary["key"] = "STORED"
    else:
        summary["key"] = "USING_CONFIGURED"

    canary_args = argparse.Namespace(
        provider=args.provider,
        media="text",
        model=args.model,
        duration=5,
        voice=None,
        ttl_days=args.ttl_days,
        recorded_by=args.recorded_by,
    )
    summary["canary"] = await run_media_canary(canary_args)

    model, base_url = await vision_model(args.provider, args.model)
    evidence = await run_smoke(
        master=master,
        reverse=reverse,
        scene=args.scene,
        model_name=args.model,
        model=model,
        submitted_base_url=base_url,
    )
    summary["smoke"] = {"result": evidence["result"]}
    return summary, evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--provider", default="gemini-aistudio", choices=("gemini-aistudio", "gemini-vertex"))
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--master", default=str(FIXTURE_DIR / "master.png"))
    parser.add_argument("--reverse", default=str(FIXTURE_DIR / "reverse.png"))
    parser.add_argument("--scene", default="Synthetic room")
    parser.add_argument("--ttl-days", type=int, default=30)
    parser.add_argument("--recorded-by", default=getpass.getuser())
    parser.add_argument("--out", default="docs/r2/evidence", help="directory for the smoke evidence JSON")
    args = parser.parse_args(argv)
    try:
        summary, evidence = asyncio.run(
            run(args, master=Path(args.master).read_bytes(), reverse=Path(args.reverse).read_bytes())
        )
    except Exception as exc:
        print(json.dumps({"error": type(exc).__name__, "detail": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = Path(args.out) / f"R2_M8C_SPATIAL_LIVE_SMOKE_{stamp}.json"
    out.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    summary["smoke"]["evidence"] = str(out)
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if summary["smoke"]["result"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())

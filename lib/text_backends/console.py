"""Operator console for the shared configured text generation path."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence

from lib.backend_assembly.specs import PROVIDER_SPEC_REGISTRY
from lib.config.registry import PROVIDER_REGISTRY
from lib.text_backends.base import TextGenerationRequest, TextTaskType
from lib.text_generator import TextGenerator
from r2.host_hardening.route_qualifications import install_runtime_qualification_lookup


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


async def _run(args: argparse.Namespace) -> dict[str, object]:
    install_runtime_qualification_lookup()
    generator = await TextGenerator.create(TextTaskType.SCRIPT, provider_id=args.provider, model_id=args.model)
    identity = {"provider_id": args.provider, "model_id": generator.model}
    if args.check:
        return {**identity, "constructed": True, "live_provider_verified": False}
    result = await generator.generate(
        TextGenerationRequest(prompt=args.prompt, max_output_tokens=args.max_output_tokens),
        project_name=args.project,
    )
    return {
        **identity,
        "text": result.text,
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "finish_reason": result.finish_reason,
    }


def main(argv: Sequence[str] | None = None) -> int:
    """List registered models, construct a selection, or generate through Ledger."""
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--list", action="store_true", help="List registered builtins; availability is not verified")
    mode.add_argument("--check", action="store_true", help="Construct only; sends no generation request")
    mode.add_argument("--prompt", help="Generate text (may incur provider charges)")
    parser.add_argument("--provider", help="Exact builtin or custom-N provider ID")
    parser.add_argument("--model", help="Exact registered model ID")
    parser.add_argument("--project", help="Project name for the existing usage ledger")
    parser.add_argument("--max-output-tokens", type=_positive_int, default=256)
    args = parser.parse_args(argv)
    if args.list:
        if args.provider is not None or args.model is not None:
            parser.error("--list does not accept --provider or --model")
        rows = [
            {"provider_id": provider_id, "model_id": model_id, "display_name": info.display_name}
            for provider_id, provider in PROVIDER_REGISTRY.items()
            if (provider_id, "text") in PROVIDER_SPEC_REGISTRY
            for model_id, info in provider.models.items()
            if info.media_type == "text" and not info.hidden
        ]
        print(json.dumps(rows, ensure_ascii=False))
        return 0
    if not args.provider or not args.model:
        parser.error("--provider and --model are required for --check or --prompt")
    try:
        result = asyncio.run(_run(args))
    except Exception:
        print(json.dumps({"error": "MODEL_CALL_FAILED"}), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

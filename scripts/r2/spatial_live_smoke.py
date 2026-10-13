"""Operator live smoke for the spatial vision call: one real Gemini request on two real frames.

Running this command is the operator's authorization for one small paid call. It sends the
exact production prompt with MASTER then REVERSE, then parses and normalizes the raw response
with the production code. The evidence JSON records digests, sizes, timing and the result of
each step; it never records the key or the image bytes. The call bypasses the usage ledger.

    GEMINI_API_KEY=... uv run python -m scripts.r2.spatial_live_smoke \\
        --master frame_a.png --reverse frame_b.png --scene "Lobby" --model gemini-3-flash-preview

Exit code 0 means the real response normalized into a SpatialCandidate; 1 means it did not.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from lib.text_backends.base import TextGenerationRequest, TextGenerationResult
from lib.text_backends.gemini import GeminiTextBackend
from r2.advanced_creative.spatial import SpatialNormalizationError, SpatialSourceIdentity, normalize_spatial_candidate
from r2.advanced_creative.spatial_prompt import (
    MASTER_SOURCE_REF,
    REVERSE_SOURCE_REF,
    SPATIAL_PROMPT_VERSION,
    build_spatial_prompt,
    parse_spatial_response,
    spatial_prompt_digest,
)
from server.services.spatial_execution import (
    SPATIAL_NORMALIZER_VERSION,
    SpatialVisionModel,
    text_backend_spatial_vision,
)

DEFAULT_OUT = Path("docs/r2/evidence")


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


class _UnledgeredModel:
    def __init__(self, backend: GeminiTextBackend) -> None:
        self._backend = backend

    async def generate(self, request: TextGenerationRequest, *, execution_id: str) -> TextGenerationResult:
        return await self._backend.generate(request)


def gemini_model(model: str) -> tuple[SpatialVisionModel, str]:
    """The real Gemini model and the base URL it submits to; the key comes from ``GEMINI_API_KEY``."""
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("GEMINI_API_KEY is not set")
    backend = GeminiTextBackend(api_key=api_key, model=model)
    return _UnledgeredModel(backend), backend.submitted_base_url


async def run(
    *, master: bytes, reverse: bytes, scene: str, model_name: str, model: SpatialVisionModel, submitted_base_url: str
) -> dict[str, Any]:
    if _digest(master) == _digest(reverse):
        raise SystemExit("MASTER and REVERSE must be different images")
    prompt = build_spatial_prompt(scene)
    call = text_backend_spatial_vision(model)
    started = datetime.now(UTC)
    clock = time.monotonic()
    raw = await call(prompt=prompt, master_png=master, reverse_png=reverse, execution_id="live-smoke")
    elapsed_ms = round((time.monotonic() - clock) * 1000)
    evidence: dict[str, Any] = {
        "schema_version": 1,
        "evidence_kind": "REAL_PROVIDER_CALL",
        "route": "gemini/gemini-generate/host-spatial-v1",
        "model": model_name,
        "submitted_base_url": submitted_base_url,
        "prompt_version": SPATIAL_PROMPT_VERSION,
        "prompt_digest": spatial_prompt_digest(prompt),
        "normalizer_version": SPATIAL_NORMALIZER_VERSION,
        "master": {"digest": _digest(master), "bytes": len(master)},
        "reverse": {"digest": _digest(reverse), "bytes": len(reverse)},
        "started_at": started.isoformat(),
        "elapsed_ms": elapsed_ms,
        "raw_response": {"digest": _digest(raw), "bytes": len(raw)},
    }
    try:
        parsed = parse_spatial_response(raw)
        evidence["parse"] = "PASS"
    except SpatialNormalizationError as exc:
        evidence["parse"] = f"FAIL: {exc}"
        evidence["result"] = "FAIL"
        return evidence
    try:
        candidate = normalize_spatial_candidate(
            parsed,
            overlap_analysis=None,
            sources={
                MASTER_SOURCE_REF: SpatialSourceIdentity(source_digest=_digest(master), view="MASTER"),
                REVERSE_SOURCE_REF: SpatialSourceIdentity(source_digest=_digest(reverse), view="REVERSE"),
            },
            execution_id="live-smoke",
            normalizer_version=SPATIAL_NORMALIZER_VERSION,
        )
    except SpatialNormalizationError as exc:
        evidence["normalize"] = f"FAIL: {exc}"
        evidence["result"] = "FAIL"
        return evidence
    classes: dict[str, int] = {}
    for assertion in candidate.spatial.assertions:
        classes[assertion.evidence_class.value] = classes.get(assertion.evidence_class.value, 0) + 1
    evidence["normalize"] = "PASS"
    evidence["assertions_by_class"] = dict(sorted(classes.items()))
    evidence["result"] = "PASS"
    return evidence


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--master", required=True, help="PNG of the MASTER view")
    parser.add_argument("--reverse", required=True, help="PNG of the REVERSE view")
    parser.add_argument("--scene", required=True, help="scene name, 1-120 characters")
    parser.add_argument("--model", required=True, help="Gemini model that accepts images")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="directory for the evidence JSON")
    args = parser.parse_args(argv)
    if not 1 <= len(args.scene.strip()) <= 120:
        parser.error("--scene must be 1-120 characters")
    model, base_url = gemini_model(args.model)
    evidence = asyncio.run(
        run(
            master=Path(args.master).read_bytes(),
            reverse=Path(args.reverse).read_bytes(),
            scene=args.scene,
            model_name=args.model,
            model=model,
            submitted_base_url=base_url,
        )
    )
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = Path(args.out) / f"R2_M8C_SPATIAL_LIVE_SMOKE_{stamp}.json"
    out.write_text(json.dumps(evidence, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"result": evidence["result"], "evidence": str(out)}))
    return 0 if evidence["result"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())

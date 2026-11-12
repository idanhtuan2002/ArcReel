"""Bake-off of image-to-video engines on the same shots (cloud trial, research 2026-11-13).

Running this command is the operator's authorization for the paid calls it lists. Every shot of the plan goes through
every engine with the same start frame, prompt, duration and aspect ratio, through the normal backend assembly and
the usage ledger (project ``__bakeoff__``), so each call's cost is recorded. Outputs land in
``<out>/<engine>/<shot>.mp4`` and ``<out>/results.json`` lists every call with its seconds, cost and error. A failed
call is recorded and the run goes on. ``--dry-run`` prints the plan and the ledger's price estimate and calls nothing.

Plan file::

    {"aspect_ratio": "9:16",
     "shots": [{"id": "closeup", "prompt": "...", "start_image": "frames/closeup.png", "duration": 5}],
     "engines": [{"provider": "ark", "model": "doubao-seedance-2-0-mini-260615", "resolution": "720p"},
                 {"provider": "gemini-aistudio", "model": "veo-3.1-lite-generate-001"}]}

Paths in the plan are relative to the plan file. In a release deployment (``ARCREEL_RELEASE_MODE``) the backend
assembly refuses every route whose adapter profile is not verified; run the bake-off with the release mode unset.

    uv run python -m scripts.r2.bakeoff_video_engines --plan bakeoff/plan.json --out bakeoff/run1 --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Any

from lib.backend_assembly import assemble_backend
from lib.config.resolver import ConfigResolver
from lib.cost_calculator import CostCalculator
from lib.db import async_session_factory
from lib.ledger import Ledger
from lib.pricing.strategies import PricingParams

BAKEOFF_PROJECT = "__bakeoff__"


def load_plan(path: Path) -> dict[str, Any]:
    plan = json.loads(path.read_text(encoding="utf-8"))
    ids = [shot["id"] for shot in plan["shots"]]
    if len(set(ids)) != len(ids) or not ids:
        raise SystemExit("plan shots need unique ids")
    if not plan.get("engines"):
        raise SystemExit("plan needs at least one engine")
    for shot in plan["shots"]:
        image = path.parent / shot["start_image"]
        if not image.is_file():
            raise SystemExit(f"start image missing: {image}")
        shot["start_image_path"] = image
    return plan


def engine_key(engine: dict[str, Any]) -> str:
    resolution = engine.get("resolution")
    return f"{engine['provider']}__{engine['model']}" + (f"__{resolution}" if resolution else "")


def estimate(plan: dict[str, Any], calculator: CostCalculator | None = None) -> list[dict[str, Any]]:
    """The ledger's estimate per engine for the whole plan (0 where the registry has no price)."""
    calculator = calculator or CostCalculator()
    rows = []
    for engine in plan["engines"]:
        total, currency = 0.0, "USD"
        for shot in plan["shots"]:
            try:
                amount, currency = calculator.calculate_cost(
                    engine["provider"],
                    PricingParams(
                        call_type="video",
                        model=engine["model"],
                        resolution=engine.get("resolution"),
                        aspect_ratio=plan.get("aspect_ratio", "9:16"),
                        duration_seconds=int(shot.get("duration", 5)),
                        generate_audio=bool(engine.get("generate_audio", False)),
                    ),
                    estimate_only=True,
                )
            except (KeyError, ValueError):
                amount = 0.0
            total += amount
        rows.append({"engine": engine_key(engine), "estimate": round(total, 4), "currency": currency})
    return rows


async def run(plan: dict[str, Any], out: Path, *, session_factory=async_session_factory) -> list[dict[str, Any]]:
    from lib.video_backends.base import VideoGenerationRequest

    resolver = ConfigResolver(session_factory)
    ledger = Ledger(session_factory=session_factory)
    results: list[dict[str, Any]] = []
    for engine in plan["engines"]:
        key = engine_key(engine)
        try:
            backend = await assemble_backend(
                provider_id=engine["provider"], media_type="video", model_id=engine["model"], resolver=resolver
            )
        except Exception as error:
            results += [{"engine": key, "shot": s["id"], "error": f"assemble: {error}"} for s in plan["shots"]]
            continue
        for shot in plan["shots"]:
            target = out / key / f"{shot['id']}.mp4"
            target.parent.mkdir(parents=True, exist_ok=True)
            duration = int(shot.get("duration", 5))
            row: dict[str, Any] = {"engine": key, "shot": shot["id"], "duration": duration}
            started = time.monotonic()
            try:
                async with ledger.record(
                    project_name=BAKEOFF_PROJECT,
                    call_type="video",
                    model=engine["model"],
                    provider=engine["provider"],
                    prompt=shot["prompt"],
                    resolution=engine.get("resolution"),
                    duration_seconds=duration,
                    aspect_ratio=plan.get("aspect_ratio", "9:16"),
                    generate_audio=bool(engine.get("generate_audio", False)),
                ) as call:
                    result = await backend.generate(
                        VideoGenerationRequest(
                            prompt=shot["prompt"],
                            output_path=target,
                            aspect_ratio=plan.get("aspect_ratio", "9:16"),
                            duration_seconds=duration,
                            resolution=engine.get("resolution"),
                            start_image=shot["start_image_path"],
                            generate_audio=bool(engine.get("generate_audio", False)),
                        )
                    )
                    call.success(result)
                row.update(output=str(target.relative_to(out)), call_id=call.call_id)
            except Exception as error:
                row["error"] = f"{type(error).__name__}: {error}"[:500]
            row["wall_seconds"] = round(time.monotonic() - started, 1)
            results.append(row)
            (out / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--dry-run", action="store_true", help="print the plan and estimates; call nothing")
    args = parser.parse_args()
    plan = load_plan(args.plan)
    estimates = estimate(plan)
    print(json.dumps({"shots": [s["id"] for s in plan["shots"]], "estimates": estimates}, indent=2))
    if args.dry_run:
        return 0
    args.out.mkdir(parents=True, exist_ok=True)
    results = asyncio.run(run(plan, args.out))
    failed = sum(1 for row in results if "error" in row)
    print(json.dumps({"calls": len(results), "failed": failed, "results": str(args.out / "results.json")}))
    return 0 if failed < len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

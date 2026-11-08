"""Qualify the ranking image judge on a storyboard-pair corpus (``build_image_judge_corpus.py``).

Each storyboard of every pair is scored alone through the production judge question and image view. The evidence JSON
names the model identity, the judge prompt digest, the corpus digest and every answer, and is ``qualified`` only
under ``qualify_judge``'s rule. A launch profile pins that file by path and sha256 (``image_selection``). Exit 0 only
when the judge qualifies.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from lib.db import async_session_factory
from r2.contracts.automation import ModelRoute
from server.production_run.image_judge import (
    JUDGE_METHODS,
    YES_PROBABILITY,
    ImageJudge,
    OllamaImageJudge,
    judge_prompt_digest,
    judge_view,
    qualify_judge,
)
from server.production_run.vision_chat import model_access


async def _main(args: argparse.Namespace) -> int:
    manifest = json.loads((args.corpus / "pairs.json").read_text(encoding="utf-8"))
    pairs = []
    for pair in manifest["pairs"]:
        own, other = (args.corpus / pair["own"]).read_bytes(), (args.corpus / pair["other"]).read_bytes()
        for data, recorded in ((own, pair["own_sha256"]), (other, pair["other_sha256"])):
            if "sha256:" + hashlib.sha256(data).hexdigest() != recorded:
                raise SystemExit(f"corpus image changed: {pair['pair_id']}")
        pairs.append(
            {"pair_id": pair["pair_id"], "line": pair["line"], "own": judge_view(own), "other": judge_view(other)}
        )
    route = ModelRoute.model_validate(
        {
            "role": "reviewer_a",
            "provider_id": args.provider or "qualification",
            "model_id": args.model,
            "model_identity": args.model_identity,
            "config_digest": "sha256:" + "0" * 64,
            "local": not args.provider,
            "paid": bool(args.provider),
            "currency": "USD",
            "max_cost_per_call": None,
        }
    )

    if args.provider:
        # The provider's endpoint decides the API (Ollama, OpenAI-compatible or Gemini) and its stored key is used.
        judge: ImageJudge = ImageJudge(access_for=model_access(async_session_factory))
    else:

        async def base_url(_provider: str) -> str:
            return args.base_url

        judge = OllamaImageJudge(base_url_for=base_url)
    async with judge.scorer(route, method=args.method) as score:
        report = await qualify_judge(score, pairs)
    evidence = {
        "schema": "r2.image-judge-qualification.v1",
        "recorded_at": datetime.now(UTC).isoformat(),
        "model_identity": args.model_identity,
        "method": args.method,
        "prompt_digest": judge_prompt_digest(args.method),
        "corpus_digest": manifest["corpus_digest"],
        **report,
    }
    args.out.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: evidence[k] for k in ("pairs", "wrong", "qualified", "prompt_digest")}))
    return 0 if report["qualified"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", required=True, type=Path, help="directory holding pairs.json and its images")
    parser.add_argument("--base-url", default="http://localhost:11434", help="an Ollama, when --provider is not given")
    parser.add_argument("--provider", help="a configured provider id (custom-<n>, gemini-aistudio, openai)")
    parser.add_argument("--method", choices=JUDGE_METHODS, default=YES_PROBABILITY)
    parser.add_argument("--model", default="qwen2.5vl:7b")
    parser.add_argument("--model-identity", required=True, help="the judging reviewer route's exact model identity")
    parser.add_argument("--out", required=True, type=Path, help="evidence JSON to write")
    return asyncio.run(_main(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())

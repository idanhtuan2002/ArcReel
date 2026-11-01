"""Qualify one reviewer route against a labeled calibration and hold-out corpus of finals.

The corpus manifest lists cases: ``{"case_id", "split": "CALIBRATION"|"HOLDOUT", "label": "CLEAN"|"CRITICAL_DEFECT",
"final": path, "subtitles": path, "narration": path}``. Labels never reach the reviewer: it sees only the final,
its subtitles and narration, exactly as in production. A case is accepted when the review completed and accepts
the final. Each review is written as a receipt beside the output and named by its digest; the resulting
``ReviewerQualification`` is printed, and recorded only with ``--record``. The rule (``reviewer_is_qualified``)
needs at least 10 clean and 10 critical-defect cases per split, no accepted defect and ≥80 % accepted clean.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path

from lib.db import async_session_factory
from lib.db.repositories.reviewer_qualifications import ReviewerQualificationRepository
from r2.automation.profiles import reviewer_is_qualified
from r2.contracts.automation import ModelRoute, QualificationCase, ReviewerQualification
from server.production_run.evaluators import FinalEvidence, OllamaReviewer, QualifiedEvaluator, prompt_digest


def _digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _evidence(corpus: Path, output: Path) -> list[tuple[dict, FinalEvidence]]:
    manifest = json.loads(corpus.read_text(encoding="utf-8"))
    root = corpus.parent
    output.mkdir(parents=True, exist_ok=True)
    prepared = []
    for case in manifest["cases"]:
        final = root / case["final"]
        prepared.append(
            (
                case,
                FinalEvidence(
                    unit_key=f"case:{case['case_id']}",
                    final_path=final,
                    subtitle_path=root / case["subtitles"],
                    narration_text=(root / case["narration"]).read_text(encoding="utf-8"),
                    subject_digest=_digest(final),
                ),
            )
        )
    return prepared


def _receipt(output: Path, name: str, body: str) -> tuple[str, str]:
    receipt = output / name
    receipt.write_text(body, encoding="utf-8")
    return receipt.name, _digest(receipt)


async def qualify(
    *,
    corpus: Path,
    route: ModelRoute,
    evaluator: QualifiedEvaluator,
    output: Path,
    profile_digest: str,
    launch_profile_id: str,
    language: str,
) -> ReviewerQualification:
    cases = []
    for case, evidence in _evidence(corpus, output):
        review = await evaluator.assess(route=route, evidence=evidence)
        name, digest = _receipt(
            output, f"{case['case_id']}.{route.model_identity.replace('/', '_')}.json", review.model_dump_json()
        )
        cases.append(
            QualificationCase(
                split=case["split"],
                label=case["label"],
                accepted=review.outcome == "COMPLETED" and review.accepts(),
                case_digest=evidence.subject_digest,
                receipt_ref=name,
                receipt_digest=digest,
            )
        )
    return ReviewerQualification(
        profile_digest=profile_digest,
        launch_profile_id=launch_profile_id,
        language=language,
        provider_id=route.provider_id,
        model_id=route.model_id,
        model_identity=route.model_identity,
        config_digest=route.config_digest,
        prompt_digest=prompt_digest(),
        cases=tuple(cases),
    )


def _route(path: str) -> ModelRoute:
    return ModelRoute.model_validate_json(Path(path).read_text(encoding="utf-8"))


async def _main(args: argparse.Namespace) -> int:
    route = _route(args.route)
    record = await qualify(
        corpus=Path(args.corpus),
        route=route,
        evaluator=OllamaReviewer(base_url_for={route.provider_id: args.base_url}),
        output=Path(args.output),
        profile_digest=args.profile_digest,
        launch_profile_id=args.launch_profile_id,
        language=args.language,
    )
    qualified = reviewer_is_qualified(record)
    print(json.dumps({"qualified": qualified, "record": record.model_dump(mode="json")}, ensure_ascii=False, indent=2))
    if args.record and qualified:
        async with async_session_factory() as session, session.begin():
            await ReviewerQualificationRepository(session).record(record)
    return 0 if qualified else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", required=True, help="corpus manifest JSON")
    parser.add_argument("--route", required=True, help="the policy's reviewer ModelRoute as JSON")
    parser.add_argument("--base-url", required=True, help="the reviewer's Ollama base URL")
    parser.add_argument("--output", required=True, help="directory for review receipts")
    parser.add_argument("--profile-digest", required=True)
    parser.add_argument("--launch-profile-id", default="fiction_narration_vi_v1")
    parser.add_argument("--language", default="vi")
    parser.add_argument("--record", action="store_true", help="store a qualifying record")
    return asyncio.run(_main(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())

"""Qualify one reviewer route against a labeled calibration and hold-out corpus of finals.

The corpus manifest lists cases: ``{"case_id", "split": "CALIBRATION"|"HOLDOUT", "label": "CLEAN"|"CRITICAL_DEFECT",
"final": path, "subtitles": path, "narration": path}``. Labels never reach the reviewer: it sees only the final,
its subtitles and narration, exactly as in production. A case is accepted when the review completed and accepts
the final. Each review is written as a receipt beside the output and named by its digest; the resulting
``ReviewerQualification`` is printed, and recorded only with ``--record``. With ``--project`` and ``--role`` the route,
its provider base URL and the profile digest are read from the project's automation settings exactly as a run would
resolve them; ``--route``/``--base-url``/``--profile-digest`` give them explicitly instead. The rule (``reviewer_is_qualified``)
needs at least 10 clean and 10 critical-defect cases per split, no accepted defect and ≥80 % accepted clean. A
case is identified by its whole evidence (final, subtitles and narration), so a defect that changes only the
subtitles of a clean final is a distinct case.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path

from lib.config.resolver import ConfigResolver
from lib.db import async_session_factory
from lib.db.repositories.reviewer_qualifications import ReviewerQualificationRepository
from lib.project_manager import get_project_manager
from r2.automation.assessment import ModelAssessment
from r2.automation.profiles import reviewer_is_qualified
from r2.contracts.automation import ModelRoute, QualificationCase, ReviewerQualification
from server.production_run.composition import ProjectPolicyResolver
from server.production_run.evaluators import (
    FinalEvidence,
    OllamaReviewer,
    QualifiedEvaluator,
    evidence_digest,
    prompt_digest,
    provider_base_url,
    review_method,
)


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


def _reusable_review(
    receipt: Path, *, route: ModelRoute, evidence: FinalEvidence, method_digest: str
) -> ModelAssessment | None:
    """A review stored by an earlier qualification of the same model, review method and case evidence; such a review
    is the answer this reviewer gives (reviews run at temperature 0), so it is not asked again."""
    if not receipt.is_file():
        return None
    try:
        review = ModelAssessment.model_validate_json(receipt.read_text(encoding="utf-8"))
    except ValueError:
        return None
    if (review.model_identity, review.prompt_digest, review.evidence_digest) != (
        route.model_identity,
        method_digest,
        evidence_digest(evidence),
    ):
        return None
    return review


def cannot_qualify(cases: list[QualificationCase], clean_totals: dict[str, int]) -> bool:
    """True once the answers so far already break the rule: an accepted defect, or too many rejected clean cases."""
    for case in cases:
        if case.label == "CRITICAL_DEFECT" and case.accepted:
            return True
    for split, total in clean_totals.items():
        rejected = sum(1 for c in cases if c.split == split and c.label == "CLEAN" and not c.accepted)
        if (total - rejected) * 5 < total * 4:
            return True
    return False


async def qualify(
    *,
    corpus: Path,
    route: ModelRoute,
    evaluator: QualifiedEvaluator,
    output: Path,
    profile_digest: str,
    launch_profile_id: str,
    language: str,
    stop_early: bool = False,
) -> ReviewerQualification:
    """The reviewer's record over the corpus; with ``stop_early`` it ends at the first answer that rules it out."""
    cases: list[QualificationCase] = []
    method_digest = prompt_digest(review_method(route))
    prepared = _evidence(corpus, output)
    clean_totals: dict[str, int] = {}
    for case, _ in prepared:
        if case["label"] == "CLEAN":
            clean_totals[case["split"]] = clean_totals.get(case["split"], 0) + 1
    for case, evidence in prepared:
        if stop_early and cannot_qualify(cases, clean_totals):
            break
        receipt_name = f"{case['case_id']}.{route.model_identity.replace('/', '_')}.json"
        review = _reusable_review(output / receipt_name, route=route, evidence=evidence, method_digest=method_digest)
        if review is None:
            review = await evaluator.assess(route=route, evidence=evidence)
        name, digest = _receipt(output, receipt_name, review.model_dump_json())
        cases.append(
            QualificationCase(
                split=case["split"],
                label=case["label"],
                accepted=review.outcome == "COMPLETED" and review.accepts(),
                case_digest=evidence_digest(evidence),
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
        prompt_digest=method_digest,
        cases=tuple(cases),
    )


def _fixed(url: str):
    async def base_url(_provider_id: str) -> str:
        return url

    return base_url


def _route(path: str) -> ModelRoute:
    return ModelRoute.model_validate_json(Path(path).read_text(encoding="utf-8"))


async def project_route(project: str, role: str) -> tuple[ModelRoute, str]:
    """The project's ``role`` route as a run would freeze it, and the profile digest its automation settings name."""
    projects = get_project_manager()
    policies = ProjectPolicyResolver(
        async_session_factory, projects=projects, resolver=ConfigResolver(async_session_factory)
    )
    routes = [route for route in await policies.routes(project) if route.role == role]
    if len(routes) != 1:
        raise SystemExit(f"project {project!r} declares {len(routes)} {role} routes")
    digest = projects.load_project(project)["automation"]["profile_digest"]
    return routes[0], digest


async def _main(args: argparse.Namespace) -> int:
    if args.project:
        route, profile_digest = await project_route(args.project, args.role)
    else:
        if not (args.route and args.base_url and args.profile_digest):
            raise SystemExit("give --project and --role, or --route, --base-url and --profile-digest")
        route, profile_digest = _route(args.route), args.profile_digest
    base_url_for = _fixed(args.base_url) if args.base_url else provider_base_url(async_session_factory)
    record = await qualify(
        corpus=Path(args.corpus),
        route=route,
        evaluator=OllamaReviewer(base_url_for=base_url_for),
        output=Path(args.output),
        profile_digest=profile_digest,
        launch_profile_id=args.launch_profile_id,
        language=args.language,
        stop_early=args.stop_early,
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
    parser.add_argument("--project", help="read the route and profile digest from this project's automation settings")
    parser.add_argument("--role", choices=("reviewer_a", "reviewer_b"), default="reviewer_a")
    parser.add_argument("--route", help="the policy's reviewer ModelRoute as JSON")
    parser.add_argument("--base-url", help="the reviewer's Ollama base URL (default: its custom provider's)")
    parser.add_argument("--output", required=True, help="directory for review receipts")
    parser.add_argument("--profile-digest")
    parser.add_argument("--launch-profile-id", default="fiction_narration_vi_v1")
    parser.add_argument("--language", default="vi")
    parser.add_argument("--record", action="store_true", help="store a qualifying record")
    parser.add_argument("--stop-early", action="store_true", help="stop at the first answer that rules the route out")
    return asyncio.run(_main(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())

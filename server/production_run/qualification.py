"""Reviewer and launch qualification of automatic production, shared by the CLIs and the host's API.

A reviewer route is qualified against a labeled calibration and hold-out corpus of finals: labels never reach the
reviewer, each review is a receipt beside the output named by its digest, a stored review of the same model, review
method and case evidence is reused, and the rule is ``reviewer_is_qualified``. A launch qualification is recorded
only when the real preflight's sole blocking reason is its absence, bound to a host media-route evidence file.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path

from lib.config.resolver import ConfigResolver
from lib.project_manager import ProjectManager
from r2.automation.assessment import ModelAssessment
from r2.contracts.automation import (
    AutomationMode,
    LaunchQualification,
    ModelRoute,
    QualificationCase,
    ReviewerQualification,
)
from server.production_run.composition import HostPreflightReader, ProjectPolicyResolver
from server.production_run.evaluators import (
    FinalEvidence,
    QualifiedEvaluator,
    evidence_digest,
    prompt_digest,
    review_method,
)
from server.production_run.inputs import ProjectInputWitness
from server.production_run.preflight import ProductionPreflight


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
    progress: Callable[[int, int], None] | None = None,
) -> ReviewerQualification:
    """The reviewer's record over the corpus; with ``stop_early`` it ends at the first answer that rules it out.
    ``progress`` is told the cases reviewed so far and the corpus size after every case."""
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
        if progress is not None:
            progress(len(cases), len(prepared))
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


ONLY_MISSING = ("LAUNCH_PROFILE_NOT_QUALIFIED",)


def evidence_receipt(path: Path) -> tuple[str, str]:
    """The evidence file's name and digest; it must be a JSON document."""
    raw = path.read_bytes()
    json.loads(raw)
    return path.name, "sha256:" + hashlib.sha256(raw).hexdigest()


async def build_record(
    sessions, *, projects: ProjectManager, user_id: str, project_name: str, evidence: Path
) -> tuple[LaunchQualification | None, tuple[str, ...]]:
    """The record to store, or ``None`` with the preflight's blocking reasons when anything besides it is missing."""
    policies = ProjectPolicyResolver(sessions, projects=projects, resolver=ConfigResolver(sessions))
    policy = await policies.resolve(user_id=user_id, project_name=project_name, mode=AutomationMode.AUTO)
    reader = HostPreflightReader(
        sessions,
        projects=projects,
        policies=policies,
        witness=ProjectInputWitness(sessions, projects=projects),
    )
    report = await ProductionPreflight(reader).check(user_id=user_id, project_name=project_name, policy=policy)
    if report.blocking_reasons != ONLY_MISSING:
        return None, report.blocking_reasons
    settings = projects.load_project(project_name)["automation"]
    receipt_ref, digest = evidence_receipt(evidence)
    return (
        LaunchQualification(
            owner="launch-qualification",
            receipt_ref=receipt_ref,
            digest=digest,
            user_id=user_id,
            project_name=project_name,
            launch_profile_id=policy.launch_profile_id,
            profile_digest=policy.profile_digest,
            route_digests=report.route_digests,
            required_disk_bytes=int(settings["required_disk_bytes"]),
            required_gpu_bytes=int(settings["required_gpu_bytes"]),
        ),
        (),
    )


__all__ = ["ONLY_MISSING", "build_record", "cannot_qualify", "evidence_receipt", "qualify"]

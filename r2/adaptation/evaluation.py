"""``ProfileEvaluationService`` — the only public entry point that runs a pure M6
profile evaluator against a stored screenplay proposal and records its immutable
evidence (plan Task 11).

``evaluate`` always resolves its exact screenplay and profile pack before running any
evaluator (attempt-before-work): a stale ``artifact_ref``/``profile_ref`` fails closed
with no evaluator call and no write. The evaluator itself is a pure function of
(screenplay content, resolved ``ProfilePack``) — deterministic and provider-neutral —
so a report is content-addressed by its own ``report_digest``
(``compute_profile_evaluation_report_digest``): re-evaluating byte-identical content
under the same profile is an exact retry that performs no new write, and there is no
tuple-mismatch case to detect for the report row itself (a colliding digest can only
carry identical content). The sidecar it produces
(``WesternDramaAnalysis``/``ShuangwenAnalysis``) is stored separately, addressed by a
deterministic ``sidecar_id`` (``f"{artifact_id}:{profile_id}"``) at the evaluated
artifact's own version — a real identity conflict there (same id/version, different
content) means the evaluator regressed, not that different evidence coexists. Both
writes happen in the same transaction as one atomic bundle; an evaluator failure (a
raised error) leaves no partial sidecar or report row.
"""

from __future__ import annotations

from datetime import UTC, datetime

from r2.adaptation.errors import (
    AdaptationIdentityConflictError,
    AdaptationNotFoundError,
    AdaptationStaleDependencyError,
)
from r2.adaptation.hashing import compute_profile_evaluation_report_digest, compute_profile_sidecar_id
from r2.adaptation.ports import AdaptationUnitOfWorkFactory
from r2.adaptation.profiles import ProfilePackRegistry
from r2.adaptation.shuangwen_profile import ShuangwenSourceScope, evaluate_shuangwen
from r2.adaptation.western_profile import evaluate_western
from r2.contracts.adaptation import (
    AdaptationProfileId,
    AdaptationProfileRef,
    ArtifactVersionRef,
    DecisionRef,
    ProfileEvaluationReport,
    ProfileFinding,
    ShuangwenAnalysis,
    WesternDramaAnalysis,
)


def _sidecar_findings(sidecar: WesternDramaAnalysis | ShuangwenAnalysis) -> list[ProfileFinding]:
    if isinstance(sidecar, WesternDramaAnalysis):
        return list(sidecar.format_findings)
    return list(sidecar.findings)


def report_ref_of(report: ProfileEvaluationReport) -> DecisionRef:
    """The ``DecisionRef`` a ``ProfileWaiverCommand.report_ref`` or a
    ``MapApprovalCommand.relied_report_refs`` entry names this report by. A report has
    no separate opaque id — it is content-addressed by its own ``report_digest`` — so
    both ``DecisionRef`` fields carry that same value, the same generic shape real
    authority decisions use."""
    return DecisionRef(decision_id=report.report_digest, decision_digest=report.report_digest)


class ProfileEvaluationService:
    def __init__(
        self, uow_factory: AdaptationUnitOfWorkFactory, *, registry: ProfilePackRegistry | None = None
    ) -> None:
        self._uow_factory = uow_factory
        self._registry = registry or ProfilePackRegistry()

    async def evaluate(
        self,
        *,
        artifact_ref: ArtifactVersionRef,
        profile_ref: AdaptationProfileRef,
        user_id: str,
        project_name: str,
        source_scope: ShuangwenSourceScope | None = None,
    ) -> ProfileEvaluationReport:
        """Evaluate the exact screenplay named by ``artifact_ref`` against the exact
        profile pack named by ``profile_ref``, and record the immutable report (plus
        its sidecar) if this exact content has never been recorded before.

        ``source_scope`` is required for ``CN_SHORT_DRAMA_SHUANGWEN`` and forbidden for
        ``WESTERN_GENERIC`` — each profile's own evaluator has a different signature,
        and this method never guesses which one the caller meant to satisfy.
        """
        async with self._uow_factory() as uow:
            repo = uow.repository

            screenplay = await repo.get_exact_screenplay(
                screenplay_id=artifact_ref.artifact_id,
                version=artifact_ref.version,
                project_name=project_name,
                user_id=user_id,
            )
            if screenplay is None:
                raise AdaptationNotFoundError(
                    f"screenplay {artifact_ref.artifact_id!r} v{artifact_ref.version} does not resolve in this scope"
                )
            if screenplay.content_hash != artifact_ref.content_hash:
                raise AdaptationStaleDependencyError(
                    f"evaluation command declares content hash {artifact_ref.content_hash!r} for screenplay "
                    f"{artifact_ref.artifact_id!r} v{artifact_ref.version}, but the stored hash is "
                    f"{screenplay.content_hash!r}"
                )

            # ``ProfilePackRegistry.resolve`` raises AdaptationNotFoundError /
            # AdaptationPolicyDigestMismatchError / AdaptationPolicyPackIntegrityError
            # for an unknown, stale, or structurally invalid policy pack — fail closed,
            # no evaluator call, no write.
            profile_pack = self._registry.resolve(profile_ref)

            if profile_pack.ref.profile_id == AdaptationProfileId.WESTERN_GENERIC:
                if source_scope is not None:
                    raise ValueError("source_scope must be omitted for the WESTERN_GENERIC profile")
                sidecar: WesternDramaAnalysis | ShuangwenAnalysis = evaluate_western(
                    screenplay, profile_pack=profile_pack
                )
            else:
                if source_scope is None:
                    raise ValueError("source_scope is required for the CN_SHORT_DRAMA_SHUANGWEN profile")
                sidecar = evaluate_shuangwen(screenplay, source_scope=source_scope, profile_pack=profile_pack)

            sidecar_id = compute_profile_sidecar_id(artifact_ref.artifact_id, profile_pack.ref)
            sidecar_ref = ArtifactVersionRef(
                artifact_id=sidecar_id, version=artifact_ref.version, content_hash=sidecar.content_hash
            )

            draft = ProfileEvaluationReport(
                schema_version="r2-profile-evaluation-report-v1",
                artifact_hash=artifact_ref.content_hash,
                profile_ref=profile_pack.ref,
                evaluator_version=profile_pack.evaluator_version,
                sidecar_ref=sidecar_ref,
                sidecar_digest=sidecar.content_hash,
                findings=_sidecar_findings(sidecar),
                report_digest="pending",
                created_at=datetime.now(UTC),
            )
            report_digest = compute_profile_evaluation_report_digest(draft)
            report = draft.model_copy(update={"report_digest": report_digest})

            existing_report = await repo.get_exact_report(
                report_digest=report_digest, project_name=project_name, user_id=user_id
            )
            if existing_report is not None:
                await uow.commit()
                return existing_report

            existing_sidecar = await repo.get_exact_sidecar(
                sidecar_id=sidecar_id, version=artifact_ref.version, project_name=project_name, user_id=user_id
            )
            if existing_sidecar is None:
                await repo.insert_sidecar(
                    sidecar_id, artifact_ref.version, sidecar, user_id=user_id, project_name=project_name
                )
            elif existing_sidecar != sidecar:
                raise AdaptationIdentityConflictError(
                    f"profile sidecar {sidecar_id!r} v{artifact_ref.version} was already recorded with a "
                    "different tuple"
                )

            await repo.insert_report(report, user_id=user_id, project_name=project_name)
            await uow.commit()
            return report

    async def get_exact_report(
        self, *, report_digest: str, project_name: str, user_id: str
    ) -> ProfileEvaluationReport | None:
        async with self._uow_factory() as uow:
            return await uow.repository.get_exact_report(
                report_digest=report_digest, project_name=project_name, user_id=user_id
            )


__all__ = ["ProfileEvaluationService", "report_ref_of"]

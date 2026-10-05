"""``ApprovedScreenplayReader`` — the sole read surface Director (Task 13) uses to
resolve an admitted screenplay for direction (plan Task 12).

Reads only the append-only ``adaptation_screenplays``/``adaptation_screenplay_admissions``
projection ``AdaptationAuthorityService.admit_screenplay_for_direction`` writes; exposes
no mutation method and no authority surface. ``get_exact_admitted`` requires both the
exact screenplay version and the exact admission decision that selected it — a
screenplay row alone is never sufficient proof that it is currently admitted, since a
screenplay's own ``approval_status``/``locked_for_direction`` fields could in principle
be forged by any caller building a ``ScreenplayArtifactV2`` by hand; only the admission
projection row is authoritative for "this exact version was actually admitted by this
exact decision."
"""

from __future__ import annotations

from r2.adaptation.authority_kernel import require_head_matches_fold
from r2.adaptation.errors import AdaptationNotFoundError
from r2.adaptation.ports import AdaptationRepositoryPort, AdaptationUnitOfWorkFactory
from r2.contracts.adaptation import (
    AdaptationAuthorityFamily,
    AdaptationProfileRef,
    AdmittedScreenplayRef,
    ArtifactVersionRef,
    DecisionRef,
    ScreenplayArtifactV2,
)


async def resolve_exact_admitted(
    repository: AdaptationRepositoryPort,
    *,
    user_id: str,
    project_name: str,
    screenplay_ref: ArtifactVersionRef,
    admission_ref: DecisionRef,
    expected_profile_ref: AdaptationProfileRef | None = None,
) -> ScreenplayArtifactV2:
    admission = await repository.get_exact_screenplay_admission(
        screenplay_id=screenplay_ref.artifact_id,
        version=screenplay_ref.version,
        project_name=project_name,
        user_id=user_id,
    )
    if admission is None:
        raise AdaptationNotFoundError(
            f"screenplay {screenplay_ref.artifact_id!r} v{screenplay_ref.version} has no admission record"
        )
    if admission.screenplay_ref != screenplay_ref or admission.admission_ref != admission_ref:
        raise AdaptationNotFoundError(
            f"screenplay {screenplay_ref.artifact_id!r} v{screenplay_ref.version}'s admission record does "
            "not match the exact screenplay/admission refs requested"
        )
    if expected_profile_ref is not None and admission.profile_ref != expected_profile_ref:
        raise AdaptationNotFoundError(
            f"screenplay {screenplay_ref.artifact_id!r} v{screenplay_ref.version}'s admission record does "
            "not match the exact profile ref requested"
        )

    head = await repository.prepare_or_lock_head(
        user_id=user_id,
        project_name=project_name,
        family=AdaptationAuthorityFamily.SCREENPLAY_ADMISSION,
        head_key=screenplay_ref.artifact_id,
    )
    if head is None:
        raise AdaptationNotFoundError(f"screenplay {screenplay_ref.artifact_id!r} has no current admission authority")
    decisions = await repository.list_decisions_for_locked_head(
        user_id=user_id,
        project_name=project_name,
        family=AdaptationAuthorityFamily.SCREENPLAY_ADMISSION,
        head_key=screenplay_ref.artifact_id,
    )
    require_head_matches_fold(decisions, head)
    if head.effective_decision_id != admission_ref.decision_id or head.selected_artifact_ref != screenplay_ref:
        raise AdaptationNotFoundError(
            f"screenplay {screenplay_ref.artifact_id!r} v{screenplay_ref.version} is not the current "
            "effective admission selection"
        )

    screenplay = await repository.get_exact_screenplay(
        screenplay_id=screenplay_ref.artifact_id,
        version=screenplay_ref.version,
        project_name=project_name,
        user_id=user_id,
    )
    if screenplay is None or screenplay.content_hash != screenplay_ref.content_hash:
        raise AdaptationNotFoundError(
            f"screenplay {screenplay_ref.artifact_id!r} v{screenplay_ref.version} does not resolve to the "
            "exact content its admission record names"
        )
    return screenplay


class ApprovedScreenplayReader:
    def __init__(self, uow_factory: AdaptationUnitOfWorkFactory) -> None:
        self._uow_factory = uow_factory

    async def get_exact_admitted(
        self,
        *,
        user_id: str,
        project_name: str,
        screenplay_ref: ArtifactVersionRef,
        admission_ref: DecisionRef,
    ) -> ScreenplayArtifactV2:
        async with self._uow_factory() as uow:
            return await resolve_exact_admitted(
                uow.repository,
                user_id=user_id,
                project_name=project_name,
                screenplay_ref=screenplay_ref,
                admission_ref=admission_ref,
            )


class TransactionBoundApprovedScreenplayReader:
    def __init__(self, repository: AdaptationRepositoryPort, *, expected_admission: AdmittedScreenplayRef) -> None:
        self._repository = repository
        self._expected_admission = expected_admission

    async def get_exact_admitted(
        self,
        *,
        user_id: str,
        project_name: str,
        screenplay_ref: ArtifactVersionRef,
        admission_ref: DecisionRef,
    ) -> ScreenplayArtifactV2:
        if (
            screenplay_ref != self._expected_admission.screenplay_ref
            or admission_ref != self._expected_admission.admission_ref
        ):
            raise AdaptationNotFoundError("requested screenplay/admission refs do not match the bound admission")
        return await resolve_exact_admitted(
            self._repository,
            user_id=user_id,
            project_name=project_name,
            screenplay_ref=screenplay_ref,
            admission_ref=admission_ref,
            expected_profile_ref=self._expected_admission.profile_ref,
        )


__all__ = ["ApprovedScreenplayReader", "TransactionBoundApprovedScreenplayReader", "resolve_exact_admitted"]

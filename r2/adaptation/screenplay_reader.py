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

from r2.adaptation.errors import AdaptationNotFoundError
from r2.adaptation.ports import AdaptationUnitOfWorkFactory
from r2.contracts.adaptation import ArtifactVersionRef, DecisionRef, ScreenplayArtifactV2


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
            repo = uow.repository
            admission = await repo.get_exact_screenplay_admission(
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

            screenplay = await repo.get_exact_screenplay(
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


__all__ = ["ApprovedScreenplayReader"]

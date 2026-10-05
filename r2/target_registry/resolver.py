"""Resolve a target-ID consumer through its current upstream admission."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from lib.db.repositories.adaptation import AdaptationRepository
from lib.db.repositories.production_target import (
    ProductionTargetIntegrityError,
    ProductionTargetRepository,
    VerifiedTargetVersion,
)
from r2.adaptation.errors import AdaptationError
from r2.adaptation.screenplay_reader import TransactionBoundApprovedScreenplayReader
from r2.contracts.enums import ProductionBindingTarget


class TransactionBoundTargetAuthorityResolver:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def resolve_current(
        self, *, user_id: str, project_name: str, target_type: ProductionBindingTarget | str, target_id: str
    ) -> VerifiedTargetVersion | None:
        repository = ProductionTargetRepository(self._session)
        hint = await repository.peek_current_admission_hint(
            user_id=user_id, project_name=project_name, target_type=target_type, target_id=target_id
        )
        if hint is None:
            return None
        admission = hint.admitted_screenplay_ref
        reader = TransactionBoundApprovedScreenplayReader(
            AdaptationRepository(self._session), expected_admission=admission
        )
        try:
            await reader.get_exact_admitted(
                user_id=user_id,
                project_name=project_name,
                screenplay_ref=admission.screenplay_ref,
                admission_ref=admission.admission_ref,
            )
        except AdaptationError as exc:
            raise ProductionTargetIntegrityError("target admission hint is stale or invalid") from exc
        current = await repository.get_current_verified(
            user_id=user_id,
            project_name=project_name,
            target_type=target_type,
            target_id=target_id,
            expected_admission=admission,
        )
        if current is None or current.ref != hint.ref or current.admitted_screenplay_ref != admission:
            raise ProductionTargetIntegrityError("target admission hint changed before the locked read")
        return current


__all__ = ["TransactionBoundTargetAuthorityResolver"]

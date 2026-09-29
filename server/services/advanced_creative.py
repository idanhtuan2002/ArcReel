"""Host composition of the M8 exploration services on one database session (ADR-0097).

The services commit the session once per operation. The slot authority promotes through the M7
master authority on the same session with a deferred commit, so M8 and M7 rows land together.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from lib.artifact_manifest import decode_artifact_key_parts
from lib.db.models.host_hardening import MasterAuthorityModel
from lib.db.repositories.advanced_creative import ExplorationRepository
from lib.db.repositories.host_hardening import (
    CandidateObjectRepository,
    MasterAuthorityRepository,
    PromotionReceiptRepository,
)
from r2.advanced_creative.exploration import ExplorationService
from r2.advanced_creative.promotion import ExplorationPromotion
from r2.contracts.host_hardening import MasterHeadSnapshot, VerifiedCandidateObject
from r2.host_hardening.master_authority import MasterAuthorityUnit


def _utc_now() -> datetime:
    return datetime.now(UTC)


async def _deferred_commit() -> None:
    """The M8 service commits the session once, after its own rows are staged."""


class HostSlotAuthority:
    """``SlotAuthority`` over the M7 master authority tables of ``session``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._authorities = MasterAuthorityRepository(session)
        self._candidates = CandidateObjectRepository(session)

    def is_manifest_key(self, target_ref: str) -> bool:
        return decode_artifact_key_parts(target_ref) is not None

    async def current_head(self, *, user_id: str, project_name: str, target_ref: str) -> MasterHeadSnapshot | None:
        return await self._authorities.get_current(user_id=user_id, project_name=project_name, artifact_key=target_ref)

    async def lock_slot(self, *, user_id: str, project_name: str, target_ref: str) -> None:
        """Take the slot's authority row write lock until the transaction ends (a no-op rewrite)."""
        await self._session.execute(
            update(MasterAuthorityModel)
            .where(
                MasterAuthorityModel.user_id == user_id,
                MasterAuthorityModel.project_name == project_name,
                MasterAuthorityModel.artifact_key == target_ref,
            )
            .values(current_version=MasterAuthorityModel.current_version)
        )

    async def candidate_object(
        self, *, user_id: str, project_name: str, candidate_id: str
    ) -> VerifiedCandidateObject | None:
        return await self._candidates.get_exact(user_id=user_id, project_name=project_name, candidate_id=candidate_id)

    async def promote(
        self,
        *,
        user_id: str,
        project_name: str,
        target_ref: str,
        candidate_id: str,
        expected_master_version: int,
        approval_record: str,
        command_id: str,
    ) -> MasterHeadSnapshot:
        unit = MasterAuthorityUnit(
            candidates=self._candidates,
            authorities=self._authorities,
            receipts=PromotionReceiptRepository(self._session),
            commit=_deferred_commit,
            clock=_utc_now,
        )
        return await unit.promote_registered(
            user_id=user_id,
            project_name=project_name,
            artifact_key=target_ref,
            candidate_id=candidate_id,
            expected_master_version=expected_master_version,
            approval_record=approval_record,
            command_id=command_id,
        )


def exploration_service(session: AsyncSession) -> ExplorationService:
    return ExplorationService(
        store=ExplorationRepository(session),
        slots=HostSlotAuthority(session),
        commit=session.commit,
        clock=_utc_now,
    )


def exploration_promotion(session: AsyncSession) -> ExplorationPromotion:
    return ExplorationPromotion(
        store=ExplorationRepository(session),
        slots=HostSlotAuthority(session),
        commit=session.commit,
        clock=_utc_now,
    )


__all__ = ["HostSlotAuthority", "exploration_promotion", "exploration_service"]

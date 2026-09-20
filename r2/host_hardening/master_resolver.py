"""The one authoritative master read (M7-B, H3-H4 design spec section 6).

All authoritative master reads go through this resolver rather than a direct
legacy manifest/version selection. When a legacy compatibility projection is
supplied and it disagrees with the database head, this fails closed with
``MasterDivergedError`` instead of picking either side -- a silent pick could
serve stale or unapproved bytes.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from r2.contracts.host_hardening import MasterHeadSnapshot
from r2.host_hardening.ports import MasterAuthorityPort


class MasterDivergedError(RuntimeError):
    """The database head and the legacy compatibility projection disagree."""


@runtime_checkable
class LegacyMasterProjection(Protocol):
    """Read-only access to whatever the pre-M7-B host authority currently
    believes is selected for an artifact. Returns ``None`` when the legacy
    side has no opinion (e.g. it was never wired for this artifact), which is
    not a divergence -- there is nothing to disagree with yet."""

    async def get_selected_candidate_id(self, *, user_id: str, project_name: str, artifact_key: str) -> str | None: ...


class DatabaseMasterResolver:
    def __init__(
        self, *, authorities: MasterAuthorityPort, legacy_projection: LegacyMasterProjection | None = None
    ) -> None:
        self._authorities = authorities
        self._legacy_projection = legacy_projection

    async def get_exact(self, *, user_id: str, project_name: str, artifact_key: str) -> MasterHeadSnapshot | None:
        current = await self._authorities.get_current(
            user_id=user_id, project_name=project_name, artifact_key=artifact_key
        )
        if self._legacy_projection is not None:
            legacy_candidate_id = await self._legacy_projection.get_selected_candidate_id(
                user_id=user_id, project_name=project_name, artifact_key=artifact_key
            )
            if legacy_candidate_id is not None:
                db_candidate_id = current.candidate_id if current is not None else None
                if legacy_candidate_id != db_candidate_id:
                    raise MasterDivergedError(
                        f"M7_MASTER_DIVERGED: {artifact_key!r} database head is {db_candidate_id!r}, "
                        f"legacy projection is {legacy_candidate_id!r}"
                    )
        return current


__all__ = ["DatabaseMasterResolver", "LegacyMasterProjection", "MasterDivergedError"]

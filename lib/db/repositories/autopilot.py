"""Append-only autopilot delegation versions (ADR-0124)."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from lib.db.models.autopilot import AutopilotDelegationModel
from r2.contracts.autopilot import AutopilotDelegation


class AutopilotIntegrityError(RuntimeError):
    """A stored delegation differs from its recorded columns or digest."""


def _parse(row: AutopilotDelegationModel) -> AutopilotDelegation:
    delegation = AutopilotDelegation.model_validate_json(row.delegation_json)
    if (
        delegation.user_id,
        delegation.project_name,
        delegation.version,
        delegation.state,
        delegation.kind,
        delegation.digest(),
    ) != (row.user_id, row.project_name, row.version, row.state, row.kind, row.delegation_digest):
        raise AutopilotIntegrityError("AUTOPILOT_DELEGATION_INTEGRITY_FAILED")
    return delegation


class AutopilotRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def current(self, user_id: str, project_name: str, *, lock: bool = False) -> AutopilotDelegation | None:
        """The project's latest version; ``lock`` holds its row until the transaction ends."""
        query = (
            select(AutopilotDelegationModel)
            .where(AutopilotDelegationModel.user_id == user_id, AutopilotDelegationModel.project_name == project_name)
            .order_by(AutopilotDelegationModel.version.desc())
            .limit(1)
        )
        if lock:
            query = query.with_for_update().execution_options(populate_existing=True)
        row = (await self.session.execute(query)).scalar_one_or_none()
        return None if row is None else _parse(row)

    async def by_command(self, user_id: str, project_name: str, command_id: str) -> AutopilotDelegation | None:
        """The version a command recorded, whichever version is current now."""
        rows = (
            await self.session.execute(
                select(AutopilotDelegationModel).where(
                    AutopilotDelegationModel.user_id == user_id,
                    AutopilotDelegationModel.project_name == project_name,
                )
            )
        ).scalars()
        return next((d for d in map(_parse, rows) if d.command_id == command_id), None)

    async def append(self, delegation: AutopilotDelegation, *, previous: AutopilotDelegation | None) -> None:
        """Record the next version; a concurrent append of the same version fails on the primary key."""
        if delegation.version != (1 if previous is None else previous.version + 1) or (
            previous is not None
            and (previous.user_id, previous.project_name) != (delegation.user_id, delegation.project_name)
        ):
            raise AutopilotIntegrityError("AUTOPILOT_DELEGATION_VERSION")
        self.session.add(
            AutopilotDelegationModel(
                user_id=delegation.user_id,
                project_name=delegation.project_name,
                version=delegation.version,
                state=delegation.state,
                kind=delegation.kind,
                delegation_digest=delegation.digest(),
                delegation_json=delegation.model_dump_json(),
                created_at=delegation.created_at,
            )
        )
        await self.session.flush()

    async def enabled(self, *, limit: int, after: tuple[str, str] | None = None) -> list[AutopilotDelegation]:
        """Projects whose current version is enabled, in (user, project) order after ``after``."""
        latest = (
            select(
                AutopilotDelegationModel.user_id,
                AutopilotDelegationModel.project_name,
                func.max(AutopilotDelegationModel.version).label("version"),
            )
            .group_by(AutopilotDelegationModel.user_id, AutopilotDelegationModel.project_name)
            .subquery()
        )
        query = (
            select(AutopilotDelegationModel)
            .join(
                latest,
                (AutopilotDelegationModel.user_id == latest.c.user_id)
                & (AutopilotDelegationModel.project_name == latest.c.project_name)
                & (AutopilotDelegationModel.version == latest.c.version),
            )
            .where(AutopilotDelegationModel.state == "ENABLED")
            .order_by(AutopilotDelegationModel.user_id, AutopilotDelegationModel.project_name)
            .limit(limit)
        )
        if after is not None:
            query = query.where(
                (AutopilotDelegationModel.user_id > after[0])
                | ((AutopilotDelegationModel.user_id == after[0]) & (AutopilotDelegationModel.project_name > after[1]))
            )
        return [_parse(row) for row in (await self.session.execute(query)).scalars()]


__all__ = ["AutopilotIntegrityError", "AutopilotRepository"]

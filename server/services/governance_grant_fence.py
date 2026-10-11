"""Cross-process grant-import fence for a future full recovery scan."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_FENCE_NAMESPACE = 0x4D384743
_FENCE_VERSION = 1


class GrantRecoveryFenceUnavailable(RuntimeError):
    """The required transaction-level recovery fence cannot be acquired."""


async def acquire_grant_import_fence(session: AsyncSession) -> None:
    """Hold a shared PostgreSQL fence through the import transaction."""

    if not session.in_transaction():
        raise GrantRecoveryFenceUnavailable("grant import fence requires a transaction")
    dialect = session.get_bind().dialect.name
    if dialect == "sqlite":
        return
    if dialect != "postgresql":
        raise GrantRecoveryFenceUnavailable("grant import fence requires PostgreSQL")
    await session.execute(
        text("SELECT pg_advisory_xact_lock_shared(:namespace, :version)"),
        {"namespace": _FENCE_NAMESPACE, "version": _FENCE_VERSION},
    )


async def acquire_grant_recovery_scan_fence(session: AsyncSession) -> None:
    """Hold an exclusive PostgreSQL fence through scope enumeration and verification."""

    if not session.in_transaction() or session.get_bind().dialect.name != "postgresql":
        raise GrantRecoveryFenceUnavailable("grant recovery fence requires a PostgreSQL transaction")
    await session.execute(
        text("SELECT pg_advisory_xact_lock(:namespace, :version)"),
        {"namespace": _FENCE_NAMESPACE, "version": _FENCE_VERSION},
    )


__all__ = ["GrantRecoveryFenceUnavailable", "acquire_grant_import_fence", "acquire_grant_recovery_scan_fence"]

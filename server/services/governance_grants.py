"""Transaction-bound local ledger for signed Governance Showrunner events."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.models.governance_grant import ShowrunnerGrantEventModel, ShowrunnerGrantHeadModel
from r2.contracts.grant_checkpoint import GrantHeadRecordV1
from r2.contracts.showrunner_grant import WORKSPACE_SCOPE, GrantEventInvalid
from r2.governance.checkpoint_signature import VerifiedGrantCheckpointV1, verify_grant_checkpoint
from r2.governance.grant_signature import VerifiedGrantEventV1, verify_grant_event
from r2.governance.grant_transition import GrantScopeV1, verify_next_grant_event
from server.services.governance_grant_fence import acquire_grant_import_fence, acquire_grant_recovery_scan_fence


class ShowrunnerGrantUnavailableError(PermissionError):
    """A current, authentic, scoped grant cannot be established."""


class GrantRecoveryUnavailable(RuntimeError):
    """The signed checkpoint and local grant ledger cannot be reconciled."""


def _scope_matches(event: VerifiedGrantEventV1, scope: GrantScopeV1) -> bool:
    return (
        event.body.user_id == scope.user_id
        and event.body.project_name == scope.project_name
        and event.body.principal == scope.principal
    )


def _imported_at(row: ShowrunnerGrantEventModel) -> datetime:
    value = row.imported_at
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


async def _database_now(session: AsyncSession) -> datetime:
    if session.get_bind().dialect.name == "postgresql":
        value = await session.scalar(select(func.clock_timestamp()))
        if not isinstance(value, datetime) or value.utcoffset() is None:
            raise ShowrunnerGrantUnavailableError("grant database time unavailable")
        return value.astimezone(UTC)
    return datetime.now(UTC)


async def _locked_head(session: AsyncSession, scope: GrantScopeV1) -> ShowrunnerGrantHeadModel | None:
    return (
        await session.execute(
            select(ShowrunnerGrantHeadModel)
            .where(
                ShowrunnerGrantHeadModel.user_id == scope.user_id,
                ShowrunnerGrantHeadModel.project_name == scope.project_name,
                ShowrunnerGrantHeadModel.principal == scope.principal,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


async def _locked_event(session: AsyncSession, scope: GrantScopeV1, sequence: int) -> ShowrunnerGrantEventModel | None:
    return (
        await session.execute(
            select(ShowrunnerGrantEventModel)
            .where(
                ShowrunnerGrantEventModel.user_id == scope.user_id,
                ShowrunnerGrantEventModel.project_name == scope.project_name,
                ShowrunnerGrantEventModel.principal == scope.principal,
                ShowrunnerGrantEventModel.sequence == sequence,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


class _GrantLedger:
    def __init__(self, *, key_id: str, public_key: bytes) -> None:
        if not key_id or len(public_key) != 32:
            raise ShowrunnerGrantUnavailableError("grant verifier is unconfigured")
        self.key_id = key_id
        self.public_key = public_key

    def _verify_row(self, row: ShowrunnerGrantEventModel, scope: GrantScopeV1) -> VerifiedGrantEventV1:
        try:
            event = verify_grant_event(row.raw_event, key_id=self.key_id, public_key=self.public_key)
        except GrantEventInvalid:
            raise ShowrunnerGrantUnavailableError("stored grant event is invalid") from None
        if (
            not _scope_matches(event, scope)
            or row.sequence != event.body.sequence
            or row.event_digest != event.event_digest
            or row.event_type != event.body.event_type
            or row.issued_at != event.body.issued_at
            or row.signer_key_id != event.body.signer_key_id
        ):
            raise ShowrunnerGrantUnavailableError("stored grant event differs from its signed bytes")
        return event

    async def _current_locked(
        self, session: AsyncSession, head: ShowrunnerGrantHeadModel, scope: GrantScopeV1
    ) -> tuple[ShowrunnerGrantEventModel, VerifiedGrantEventV1] | None:
        if head.current_sequence is None and head.current_event_digest is None:
            return None
        if head.current_sequence is None or head.current_event_digest is None:
            raise ShowrunnerGrantUnavailableError("grant head is incomplete")
        rows = (
            (
                await session.execute(
                    select(ShowrunnerGrantEventModel)
                    .where(
                        ShowrunnerGrantEventModel.user_id == scope.user_id,
                        ShowrunnerGrantEventModel.project_name == scope.project_name,
                        ShowrunnerGrantEventModel.principal == scope.principal,
                    )
                    .order_by(ShowrunnerGrantEventModel.sequence)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            )
            .scalars()
            .all()
        )
        if len(rows) != head.current_sequence:
            raise ShowrunnerGrantUnavailableError("grant history is missing or not latest")
        previous: VerifiedGrantEventV1 | None = None
        for expected_sequence, row in enumerate(rows, 1):
            event = self._verify_row(row, scope)
            if event.body.sequence != expected_sequence:
                raise ShowrunnerGrantUnavailableError("grant history sequence has a gap")
            if previous is None:
                if event.body.event_type != "ISSUE" or event.body.previous_event_digest is not None:
                    raise ShowrunnerGrantUnavailableError("grant history genesis is invalid")
            elif (
                event.body.previous_event_digest != previous.event_digest
                or event.body.event_type == previous.body.event_type
                or event.body.issued_at <= previous.body.issued_at
            ):
                raise ShowrunnerGrantUnavailableError("grant history chain is invalid")
            previous = event
        if previous is None or previous.event_digest != head.current_event_digest:
            raise ShowrunnerGrantUnavailableError("grant head digest differs from signed event")
        return rows[-1], previous


class GovernanceGrantImporter(_GrantLedger):
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        key_id: str,
        public_key: bytes,
        on_head_locked: Callable[[AsyncSession], Awaitable[None]] | None = None,
    ) -> None:
        super().__init__(key_id=key_id, public_key=public_key)
        self._sessions = session_factory
        self._on_head_locked = on_head_locked

    async def import_event(self, raw: bytes, *, scope: GrantScopeV1) -> VerifiedGrantEventV1:
        try:
            submitted = verify_grant_event(raw, key_id=self.key_id, public_key=self.public_key)
        except GrantEventInvalid:
            raise ShowrunnerGrantUnavailableError("submitted grant event is invalid") from None
        if not _scope_matches(submitted, scope):
            raise ShowrunnerGrantUnavailableError("submitted grant scope differs")
        async with self._sessions() as session, session.begin():
            await acquire_grant_import_fence(session)
            insert = pg_insert if session.get_bind().dialect.name == "postgresql" else sqlite_insert
            inserted = (
                await session.execute(
                    insert(ShowrunnerGrantHeadModel)
                    .values(
                        user_id=scope.user_id,
                        project_name=scope.project_name,
                        principal=scope.principal,
                        current_sequence=None,
                        current_event_digest=None,
                    )
                    .on_conflict_do_nothing(index_elements=["user_id", "project_name", "principal"])
                    .returning(ShowrunnerGrantHeadModel.user_id)
                )
            ).scalar_one_or_none()
            head = await _locked_head(session, scope)
            if head is None:
                raise ShowrunnerGrantUnavailableError("grant head claim failed")
            current = await self._current_locked(session, head, scope)
            if self._on_head_locked is not None:
                await self._on_head_locked(session)
            if inserted is None and current is None:
                raise ShowrunnerGrantUnavailableError("committed grant head has no event")
            stored = await _locked_event(session, scope, submitted.body.sequence)
            if stored is not None:
                verified = self._verify_row(stored, scope)
                if stored.raw_event != raw:
                    raise ShowrunnerGrantUnavailableError("grant event sequence has different bytes")
                return verified
            now = await _database_now(session)
            try:
                event = verify_next_grant_event(
                    raw,
                    current[0].raw_event if current is not None else None,
                    scope=scope,
                    key_id=self.key_id,
                    public_key=self.public_key,
                    now=now,
                )
            except GrantEventInvalid:
                raise ShowrunnerGrantUnavailableError("grant event transition is invalid") from None
            session.add(
                ShowrunnerGrantEventModel(
                    user_id=scope.user_id,
                    project_name=scope.project_name,
                    principal=scope.principal,
                    sequence=event.body.sequence,
                    raw_event=raw,
                    event_digest=event.event_digest,
                    event_type=event.body.event_type,
                    issued_at=event.body.issued_at,
                    signer_key_id=event.body.signer_key_id,
                    imported_at=now,
                )
            )
            await session.flush()
            head.current_sequence = event.body.sequence
            head.current_event_digest = event.event_digest
            await session.flush()
            return event


@dataclass(frozen=True)
class ConsultedGrantHead:
    """One chain the reader looked at, as its locked head stood (both ``None`` when it has no event)."""

    scope: GrantScopeV1
    head_sequence: int | None
    head_event_digest: str | None


def _workspace_scope(scope: GrantScopeV1) -> GrantScopeV1:
    return GrantScopeV1(scope.user_id, WORKSPACE_SCOPE, scope.principal)


def _active_issue(event: VerifiedGrantEventV1, now: datetime) -> bool:
    return (
        event.body.event_type == "ISSUE"
        and event.body.not_before is not None
        and event.body.expires_at is not None
        and event.body.not_before <= now.strftime("%Y-%m-%dT%H:%M:%SZ") < event.body.expires_at
    )


class CurrentShowrunnerGrantReader(_GrantLedger):
    async def _chain_locked(
        self, session: AsyncSession, scope: GrantScopeV1
    ) -> tuple[ShowrunnerGrantHeadModel | None, VerifiedGrantEventV1 | None, ConsultedGrantHead]:
        head = await _locked_head(session, scope)
        current = None if head is None else await self._current_locked(session, head, scope)
        consulted = ConsultedGrantHead(
            scope=scope,
            head_sequence=None if current is None else current[1].body.sequence,
            head_event_digest=None if current is None else current[1].event_digest,
        )
        return head, None if current is None else current[1], consulted

    async def resolve_current_locked(
        self, session: AsyncSession, *, scope: GrantScopeV1
    ) -> tuple[VerifiedGrantEventV1, tuple[ConsultedGrantHead, ...]]:
        """The project's own current ISSUE; else, unless the project's chain ends in a REVOKE, the workspace's.

        Heads are locked project first, then workspace. Returns the chains consulted so a checkpoint can cover them.
        """

        if not session.in_transaction():
            raise ShowrunnerGrantUnavailableError("grant read requires a transaction")
        if scope.project_name.startswith("@"):
            raise ShowrunnerGrantUnavailableError("grant scope is not a project")
        head, event, consulted = await self._chain_locked(session, scope)
        now = await _database_now(session)
        if event is not None and _active_issue(event, now):
            return event, (consulted,)
        if event is not None and event.body.event_type == "REVOKE":
            raise ShowrunnerGrantUnavailableError("grant is not currently active")
        reason = (
            "grant head is missing"
            if head is None
            else "grant has no current event"
            if event is None
            else "grant is not currently active"
        )
        ws_head, ws_event, ws_consulted = await self._chain_locked(session, _workspace_scope(scope))
        if ws_head is None:
            raise ShowrunnerGrantUnavailableError(reason)
        if ws_event is None or not _active_issue(ws_event, now):
            raise ShowrunnerGrantUnavailableError("grant is not currently active")
        return ws_event, (consulted, ws_consulted)

    async def require_current_locked(self, session: AsyncSession, *, scope: GrantScopeV1) -> VerifiedGrantEventV1:
        """Read local grant state under the caller's transaction; activation needs external custody."""

        event, _ = await self.resolve_current_locked(session, scope=scope)
        return event

    async def require_historical_issue_locked(
        self,
        session: AsyncSession,
        *,
        scope: GrantScopeV1,
        event_digest: str,
        authenticated_at: datetime,
    ) -> VerifiedGrantEventV1:
        """Verify a replay's signed ISSUE reference within the locked, current grant chain."""
        if authenticated_at.tzinfo is None:
            raise ShowrunnerGrantUnavailableError("historical authorization time is not UTC-aware")
        _, consulted = await self.resolve_current_locked(session, scope=scope)
        rows: list[ShowrunnerGrantEventModel] = []
        match_index: int | None = None
        for chain in consulted:
            scope = chain.scope
            rows = list(
                (
                    await session.execute(
                        select(ShowrunnerGrantEventModel)
                        .where(
                            ShowrunnerGrantEventModel.user_id == scope.user_id,
                            ShowrunnerGrantEventModel.project_name == scope.project_name,
                            ShowrunnerGrantEventModel.principal == scope.principal,
                        )
                        .order_by(ShowrunnerGrantEventModel.sequence)
                        .with_for_update()
                        .execution_options(populate_existing=True)
                    )
                )
                .scalars()
                .all()
            )
            match_index = next((index for index, row in enumerate(rows) if row.event_digest == event_digest), None)
            if match_index is not None:
                break
        if match_index is None:
            raise ShowrunnerGrantUnavailableError("historical grant event reference is missing")
        event = self._verify_row(rows[match_index], scope)
        at = authenticated_at.astimezone(UTC)
        if (
            event.body.event_type != "ISSUE"
            or event.body.not_before is None
            or event.body.expires_at is None
            or not _imported_at(rows[match_index]) <= at
            or not datetime.fromisoformat(event.body.not_before) <= at < datetime.fromisoformat(event.body.expires_at)
        ):
            raise ShowrunnerGrantUnavailableError("historical grant was not active at authorization time")
        if match_index + 1 < len(rows):
            self._verify_row(rows[match_index + 1], scope)
            if at >= _imported_at(rows[match_index + 1]):
                raise ShowrunnerGrantUnavailableError("historical grant was superseded before authorization")
        return event


class CheckpointedShowrunnerGrantReader(CurrentShowrunnerGrantReader):
    """Require a fresh signed checkpoint for the transaction-locked grant head."""

    def __init__(
        self,
        *,
        grant_key_id: str,
        grant_public_key: bytes,
        deployment_id: str,
        checkpoint_key_id: str,
        checkpoint_public_key: bytes,
        load_checkpoint: Callable[[], Awaitable[bytes]],
    ) -> None:
        super().__init__(key_id=grant_key_id, public_key=grant_public_key)
        self._deployment_id = deployment_id
        self._checkpoint_key_id = checkpoint_key_id
        self._checkpoint_public_key = checkpoint_public_key
        self._load_checkpoint = load_checkpoint

    async def resolve_current_locked(
        self, session: AsyncSession, *, scope: GrantScopeV1
    ) -> tuple[VerifiedGrantEventV1, tuple[ConsultedGrantHead, ...]]:
        event, consulted = await super().resolve_current_locked(session, scope=scope)
        try:
            raw = await self._load_checkpoint()
            checkpoint = verify_grant_checkpoint(
                raw,
                deployment_id=self._deployment_id,
                key_id=self._checkpoint_key_id,
                public_key=self._checkpoint_public_key,
            )
        except Exception:
            raise ShowrunnerGrantUnavailableError("signed grant checkpoint is unavailable") from None
        # Every chain consulted must match: an absent head where the checkpoint lists one (a deleted per-project
        # REVOKE) cannot fall through to the workspace grant.
        for chain in consulted:
            expected = checkpoint.head_for_scope(
                user_id=chain.scope.user_id, project_name=chain.scope.project_name, principal=chain.scope.principal
            )
            if (None if expected is None else (expected.head_sequence, expected.head_event_digest)) != (
                None if chain.head_sequence is None else (chain.head_sequence, chain.head_event_digest)
            ):
                raise ShowrunnerGrantUnavailableError("signed grant checkpoint differs from current head")
        return event, consulted


class GovernanceGrantHeadExporter(_GrantLedger):
    """Read every committed grant head, each chain verified, for the operator's next checkpoint body."""

    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], *, grant_key_id: str, grant_public_key: bytes
    ) -> None:
        super().__init__(key_id=grant_key_id, public_key=grant_public_key)
        self._sessions = session_factory

    async def heads(self) -> tuple[GrantHeadRecordV1, ...]:
        """Ordered by scope, under the same scan fence the recovery scanner takes."""
        async with self._sessions() as session, session.begin():
            await acquire_grant_recovery_scan_fence(session)
            scopes = (
                (
                    await session.execute(
                        select(
                            ShowrunnerGrantHeadModel.user_id,
                            ShowrunnerGrantHeadModel.project_name,
                            ShowrunnerGrantHeadModel.principal,
                        ).order_by(
                            ShowrunnerGrantHeadModel.user_id,
                            ShowrunnerGrantHeadModel.project_name,
                            ShowrunnerGrantHeadModel.principal,
                        )
                    )
                )
                .tuples()
                .all()
            )
            # The checkpoint orders scopes by code point; the database collation may not.
            scopes = sorted(scopes)
            records: list[GrantHeadRecordV1] = []
            for user_id, project_name, principal in scopes:
                scope = GrantScopeV1(user_id, project_name, principal)
                head = await _locked_head(session, scope)
                if head is None:
                    raise GrantRecoveryUnavailable("grant head is missing")
                try:
                    current = await self._current_locked(session, head, scope)
                except ShowrunnerGrantUnavailableError:
                    raise GrantRecoveryUnavailable("grant chain is invalid") from None
                if current is None or head.current_sequence is None:
                    raise GrantRecoveryUnavailable("grant head has no current event")
                records.append(
                    GrantHeadRecordV1(
                        user_id=user_id,
                        project_name=project_name,
                        principal=principal,
                        head_sequence=head.current_sequence,
                        head_event_digest=current[1].event_digest,
                    )
                )
            return tuple(records)


class GovernanceGrantRecoveryScanner(_GrantLedger):
    """Verify every local signed grant chain against one external checkpoint."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        grant_key_id: str,
        grant_public_key: bytes,
        deployment_id: str,
        checkpoint_key_id: str,
        checkpoint_public_key: bytes,
    ) -> None:
        super().__init__(key_id=grant_key_id, public_key=grant_public_key)
        self._sessions = session_factory
        self._deployment_id = deployment_id
        self._checkpoint_key_id = checkpoint_key_id
        self._checkpoint_public_key = checkpoint_public_key

    async def verify(self, load_checkpoint: Callable[[], Awaitable[bytes]]) -> VerifiedGrantCheckpointV1:
        """Fence imports before loading the checkpoint and enumerating all scopes."""

        async with self._sessions() as session, session.begin():
            await acquire_grant_recovery_scan_fence(session)
            try:
                raw = await load_checkpoint()
                checkpoint = verify_grant_checkpoint(
                    raw,
                    deployment_id=self._deployment_id,
                    key_id=self._checkpoint_key_id,
                    public_key=self._checkpoint_public_key,
                )
            except Exception:
                raise GrantRecoveryUnavailable("checkpoint is unavailable") from None
            scopes = (
                (
                    await session.execute(
                        select(
                            ShowrunnerGrantHeadModel.user_id,
                            ShowrunnerGrantHeadModel.project_name,
                            ShowrunnerGrantHeadModel.principal,
                        ).order_by(
                            ShowrunnerGrantHeadModel.user_id,
                            ShowrunnerGrantHeadModel.project_name,
                            ShowrunnerGrantHeadModel.principal,
                        )
                    )
                )
                .tuples()
                .all()
            )
            scopes = sorted(scopes)
            if len(scopes) != len(checkpoint.body.heads):
                raise GrantRecoveryUnavailable("checkpoint scope set differs from grant ledger")
            for (user_id, project_name, principal), expected in zip(scopes, checkpoint.body.heads, strict=True):
                if (user_id, project_name, principal) != (expected.user_id, expected.project_name, expected.principal):
                    raise GrantRecoveryUnavailable("checkpoint scope set differs from grant ledger")
                scope = GrantScopeV1(user_id, project_name, principal)
                head = await _locked_head(session, scope)
                if head is None:
                    raise GrantRecoveryUnavailable("checkpoint grant head is missing")
                try:
                    current = await self._current_locked(session, head, scope)
                except ShowrunnerGrantUnavailableError:
                    raise GrantRecoveryUnavailable("checkpoint grant chain is invalid") from None
                if (
                    current is None
                    or head.current_sequence != expected.head_sequence
                    or current[1].event_digest != expected.head_event_digest
                ):
                    raise GrantRecoveryUnavailable("checkpoint grant head differs")
            return checkpoint


__all__ = [
    "CheckpointedShowrunnerGrantReader",
    "ConsultedGrantHead",
    "CurrentShowrunnerGrantReader",
    "GovernanceGrantHeadExporter",
    "GovernanceGrantImporter",
    "GovernanceGrantRecoveryScanner",
    "GrantRecoveryUnavailable",
    "ShowrunnerGrantUnavailableError",
]

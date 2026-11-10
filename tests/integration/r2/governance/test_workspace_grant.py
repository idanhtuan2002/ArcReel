"""A workspace grant covers every project of its user unless the project's own chain decides."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.models.governance_grant import ShowrunnerGrantEventModel, ShowrunnerGrantHeadModel
from lib.db.models.user import User
from r2.contracts.showrunner_grant import WORKSPACE_SCOPE
from r2.governance.grant_transition import GrantScopeV1
from server.services.governance_grants import (
    CheckpointedShowrunnerGrantReader,
    CurrentShowrunnerGrantReader,
    GovernanceGrantHeadExporter,
    GovernanceGrantImporter,
    GovernanceGrantRecoveryScanner,
    ShowrunnerGrantUnavailableError,
)
from tests.integration.r2.governance.test_grant_importer import _event, _signed
from tests.integration.r2.governance.test_grant_recovery_snapshot import _checkpoint, _head

KEY_ID = "test-governance-key"
PROJECT = GrantScopeV1("u1", "show-a", "reviewer-a")
WORKSPACE = GrantScopeV1("u1", WORKSPACE_SCOPE, "reviewer-a")
_PRIVATE = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
_PUBLIC = _PRIVATE.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def _workspace_event(action: str, sequence: int, predecessor: str | None, issued_at: str) -> dict[str, object]:
    body = _event(action, sequence, predecessor, issued_at, project_name=WORKSPACE_SCOPE)
    body["schema"] = "governance.showrunner_grant_event.v2"
    return body


def _soon_expiring(body: dict[str, object]) -> dict[str, object]:
    body["expires_at"] = (datetime.now(UTC) + timedelta(seconds=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return body


async def _setup(session_factory: async_sessionmaker[AsyncSession]) -> GovernanceGrantImporter:
    async with session_factory() as session, session.begin():
        if await session.get(User, "u1") is None:
            session.add(User(id="u1", username="u1"))
    return GovernanceGrantImporter(session_factory, key_id=KEY_ID, public_key=_PUBLIC)


def _checkpointed(raw: bytes) -> CheckpointedShowrunnerGrantReader:
    async def load() -> bytes:
        return raw

    return CheckpointedShowrunnerGrantReader(
        grant_key_id=KEY_ID,
        grant_public_key=_PUBLIC,
        deployment_id="deploy-a",
        checkpoint_key_id="checkpoint-test-key",
        checkpoint_public_key=_PUBLIC,
        load_checkpoint=load,
    )


async def _current(session_factory: async_sessionmaker[AsyncSession], reader: CurrentShowrunnerGrantReader) -> str:
    async with session_factory() as session, session.begin():
        return (await reader.require_current_locked(session, scope=PROJECT)).event_digest


@pytest.mark.asyncio
@pytest.mark.parametrize("project_chain", ["absent", "issue", "revoke", "expired"])
async def test_project_chain_takes_precedence_over_the_workspace(
    session_factory: async_sessionmaker[AsyncSession], project_chain: str
) -> None:
    importer = await _setup(session_factory)
    workspace = await importer.import_event(
        _signed(_workspace_event("ISSUE", 1, None, "2026-01-01T00:00:00Z"), _PRIVATE), scope=WORKSPACE
    )
    project = None
    if project_chain != "absent":
        body = _event("ISSUE", 1, None, "2026-01-01T00:00:00Z")
        if project_chain == "expired":
            body = _soon_expiring(body)
        project = await importer.import_event(_signed(body, _PRIVATE), scope=PROJECT)
    if project_chain == "revoke":
        assert project is not None
        await importer.import_event(
            _signed(_event("REVOKE", 2, project.event_digest, "2026-02-01T00:00:00Z"), _PRIVATE), scope=PROJECT
        )
    if project_chain == "expired":
        await asyncio.sleep(2.5)
    reader = CurrentShowrunnerGrantReader(key_id=KEY_ID, public_key=_PUBLIC)
    if project_chain == "revoke":
        with pytest.raises(ShowrunnerGrantUnavailableError, match="not currently active"):
            await _current(session_factory, reader)
        return
    expected = project.event_digest if project_chain == "issue" and project is not None else workspace.event_digest
    assert await _current(session_factory, reader) == expected


@pytest.mark.asyncio
async def test_workspace_grant_does_not_cover_another_user_or_principal(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    importer = await _setup(session_factory)
    await importer.import_event(
        _signed(_workspace_event("ISSUE", 1, None, "2026-01-01T00:00:00Z"), _PRIVATE), scope=WORKSPACE
    )
    reader = CurrentShowrunnerGrantReader(key_id=KEY_ID, public_key=_PUBLIC)
    for scope in (GrantScopeV1("u2", "show-a", "reviewer-a"), GrantScopeV1("u1", "show-a", "reviewer-b")):
        async with session_factory() as session, session.begin():
            with pytest.raises(ShowrunnerGrantUnavailableError, match="head is missing"):
                await reader.require_current_locked(session, scope=scope)
    async with session_factory() as session, session.begin():
        with pytest.raises(ShowrunnerGrantUnavailableError, match="not a project"):
            await reader.require_current_locked(session, scope=WORKSPACE)


@pytest.mark.asyncio
async def test_revoked_workspace_grant_covers_nothing(session_factory: async_sessionmaker[AsyncSession]) -> None:
    importer = await _setup(session_factory)
    issue = await importer.import_event(
        _signed(_workspace_event("ISSUE", 1, None, "2026-01-01T00:00:00Z"), _PRIVATE), scope=WORKSPACE
    )
    await importer.import_event(
        _signed(_workspace_event("REVOKE", 2, issue.event_digest, "2026-02-01T00:00:00Z"), _PRIVATE), scope=WORKSPACE
    )
    with pytest.raises(ShowrunnerGrantUnavailableError, match="not currently active"):
        await _current(session_factory, CurrentShowrunnerGrantReader(key_id=KEY_ID, public_key=_PUBLIC))


@pytest.mark.asyncio
async def test_importer_refuses_an_event_under_the_other_schema(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    importer = await _setup(session_factory)
    v1_named_workspace = _event("ISSUE", 1, None, "2026-01-01T00:00:00Z", project_name=WORKSPACE_SCOPE)
    v2_named_project = _workspace_event("ISSUE", 1, None, "2026-01-01T00:00:00Z")
    v2_named_project["project_name"] = "show-a"
    with pytest.raises(ShowrunnerGrantUnavailableError, match="invalid"):
        await importer.import_event(_signed(v1_named_workspace, _PRIVATE), scope=WORKSPACE)
    with pytest.raises(ShowrunnerGrantUnavailableError, match="invalid"):
        await importer.import_event(_signed(v2_named_project, _PRIVATE), scope=PROJECT)


@pytest.mark.asyncio
async def test_checkpoint_must_cover_every_chain_consulted(session_factory: async_sessionmaker[AsyncSession]) -> None:
    importer = await _setup(session_factory)
    workspace = await importer.import_event(
        _signed(_workspace_event("ISSUE", 1, None, "2026-01-01T00:00:00Z"), _PRIVATE), scope=WORKSPACE
    )
    issue = await importer.import_event(
        _signed(_event("ISSUE", 1, None, "2026-01-01T00:00:00Z"), _PRIVATE), scope=PROJECT
    )
    revoke = await importer.import_event(
        _signed(_event("REVOKE", 2, issue.event_digest, "2026-02-01T00:00:00Z"), _PRIVATE), scope=PROJECT
    )
    workspace_head = _head(WORKSPACE_SCOPE, 1, workspace.event_digest)
    revoked_head = _head("show-a", 2, revoke.event_digest)
    # The exporter's heads, sorted by code point, are what an operator signs; the scanner accepts them.
    exported = await GovernanceGrantHeadExporter(session_factory, grant_key_id=KEY_ID, grant_public_key=_PUBLIC).heads()
    assert [(head.project_name, head.head_sequence) for head in exported] == [(WORKSPACE_SCOPE, 1), ("show-a", 2)]
    checkpoint = _checkpoint([workspace_head, revoked_head])
    scanner = GovernanceGrantRecoveryScanner(
        session_factory,
        grant_key_id=KEY_ID,
        grant_public_key=_PUBLIC,
        deployment_id="deploy-a",
        checkpoint_key_id="checkpoint-test-key",
        checkpoint_public_key=_PUBLIC,
    )

    async def load() -> bytes:
        return checkpoint

    await scanner.verify(load)

    # The revoke denies, under the matching checkpoint.
    with pytest.raises(ShowrunnerGrantUnavailableError, match="not currently active"):
        await _current(session_factory, _checkpointed(checkpoint))

    # Deleting the project's chain from the database cannot fall through to the workspace grant.
    async with session_factory() as session, session.begin():
        project_head = ShowrunnerGrantHeadModel.project_name == "show-a"
        await session.execute(
            update(ShowrunnerGrantHeadModel)
            .where(project_head)
            .values(current_sequence=None, current_event_digest=None)
        )
        await session.execute(
            delete(ShowrunnerGrantEventModel).where(ShowrunnerGrantEventModel.project_name == "show-a")
        )
        await session.execute(delete(ShowrunnerGrantHeadModel).where(project_head))
    with pytest.raises(ShowrunnerGrantUnavailableError, match="checkpoint differs"):
        await _current(session_factory, _checkpointed(checkpoint))

    # A checkpoint without the project falls back, and must still match the workspace head.
    assert await _current(session_factory, _checkpointed(_checkpoint([workspace_head]))) == workspace.event_digest
    with pytest.raises(ShowrunnerGrantUnavailableError, match="checkpoint differs"):
        await _current(session_factory, _checkpointed(_checkpoint([])))
    with pytest.raises(ShowrunnerGrantUnavailableError, match="checkpoint differs"):
        await _current(session_factory, _checkpointed(_checkpoint([_head(WORKSPACE_SCOPE, 1, "sha256:" + "0" * 64)])))


@pytest.mark.asyncio
async def test_historical_reference_resolves_in_the_workspace_chain(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    importer = await _setup(session_factory)
    workspace = await importer.import_event(
        _signed(_workspace_event("ISSUE", 1, None, "2026-01-01T00:00:00Z"), _PRIVATE), scope=WORKSPACE
    )
    reader = CurrentShowrunnerGrantReader(key_id=KEY_ID, public_key=_PUBLIC)
    async with session_factory() as session, session.begin():
        row = await session.get(ShowrunnerGrantEventModel, ("u1", WORKSPACE_SCOPE, "reviewer-a", 1))
        assert row is not None
        found = await reader.require_historical_issue_locked(
            session,
            scope=PROJECT,
            event_digest=workspace.event_digest,
            authenticated_at=row.imported_at.replace(tzinfo=UTC),
        )
        assert found.event_digest == workspace.event_digest

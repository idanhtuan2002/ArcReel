"""The operator ceremony: enroll a genesis archive, import a signed ISSUE, and publish its checkpoint."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from r2.governance import ceremony as ceremony_builders
from r2.governance.ceremony import (
    CeremonyInvalid,
    build_approved_deployment,
    build_registry,
    checkpoint_body,
    generate_key,
    sign_checkpoint,
    sign_grant_event,
    utc_second,
)
from r2.governance.grant_transition import GrantScopeV1
from r2.governance.operator_archive_reader import OperatorArchiveInvalid, OperatorArchiveReader
from server.services import governance_ceremony as ceremony_service
from server.services.governance_ceremony import (
    enroll_genesis,
    import_grant_event,
    next_checkpoint_body,
    publish_signed_checkpoint,
)
from server.services.governance_operator_archive import (
    OperatorArchiveReconcileUnavailable,
    verify_operator_archive_preflight,
)
from server.services.governance_startup import verify_governance_public_startup
from tests.integration.r2.governance.test_operator_archive_reconcile import _ready_schema

type Factory = async_sessionmaker[AsyncSession]

UID = os.getuid()


async def _postgres(factory: Factory) -> None:
    engine = factory.kw["bind"]
    if engine.dialect.name != "postgresql":
        pytest.skip("the operator ceremony requires PostgreSQL")
    await _ready_schema(engine)


def _genesis():
    grant, checkpoint = generate_key(), generate_key()
    registry_raw, registry = build_registry(
        deployment_id="deploy-a",
        grant_key_id="grant-key-a",
        grant_public_key=grant.public_encoded,
        checkpoint_key_id="checkpoint-key-a",
        checkpoint_public_key=checkpoint.public_encoded,
    )
    approved_raw = build_approved_deployment(
        registry_raw, image_ref="arcreel/arcreel@sha256:" + "a" * 64, image_platform="linux/amd64", operator_id="op-a"
    )
    genesis_raw = sign_checkpoint(
        checkpoint_body(
            deployment_id=registry.deployment_id,
            signer_key_id=registry.grant_checkpoint.key_id,
            sequence=1,
            previous=None,
            heads=(),
        ),
        checkpoint.private_raw,
    )
    return grant, checkpoint, registry_raw, approved_raw, genesis_raw


def _issue(grant, *, issued_at: str | None = None) -> bytes:
    raw, _event = sign_grant_event(
        private_raw=grant.private_raw,
        signer_key_id="grant-key-a",
        event_type="ISSUE",
        user_id="default",
        project_name="show-a",
        principal="reviewer-a",
        sequence=1,
        previous_event_digest=None,
        expires_at=utc_second(datetime.now(UTC) + timedelta(days=30)),
        issued_at=issued_at,
    )
    return raw


@pytest.mark.asyncio
async def test_the_ceremony_enrolls_imports_and_publishes_a_checkpoint_the_preflight_accepts(
    session_factory: Factory, tmp_path: Path
) -> None:
    await _postgres(session_factory)
    grant, checkpoint, registry_raw, approved_raw, genesis_raw = _genesis()
    root = tmp_path / "custody"

    enrolled = await enroll_genesis(
        root,
        registry_raw=registry_raw,
        approved_raw=approved_raw,
        checkpoint_raw=genesis_raw,
        operator_id="op-a",
        session_factory=session_factory,
        expected_uid=UID,
    )
    assert enrolled.snapshot.high_water.checkpoint_sequence == 1

    event = await import_grant_event(root, _issue(grant), session_factory=session_factory, expected_uid=UID)
    # The imported grant is not in the published checkpoint yet, so the preflight denies until it is.
    with pytest.raises(OperatorArchiveReconcileUnavailable):
        await verify_operator_archive_preflight(root, session_factory=session_factory, expected_uid=UID)

    body = await next_checkpoint_body(root, session_factory=session_factory, expected_uid=UID)
    signed = sign_checkpoint(body, checkpoint.private_raw)
    published = await publish_signed_checkpoint(
        root, signed, operator_id="op-a", session_factory=session_factory, expected_uid=UID
    )

    assert published.snapshot.high_water.checkpoint_sequence == 2
    [head] = published.snapshot.checkpoint.body.heads
    assert (head.user_id, head.project_name, head.principal, head.head_sequence) == (
        "default",
        "show-a",
        "reviewer-a",
        1,
    )
    assert head.head_event_digest == event.event_digest
    assert await verify_operator_archive_preflight(root, session_factory=session_factory, expected_uid=UID) == (
        OperatorArchiveReader(root, expected_uid=UID).read()
    )
    assert (root / "read" / "grant-checkpoint.json").read_bytes() == signed
    # The application's own startup verifier accepts the published copies and the ISSUE is current.
    reader = await verify_governance_public_startup(
        root / "read", session_factory=session_factory, expected_uid=UID, expected_gid=os.getgid()
    )
    async with session_factory() as session, session.begin():
        current = await reader.require_current_locked(session, scope=GrantScopeV1("default", "show-a", "reviewer-a"))
    assert current.event_digest == event.event_digest


@pytest.mark.asyncio
async def test_the_ceremony_refuses_a_second_enrollment_a_used_ledger_or_a_foreign_signer(
    session_factory: Factory, tmp_path: Path
) -> None:
    await _postgres(session_factory)
    grant, _checkpoint, registry_raw, approved_raw, genesis_raw = _genesis()
    root = tmp_path / "custody"
    enroll = {
        "registry_raw": registry_raw,
        "approved_raw": approved_raw,
        "checkpoint_raw": genesis_raw,
        "operator_id": "op-a",
        "session_factory": session_factory,
        "expected_uid": UID,
    }
    await enroll_genesis(root, **enroll)

    with pytest.raises(CeremonyInvalid, match="new path"):
        await enroll_genesis(root, **enroll)

    await import_grant_event(root, _issue(grant), session_factory=session_factory, expected_uid=UID)
    with pytest.raises(CeremonyInvalid, match="empty grant ledger"):
        await enroll_genesis(tmp_path / "second", **enroll)

    body = await next_checkpoint_body(root, session_factory=session_factory, expected_uid=UID)
    foreign = sign_checkpoint(body, generate_key().private_raw)
    with pytest.raises((OperatorArchiveReconcileUnavailable, ValueError)):
        await publish_signed_checkpoint(
            root, foreign, operator_id="op-a", session_factory=session_factory, expected_uid=UID
        )
    assert OperatorArchiveReader(root, expected_uid=UID).read().snapshot.high_water.checkpoint_sequence == 1


class _Crash(RuntimeError):
    pass


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["checkpoint:file_written", "high_water:file_written", "public_checkpoint:renamed"])
async def test_a_publication_interrupted_at_any_phase_completes_when_the_same_file_is_published_again(
    session_factory: Factory, tmp_path: Path, phase: str
) -> None:
    await _postgres(session_factory)
    grant, checkpoint, registry_raw, approved_raw, genesis_raw = _genesis()
    root = tmp_path / "custody"
    await enroll_genesis(
        root,
        registry_raw=registry_raw,
        approved_raw=approved_raw,
        checkpoint_raw=genesis_raw,
        operator_id="op-a",
        session_factory=session_factory,
        expected_uid=UID,
    )
    await import_grant_event(root, _issue(grant), session_factory=session_factory, expected_uid=UID)
    signed = sign_checkpoint(
        await next_checkpoint_body(root, session_factory=session_factory, expected_uid=UID), checkpoint.private_raw
    )
    real_publish = ceremony_service.publish_candidate_archive
    reached: list[str] = []

    async def crash_once(*args, **kwargs):
        def stop(observed: str) -> None:
            if observed == phase:
                reached.append(observed)
                raise _Crash(observed)

        return await real_publish(*args, **kwargs, after_phase=stop)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(ceremony_service, "publish_candidate_archive", crash_once)
        # The publisher reports any interruption as unavailable; the crash itself must have happened.
        with pytest.raises((_Crash, OperatorArchiveReconcileUnavailable)):
            await publish_signed_checkpoint(
                root, signed, operator_id="op-a", session_factory=session_factory, expected_uid=UID
            )

    assert reached == [phase]
    # The retry happens later; the rebuilt high-water record must not depend on the wall clock.
    with pytest.MonkeyPatch.context() as later:
        later.setattr(ceremony_builders, "utc_second", lambda moment=None: "2099-01-01T00:00:00Z")
        resumed = await publish_signed_checkpoint(
            root, signed, operator_id="op-a", session_factory=session_factory, expected_uid=UID
        )
        again = await publish_signed_checkpoint(
            root, signed, operator_id="op-a", session_factory=session_factory, expected_uid=UID
        )

    assert resumed.snapshot.high_water.checkpoint_sequence == 2
    assert again == resumed
    assert await verify_operator_archive_preflight(root, session_factory=session_factory, expected_uid=UID) == resumed


@pytest.mark.asyncio
async def test_enrollment_refuses_an_unbound_approval_before_writing_and_import_trusts_only_the_archive(
    session_factory: Factory, tmp_path: Path
) -> None:
    await _postgres(session_factory)
    grant, _checkpoint, registry_raw, approved_raw, genesis_raw = _genesis()
    _other_grant, _other_checkpoint, other_registry, _approved, _genesis_raw = _genesis()
    root = tmp_path / "custody"
    enroll = {
        "approved_raw": approved_raw,
        "checkpoint_raw": genesis_raw,
        "operator_id": "op-a",
        "session_factory": session_factory,
        "expected_uid": UID,
    }

    with pytest.raises(CeremonyInvalid, match="does not bind"):
        await enroll_genesis(root, registry_raw=other_registry, **enroll)
    assert not root.exists()

    await enroll_genesis(root, registry_raw=registry_raw, **enroll)
    # A swapped public registry no longer matches the retained archive, so its key is never used.
    public_registry = root / "read" / "governance-verifiers-v1.json"
    public_registry.chmod(0o644)
    public_registry.write_bytes(other_registry)
    with pytest.raises(OperatorArchiveInvalid):
        await import_grant_event(root, _issue(grant), session_factory=session_factory, expected_uid=UID)

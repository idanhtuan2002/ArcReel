"""A candidate successor must match the retained chain and committed grant ledger."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.content_digest import canonical_json_bytes
from r2.governance.grant_transition import GrantScopeV1
from r2.governance.operator_archive_reader import ArchiveReadLimits, _locked_archive, _RetainedArchiveState
from server.services.governance_grants import GovernanceGrantImporter
from server.services.governance_operator_archive import OperatorArchiveReconcileUnavailable, verify_candidate_preflight
from tests.integration.r2.governance.test_grant_importer import _event, _signed
from tests.integration.r2.governance.test_operator_archive_reconcile import _ready_schema
from tests.unit.r2.governance.test_operator_archive_reader import _append_successor, _digest, _put, _tree


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["valid", "bad_candidate", "bad_signature", "divergent_ledger", "changed_public"])
async def test_pg_candidate_preflight_requires_signed_successor_committed_ledger_and_stable_archive(
    session_factory: async_sessionmaker[AsyncSession], tmp_path: Path, fault: str
) -> None:
    engine = session_factory.kw["bind"]
    if engine.dialect.name != "postgresql":
        pytest.skip("candidate preflight requires PostgreSQL")
    await _ready_schema(engine)
    root, paths = _tree(tmp_path)
    old_high_water = paths["public_high_water"].read_bytes()
    old_checkpoint = paths["public_checkpoint"].read_bytes()
    _append_successor(root, paths)
    candidate_high_water = paths["public_high_water"].read_bytes()
    candidate_checkpoint = paths["public_checkpoint"].read_bytes()
    if fault == "bad_signature":
        envelope = json.loads(candidate_checkpoint)
        signature = envelope["signature"]
        envelope["signature"] = ("A" if signature[0] != "A" else "B") + signature[1:]
        candidate_checkpoint = canonical_json_bytes(envelope, allow_nan=False)
        high_water = json.loads(candidate_high_water)
        high_water["checkpoint_file_digest"] = _digest(candidate_checkpoint)
        candidate_high_water = canonical_json_bytes(high_water, allow_nan=False)
    (root / "archive" / "high-water" / "00000000000000000002.json").unlink()
    for path in (root / "archive" / "checkpoints").iterdir():
        if path != paths["checkpoint"]:
            path.unlink()
    _put(paths["public_high_water"], old_high_water, 0o644)
    _put(paths["public_checkpoint"], old_checkpoint, 0o644)
    if fault == "divergent_ledger":
        private = Ed25519PrivateKey.from_private_bytes(bytes(range(32, 64)))
        public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        importer = GovernanceGrantImporter(session_factory, key_id="grant-key-a", public_key=public)
        body = _event("ISSUE", 1, None, "2026-01-01T00:00:00Z")
        body["signer_key_id"] = "grant-key-a"
        await importer.import_event(_signed(body, private), scope=GrantScopeV1("u1", "show-a", "reviewer-a"))
    with _locked_archive(root, uid=os.getuid(), limits=ArchiveReadLimits()) as archive:
        state = archive.read_retained()

        def reread() -> _RetainedArchiveState:
            if fault == "changed_public":
                _put(paths["public_checkpoint"], b"{}", 0o644)
            return archive.read_retained()

        if fault == "valid":
            snapshot = await verify_candidate_preflight(
                archive,
                state,
                candidate_high_water,
                candidate_checkpoint,
                session_factory=session_factory,
                reread=reread,
            )
            assert snapshot.high_water.checkpoint_sequence == 2
        else:
            with pytest.raises(OperatorArchiveReconcileUnavailable):
                await verify_candidate_preflight(
                    archive,
                    state,
                    candidate_high_water,
                    b"{}" if fault == "bad_candidate" else candidate_checkpoint,
                    session_factory=session_factory,
                    reread=reread,
                )
    assert not (root / "archive" / "high-water" / "00000000000000000002.json").exists()
    assert {path.name for path in (root / "archive" / ".staging").iterdir()} == set()

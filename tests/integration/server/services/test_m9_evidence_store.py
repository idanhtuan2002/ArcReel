from __future__ import annotations

import asyncio
import importlib
import importlib.util
import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from r2.contracts.opportunity import ErasableEvidencePayload, PayloadDeletionRequest
from r2.opportunity.errors import OpportunityError

ATTEMPT = "019a0000-0000-7000-8000-000000000001"
JOB = "019a0000-0000-7000-8000-000000000002"


def _module() -> Any:
    assert importlib.util.find_spec("server.services.m9_evidence_store") is not None, "B2 evidence store is missing"
    return importlib.import_module("server.services.m9_evidence_store")


def _store(root: Path, project: str = "show-a") -> Any:
    return _module().FileSnapshotEvidenceStore(root, user_id="u1", project_name=project)


def _payload(
    *, ordinal: int = 1, raw: bytes = b"canary-private-evidence", retain: bool = False
) -> ErasableEvidencePayload:
    return ErasableEvidencePayload(
        user_id="u1",
        project_name="show-a",
        attempt_id=ATTEMPT,
        page_ordinal=ordinal,
        evidence_kind="raw-page",
        raw_payload=raw,
        raw_media_type="text/plain",
        source_native_ids=("canary-native-private-id",),
        data_classes=("manual-excerpt",),
        retain_digest_proof=retain,
    )


def _delete(ref: Any, *, retain: bool = False) -> PayloadDeletionRequest:
    return PayloadDeletionRequest(
        user_id="u1",
        project_name="show-a",
        invalidation_job_id=JOB,
        payload_refs=(ref.payload_ref,),
        source_identity_refs=ref.source_identity_refs,
        payload_integrity_refs=(ref.payload_integrity_ref,),
        retain_permitted_digest_proofs=retain,
    )


async def test_same_key_replay_is_immutable_and_survives_reopen(tmp_path: Path) -> None:
    first = await _store(tmp_path).put_if_absent(_payload())
    replay = await _store(tmp_path).put_if_absent(_payload())
    assert replay == first
    assert first.retained_content_digest is None
    assert (
        await _store(tmp_path).verify_and_read(first.payload_ref, first.payload_integrity_ref)
        == b"canary-private-evidence"
    )
    with pytest.raises(OpportunityError, match="M9_COMMAND_REPLAY_CONFLICT"):
        await _store(tmp_path).put_if_absent(_payload(raw=b"different"))
    assert (
        await _store(tmp_path).verify_and_read(first.payload_ref, first.payload_integrity_ref)
        == b"canary-private-evidence"
    )
    assert await asyncio.to_thread(
        lambda: all("canary" not in str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*"))
    )


async def test_equal_and_divergent_concurrent_publication_never_overwrite(tmp_path: Path) -> None:
    results = await asyncio.gather(*[_store(tmp_path).put_if_absent(_payload()) for _ in range(8)])
    assert all(r == results[0] for r in results)
    outcomes = await asyncio.gather(
        _store(tmp_path).put_if_absent(_payload(ordinal=2, raw=b"a")),
        _store(tmp_path).put_if_absent(_payload(ordinal=2, raw=b"b")),
        return_exceptions=True,
    )
    winner = [o for o in outcomes if not isinstance(o, BaseException)]
    assert len(winner) == 1
    assert sum(isinstance(o, OpportunityError) for o in outcomes) == 1
    assert await _store(tmp_path).verify_and_read(winner[0].payload_ref, winner[0].payload_integrity_ref) in {
        b"a",
        b"b",
    }


async def test_refs_are_paired_scoped_and_opaque(tmp_path: Path) -> None:
    a = await _store(tmp_path).put_if_absent(_payload())
    b = await _store(tmp_path).put_if_absent(_payload(ordinal=2))
    for reader, payload, integrity in [
        (_store(tmp_path, "foreign"), a.payload_ref, a.payload_integrity_ref),
        (_store(tmp_path), a.payload_ref, b.payload_integrity_ref),
        (_store(tmp_path), "../../outside", a.payload_integrity_ref),
    ]:
        with pytest.raises(OpportunityError, match="M9_RAW_DIGEST_MISMATCH") as caught:
            await reader.verify_and_read(payload, integrity)
        assert "canary" not in str(caught.value)
    with pytest.raises(OpportunityError):
        await _store(tmp_path, "foreign").put_if_absent(_payload())


@pytest.mark.parametrize(
    ("permitted", "requested", "expected"), [(False, True, False), (True, False, False), (True, True, True)]
)
async def test_exact_erasure_removes_bytes_identities_integrity_and_cannot_upgrade_proofs(
    tmp_path: Path, permitted: bool, requested: bool, expected: bool
) -> None:
    store = _store(tmp_path)
    ref = await store.put_if_absent(_payload(retain=permitted))
    other = await store.put_if_absent(
        _payload(ordinal=2, raw=b"unrelated").model_copy(update={"source_native_ids": ("unrelated-native-id",)})
    )
    result = await store.delete_exact(_delete(ref, retain=requested))
    assert result.erased_payload_refs == (ref.payload_ref,)
    assert result.erased_identity_refs == ref.source_identity_refs
    assert result.erased_integrity_refs == (ref.payload_integrity_ref,)
    assert bool(result.retained_proof_digests) is expected
    assert (
        bool((await _store(tmp_path).delete_exact(_delete(ref, retain=requested))).retained_proof_digests) is expected
    )
    with pytest.raises(OpportunityError):
        await _store(tmp_path).verify_and_read(ref.payload_ref, ref.payload_integrity_ref)
    with pytest.raises(OpportunityError, match="M9_EVIDENCE_RETENTION_EXPIRED"):
        await _store(tmp_path).put_if_absent(_payload(retain=permitted))
    assert await _store(tmp_path).verify_and_read(other.payload_ref, other.payload_integrity_ref) == b"unrelated"


async def test_deleted_entry_contains_no_erased_source_identity_or_integrity(tmp_path: Path) -> None:
    ref = await _store(tmp_path).put_if_absent(_payload())
    await _store(tmp_path).delete_exact(_delete(ref))
    all_bytes = await asyncio.to_thread(lambda: b"".join(p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()))
    assert b"canary-native-private-id" not in all_bytes
    assert b"canary-private-evidence" not in all_bytes
    assert b"Y2FuYXJ5LXByaXZhdGUtZXZpZGVuY2U=" not in all_bytes
    assert b"sha256:" not in all_bytes


async def test_committed_bundle_recovers_when_index_publication_is_interrupted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    module = _module()
    original = module.atomic_write_bytes

    def interrupted(path: Path, raw: bytes) -> None:
        if path.parent.resolve().name == "keys" and not path.name.startswith("identity."):
            raise OSError("canary-private-evidence")
        original(path, raw)

    with monkeypatch.context() as scoped:
        scoped.setattr(module, "atomic_write_bytes", interrupted)
        with pytest.raises(OpportunityError) as caught:
            await _store(tmp_path).put_if_absent(_payload())
        assert "canary" not in str(caught.value)
    ref = await _store(tmp_path).put_if_absent(_payload())
    assert (
        await _store(tmp_path).verify_and_read(ref.payload_ref, ref.payload_integrity_ref) == b"canary-private-evidence"
    )
    assert await asyncio.to_thread(lambda: len(list(tmp_path.rglob("objects/*.json")))) == 1


async def test_payload_corruption_and_object_symlink_fail_closed(tmp_path: Path) -> None:
    ref = await _store(tmp_path).put_if_absent(_payload())
    objects = await asyncio.to_thread(lambda: list(tmp_path.rglob("objects/*.json")))
    assert len(objects) == 1
    original = objects[0].read_bytes()
    body = json.loads(original)
    body["raw_payload"] = "Y29ycnVwdA=="
    objects[0].write_text(json.dumps(body))
    with pytest.raises(OpportunityError, match="M9_RAW_DIGEST_MISMATCH"):
        await _store(tmp_path).verify_and_read(ref.payload_ref, ref.payload_integrity_ref)
    outside = tmp_path.parent / "foreign-object"
    outside.write_bytes(original)
    objects[0].unlink()
    objects[0].symlink_to(outside)
    with pytest.raises(OpportunityError):
        await _store(tmp_path).verify_and_read(ref.payload_ref, ref.payload_integrity_ref)
    assert outside.read_bytes() == original


async def test_refs_resolve_in_an_independent_native_process(tmp_path: Path) -> None:
    ref = await _store(tmp_path).put_if_absent(_payload())
    program = 'import asyncio,sys; from pathlib import Path; from server.services.m9_evidence_store import FileSnapshotEvidenceStore; s=FileSnapshotEvidenceStore(Path(sys.argv[1]),user_id="u1",project_name="show-a"); sys.stdout.buffer.write(asyncio.run(s.verify_and_read(sys.argv[2],sys.argv[3])))'
    result = await asyncio.to_thread(
        subprocess.run,
        [os.sys.executable, "-c", program, str(tmp_path), ref.payload_ref, ref.payload_integrity_ref],
        capture_output=True,
        check=True,
    )
    assert result.stdout == b"canary-private-evidence"


async def test_crash_left_temporary_bytes_are_erased_on_next_store_operation(tmp_path: Path) -> None:
    program = """import asyncio,os,sys
from pathlib import Path
from server.services.m9_evidence_store import FileSnapshotEvidenceStore
from r2.contracts.opportunity import ErasableEvidencePayload
store=FileSnapshotEvidenceStore(Path(sys.argv[1]),user_id="u1",project_name="show-a")
payload=ErasableEvidencePayload.model_validate_json(sys.argv[2])
def crash_before_publish(src,dst):
    os._exit(73)
os.replace=crash_before_publish
asyncio.run(store.put_if_absent(payload))
"""
    result = await asyncio.to_thread(
        subprocess.run,
        [os.sys.executable, "-c", program, str(tmp_path), _payload().model_dump_json()],
        capture_output=True,
    )
    assert result.returncode == 73
    assert await asyncio.to_thread(lambda: list(tmp_path.rglob(".rollback.*.tmp")))
    ref = await _store(tmp_path).put_if_absent(_payload())
    await _store(tmp_path).delete_exact(_delete(ref))
    assert await asyncio.to_thread(lambda: list(tmp_path.rglob(".rollback.*.tmp"))) == []
    all_bytes = await asyncio.to_thread(lambda: b"".join(p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()))
    assert b"Y2FuYXJ5LXByaXZhdGUtZXZpZGVuY2U=" not in all_bytes


async def test_independent_processes_publish_one_equal_result(tmp_path: Path) -> None:
    program = """import asyncio,sys
from pathlib import Path
from server.services.m9_evidence_store import FileSnapshotEvidenceStore
from r2.contracts.opportunity import ErasableEvidencePayload
store=FileSnapshotEvidenceStore(Path(sys.argv[1]),user_id="u1",project_name="show-a")
print(asyncio.run(store.put_if_absent(ErasableEvidencePayload.model_validate_json(sys.argv[2]))).model_dump_json())
"""
    results = await asyncio.gather(
        *[
            asyncio.to_thread(
                subprocess.run,
                [os.sys.executable, "-c", program, str(tmp_path), _payload().model_dump_json()],
                capture_output=True,
                check=True,
            )
            for _ in range(4)
        ]
    )
    assert len({r.stdout for r in results}) == 1


async def test_invalid_batch_erasure_never_partially_erases_valid_refs(tmp_path: Path) -> None:
    ref = await _store(tmp_path).put_if_absent(_payload())
    invalid = _delete(ref).model_copy(update={"payload_integrity_refs": ("m9-integrity:" + "0" * 32 + ":" + "0" * 32,)})
    with pytest.raises(OpportunityError):
        await _store(tmp_path).delete_exact(invalid)
    assert (
        await _store(tmp_path).verify_and_read(ref.payload_ref, ref.payload_integrity_ref) == b"canary-private-evidence"
    )


async def test_source_identity_mapping_is_stable_across_page_and_process_reopen(tmp_path: Path) -> None:
    first = await _store(tmp_path).put_if_absent(_payload())
    second = await _store(tmp_path).put_if_absent(_payload(ordinal=2))
    assert second.source_identity_refs == first.source_identity_refs
    assert second.payload_ref != first.payload_ref

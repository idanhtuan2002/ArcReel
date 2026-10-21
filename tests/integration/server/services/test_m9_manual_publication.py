"""Original signed headers remain discoverable without opening expired material."""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import importlib.util
import json
import os
import sys
from collections import Counter
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import pytest

from r2.opportunity.errors import OpportunityError
from tests.unit.server.services.test_m9_manual_authenticity import (
    PUBLIC,
    canonical,
    publication_receipt,
    receipt_metadata,
)


def publication_module() -> Any:
    assert importlib.util.find_spec("server.services.m9_manual_publication") is not None, "T4 publication store missing"
    return importlib.import_module("server.services.m9_manual_publication")


def header_path(root: Path, key: str = "opaque-publication-1") -> Path:
    scope = hashlib.sha256(canonical({"user_id": "u1", "project_name": "show-a"})).hexdigest()
    return root / "manual-publications" / scope / "headers" / (hashlib.sha256(key.encode()).hexdigest() + ".json")


def install_header(root: Path, raw: bytes) -> Path:
    target = header_path(root)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(raw)
    return target


def store(root: Path) -> Any:
    module = publication_module()
    verifier = module.ManualSealVerifier(public_key=PUBLIC, verification_key_id="fixture-upload-custodian-1")
    return module.FileManualPublicationStore(root, user_id="u1", project_name="show-a", verifier=verifier)


async def test_header_lookup_never_opens_raw_or_attestation(tmp_path: Path) -> None:
    # A nonblocking FIFO open would still fail regular-file validation if accessed.
    for name in ("objects", "attestations"):
        os.mkfifo(tmp_path / name)
    install_header(tmp_path, publication_receipt(receipt_metadata()))
    header = await store(tmp_path).lookup_receipt("opaque-publication-1")
    assert header is not None
    assert header.metadata.claim_ref == "opaque-claim-1"
    assert header.metadata.objects[0].original_clocks[0].retention_due_at.year == 2026
    assert header.metadata.objects[0].payload_ref == "opaque-payload-1"
    assert "material_digest" not in header.model_dump_json()
    assert await store(tmp_path).lookup_receipt("opaque-publication-1") == header


async def test_absent_header_is_read_only(tmp_path: Path) -> None:
    assert await store(tmp_path).lookup_receipt("absent") is None
    assert await asyncio.to_thread(lambda: list(tmp_path.iterdir())) == []


@pytest.mark.parametrize("fault", ["scope", "key", "verifier", "rehashed", "noncanonical", "duplicate", "malformed"])
async def test_forged_expired_header_cannot_redirect_cleanup(tmp_path: Path, fault: str) -> None:
    metadata = receipt_metadata()
    if fault == "scope":
        metadata["context"]["project_name"] = "foreign"
    elif fault == "key":
        metadata["publication_key"] = "foreign"
    elif fault == "verifier":
        metadata["verification_key_id"] = "foreign"
    raw = publication_receipt(metadata)
    if fault == "rehashed":
        body = json.loads(raw)
        body["metadata"]["objects"][0]["payload_ref"] = "CANARY_PRIVATE_MATERIAL"
        body["metadata_digest"] = (
            "sha256:"
            + hashlib.sha256(b"m9.manual-publication-metadata.v1\x00" + canonical(body["metadata"])).hexdigest()
        )
        raw = canonical(body)
    elif fault == "noncanonical":
        raw = json.dumps(json.loads(raw), indent=2).encode()
    elif fault == "duplicate":
        raw = raw.replace(b'{"metadata":', b'{"metadata":{},"metadata":', 1)
    elif fault == "malformed":
        raw = b"CANARY_PRIVATE_MATERIAL"
    install_header(tmp_path, raw)
    with pytest.raises(OpportunityError, match=r"^M9_RAW_DIGEST_MISMATCH$"):
        await store(tmp_path).lookup_receipt("opaque-publication-1")


@pytest.mark.parametrize("boundary", ["root", "scope", "headers", "file", "ancestor"])
async def test_header_symlink_traversal_is_refused(tmp_path: Path, boundary: str) -> None:
    original = tmp_path / "original"
    original.mkdir()
    target = install_header(original, publication_receipt(receipt_metadata()))
    root = original
    if boundary == "root":
        root = tmp_path / "alias"
        root.symlink_to(original, target_is_directory=True)
    elif boundary == "ancestor":
        alias = tmp_path / "alias"
        alias.symlink_to(tmp_path, target_is_directory=True)
        root = alias / "original"
    else:
        chosen = {"scope": target.parent.parent, "headers": target.parent, "file": target}[boundary]
        saved = chosen.with_name(chosen.name + ".saved")
        chosen.rename(saved)
        chosen.symlink_to(saved, target_is_directory=boundary != "file")
    with pytest.raises(OpportunityError, match=r"^M9_RAW_DIGEST_MISMATCH$"):
        await store(root).lookup_receipt("opaque-publication-1")


async def test_header_file_must_be_bounded_regular_file(tmp_path: Path) -> None:
    target = header_path(tmp_path)
    target.parent.mkdir(parents=True)
    os.mkfifo(target)
    with pytest.raises(OpportunityError, match=r"^M9_RAW_DIGEST_MISMATCH$"):
        await store(tmp_path).lookup_receipt("opaque-publication-1")
    target.unlink()
    target.write_bytes(b"x" * 65_537)
    with pytest.raises(OpportunityError, match=r"^M9_RAW_DIGEST_MISMATCH$"):
        await store(tmp_path).lookup_receipt("opaque-publication-1")


def test_host_public_key_binding_is_immutable(tmp_path: Path) -> None:
    instance = store(tmp_path)
    with pytest.raises(FrozenInstanceError):
        instance.verifier = object()
    with pytest.raises(FrozenInstanceError):
        instance.verifier.public_key = b"q" * 32
    assert "public_key" not in repr(instance.verifier)


async def test_store_owner_rewrite_cannot_forge_seal(tmp_path: Path) -> None:
    from r2.opportunity.manual_admission import SealExpectation
    from tests.unit.server.services.test_m9_manual_authenticity import MATERIAL, expectation, seal

    verifier = store(tmp_path).verifier
    expected = SealExpectation.model_validate(expectation())
    verifier.verify_material(seal(expectation()), MATERIAL, expected=expected)
    body = json.loads(seal(expectation()))
    substituted = b"CANARY_PRIVATE_MATERIAL"
    body["body"]["material_digest"] = "sha256:" + hashlib.sha256(substituted).hexdigest()
    with pytest.raises(OpportunityError, match=r"^M9_RAW_DIGEST_MISMATCH$"):
        verifier.verify_material(canonical(body), substituted, expected=expected)
    foreign = SealExpectation.model_validate({**expectation(), "verification_key_id": "foreign"})
    with pytest.raises(OpportunityError, match=r"^M9_RAW_DIGEST_MISMATCH$"):
        verifier.verify_material(seal(foreign.model_dump(mode="json")), MATERIAL, expected=foreign)


@pytest.mark.parametrize("key_id", [None, 1, ["fixture"], "", " " * 4])
def test_invalid_host_verifier_identity_is_refused(key_id: object) -> None:
    with pytest.raises(OpportunityError, match=r"^M9_SOURCE_CAPABILITY_UNAVAILABLE$"):
        publication_module().ManualSealVerifier(public_key=PUBLIC, verification_key_id=key_id)


async def test_fresh_process_audits_header_only_file_access(tmp_path: Path) -> None:
    target = install_header(tmp_path, publication_receipt(receipt_metadata()))
    script = r"""
import asyncio,json,os,sys
from pathlib import Path
from server.services.m9_manual_publication import FileManualPublicationStore,ManualSealVerifier
async def main():
    await asyncio.to_thread(lambda: None)
    store=FileManualPublicationStore(Path(sys.argv[1]),user_id="u1",project_name="show-a",
        verifier=ManualSealVerifier(public_key=bytes.fromhex(sys.argv[2]),verification_key_id="fixture-upload-custodian-1"))
    opened=[]
    def audit(event,args):
        if event != "open":
            return
        path,mode,flags=args
        if isinstance(path,int) or flags & os.O_DIRECTORY:
            return
        if path != sys.argv[3]:
            raise RuntimeError("content access during header-only lookup")
        opened.append(path)
    sys.addaudithook(audit)
    header=await store.lookup_receipt("opaque-publication-1")
    assert header is not None
    print(json.dumps({"pid":os.getpid(),"files":opened,"claim":header.metadata.claim_ref}))
asyncio.run(main())
"""
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        script,
        str(tmp_path),
        PUBLIC.hex(),
        target.name,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    assert process.returncode == 0, stderr.decode()
    result = json.loads(stdout)
    assert result["pid"] != os.getpid()
    assert result["files"] == [target.name]
    assert result["claim"] == "opaque-claim-1"


@pytest.mark.parametrize("key", [None, 1, "", "x" * 4097, "\ud800"])
async def test_invalid_lookup_identity_cannot_escape_header_namespace(tmp_path: Path, key: object) -> None:
    with pytest.raises(OpportunityError, match=r"^M9_RAW_DIGEST_MISMATCH$"):
        await store(tmp_path).lookup_receipt(key)
    assert await asyncio.to_thread(lambda: list(tmp_path.iterdir())) == []


@pytest.mark.parametrize("key", [None, "x" * 32, b"x" * 31, b"x" * 33])
def test_invalid_host_public_key_is_refused(key: object) -> None:
    with pytest.raises(OpportunityError, match=r"^M9_SOURCE_CAPABILITY_UNAVAILABLE$"):
        publication_module().ManualSealVerifier(public_key=key, verification_key_id="fixture-upload-custodian-1")


async def prepare_publication(tmp_path: Path) -> tuple[Path, dict[str, Any], Any]:
    from tests.integration.server.services.test_m9_manual_custody_isolation import issuer_process, setup_custodian

    root, request = await setup_custodian(tmp_path)
    public_root = tmp_path / "publication"
    public_root.mkdir(mode=0o700)
    module = publication_module()
    request["descriptor"].update(module.manual_publication_measurements())
    request["descriptor"]["config_digest"] = module.manual_publication_config_digest(
        public_root,
        declared_origin="synthetic-fixture",
        uploader_id="fixture-human",
        store_namespace=request["descriptor"]["store_namespace"],
        resolver_namespace=request["descriptor"]["resolver_namespace"],
    )
    (root / "authority.json").write_text(
        json.dumps({"request": request, "declared_origin": "synthetic-fixture", "uploader_id": "fixture-human"})
    )
    code, public = await issuer_process(root, "public")
    assert code == 0
    instance = module.FileManualPublicationStore(
        public_root,
        user_id="u1",
        project_name="show-a",
        verifier=module.ManualSealVerifier(
            public_key=bytes.fromhex(public["public_key"]),
            verification_key_id=request["descriptor"]["verification_key_id"],
        ),
    )
    return root, request, instance


async def publication_subject(tmp_path: Path) -> tuple[Path, dict[str, Any], Any, Any]:
    from r2.opportunity.manual_admission import PublishedAdmission
    from tests.integration.server.services.test_m9_manual_custody_isolation import issuer_process

    root, request, instance = await prepare_publication(tmp_path)
    code, result = await issuer_process(root, "admit", request=request, publication_root=str(instance.root))
    assert code == 0, result
    return root, request, PublishedAdmission.model_validate(result["publication"]), instance


def publication_access(publication: Any) -> tuple[Any, Any]:
    from datetime import UTC, datetime, timedelta

    from r2.opportunity.manual_admission import (
        AdmissionEnvelope,
        AdmissionReadPermit,
        admission_metadata_digest,
        effective_admission_deadlines,
    )
    from tests.unit.r2.opportunity.test_manual_admission import grant_for

    now = datetime.now(UTC)
    grant = grant_for([{"data_rules": [r.model_dump() for r in publication.request.data_rules]}])
    body = {
        "schema_version": "m9.manual-admission.v1",
        "request": publication.request,
        "phase": "READY",
        "version": 1,
        "claim_ref": publication.claim_ref,
        "objects": publication.objects,
        "admitted_at": now,
        "deadlines": effective_admission_deadlines(grant, publication.objects, admitted_at=now),
        "dispatch_claim": None,
    }
    envelope = AdmissionEnvelope.model_validate({**body, "metadata_digest": admission_metadata_digest(body)})
    permit = AdmissionReadPermit(
        lease_id="fixture-read",
        user_id="u1",
        project_name="show-a",
        attempt_id=publication.request.attempt_id,
        envelope_version=1,
        operational=True,
        issued_at=now,
        expires_at=now + timedelta(seconds=5),
        access_deadline=envelope.deadlines.refresh_due_at,
    )
    return envelope, permit


async def test_custodian_admit_publishes_verified_originals_and_replays(tmp_path: Path) -> None:
    from tests.integration.server.services.test_m9_manual_custody_isolation import issuer_process

    _, request, publication, instance = await publication_subject(tmp_path)
    header = await instance.lookup_receipt(publication.publication_key)
    assert header is not None
    assert header.metadata.claim_ref == publication.claim_ref
    envelope, permit = publication_access(publication)
    raw = next(obj for obj in publication.objects if obj.evidence_kind == "raw-page")
    data = await instance.read_verified(envelope, object_ref=raw.payload_ref, permit=permit)
    assert json.loads(data)["records"][0]["value"] == 125
    code, result = await issuer_process(
        tmp_path / "issuer", "admit", request=request, publication_root=str(instance.root)
    )
    assert code == 0
    assert result["publication"] == publication.model_dump(mode="json")


async def test_per_object_seal_respects_mixed_proof_rules(tmp_path: Path) -> None:
    _, _, publication, instance = await publication_subject(tmp_path)
    by_kind = {obj.evidence_kind: obj for obj in publication.objects}
    assert by_kind["raw-page"].retained_material_digest is None
    assert by_kind["native-field-1"].retained_material_digest is not None
    assert by_kind["native-field-2"].retained_material_digest is None
    assert any(obj.evidence_kind.startswith("source-identity-") for obj in publication.objects)
    header = await instance.lookup_receipt(publication.publication_key)
    assert header is not None
    assert "retained_material_digest" not in header.model_dump_json()
    envelope, permit = publication_access(publication)
    for obj in publication.objects:
        assert await instance.read_verified(envelope, object_ref=obj.payload_ref, permit=permit)


async def test_publication_physical_erasure_preserves_exact_retry_and_stops_republish(tmp_path: Path) -> None:
    from datetime import UTC, datetime

    from r2.opportunity.manual_admission import AdmissionClosureIntent
    from tests.integration.server.services.test_m9_manual_custody_isolation import issuer_process

    root, request, publication, instance = await publication_subject(tmp_path)
    refs = {publication.publication_key} | {
        ref for obj in publication.objects for ref in (obj.payload_ref, obj.integrity_ref, obj.attestation_ref)
    }
    closure = AdmissionClosureIntent(
        closure_id="fixture-closure",
        user_id="u1",
        project_name="show-a",
        attempt_id=publication.request.attempt_id,
        attempt_version=publication.request.attempt_version,
        envelope_version=2,
        phase="CLEANUP_PENDING",
        version=2,
        object_refs=tuple(refs),
        fenced_at=datetime.now(UTC),
    )
    first = await instance.delete_exact(closure)
    assert set(first.absent_refs) == refs
    assert first.retained_proofs == ()
    assert await instance.delete_exact(closure) == first
    assert await instance.lookup_receipt(publication.publication_key) is None
    envelope, permit = publication_access(publication)
    with pytest.raises(OpportunityError):
        await instance.read_verified(envelope, object_ref=publication.objects[0].payload_ref, permit=permit)
    code, _ = await issuer_process(root, "admit", request=request, publication_root=str(instance.root))
    assert code == 2
    assert (await issuer_process(root, "spend", request=request, claim_ref=publication.claim_ref))[0] == 0
    files = await asyncio.to_thread(lambda: [p.read_bytes() for p in instance.root.rglob("*") if p.is_file()])
    assert not any(b"Entirely synthetic fixture text." in data for data in files)


async def test_rewritten_payload_and_integrity_still_fail_independent_seal(tmp_path: Path) -> None:
    _, _, publication, instance = await publication_subject(tmp_path)
    raw = next(obj for obj in publication.objects if obj.evidence_kind == "raw-page")
    scope = hashlib.sha256(canonical({"user_id": "u1", "project_name": "show-a"})).hexdigest()
    base = instance.root / "manual-publications" / scope
    changed = b"CANARY_PRIVATE_MATERIAL"
    (base / "payloads" / (raw.payload_ref.rsplit(":", 1)[1] + ".bin")).write_bytes(changed)
    (base / "integrities" / (raw.integrity_ref.rsplit(":", 1)[1] + ".json")).write_bytes(
        canonical(
            {
                "payload_ref": raw.payload_ref,
                "integrity_ref": raw.integrity_ref,
                "digest": "sha256:" + hashlib.sha256(changed).hexdigest(),
            }
        )
    )
    envelope, permit = publication_access(publication)
    with pytest.raises(OpportunityError, match="M9_RAW_DIGEST_MISMATCH"):
        await instance.read_verified(envelope, object_ref=raw.payload_ref, permit=permit)


@pytest.mark.parametrize(
    "boundary",
    [
        "issuer-header-seal-durable",
        "publication-header-durable",
        "publication-payloads-durable",
        "publication-integrities-durable",
        "publication-attestations-durable",
        "publication-complete",
    ],
)
async def test_abrupt_issuer_restart_keeps_original_planned_refs(tmp_path: Path, boundary: str) -> None:
    from r2.opportunity.manual_admission import PublishedAdmission
    from tests.integration.server.services.test_m9_manual_custody_isolation import issuer_process

    root, request, instance = await prepare_publication(tmp_path)
    code, interrupted = await issuer_process(
        root, "admit", request=request, publication_root=str(instance.root), crash_at=boundary
    )
    assert code == 73
    private_header_files = await asyncio.to_thread(lambda: list(root.glob("seal-*.json")))
    assert private_header_files
    before = await instance.lookup_receipt(request["publication_key"])
    code, recovered = await issuer_process(root, "admit", request=request, publication_root=str(instance.root))
    assert code == 0
    assert recovered["pid"] != interrupted["pid"]
    publication = PublishedAdmission.model_validate(recovered["publication"])
    after = await instance.lookup_receipt(publication.publication_key)
    assert after is not None
    if before is not None:
        assert after == before
    envelope, permit = publication_access(publication)
    for obj in publication.objects:
        assert await instance.read_verified(envelope, object_ref=obj.payload_ref, permit=permit)


async def test_changed_measured_normalizer_cannot_issue_original_seals(tmp_path: Path) -> None:
    from tests.integration.server.services.test_m9_manual_custody_isolation import issuer_process

    root, request, instance = await prepare_publication(tmp_path)
    request["descriptor"]["normalizer_digest"] = "sha256:" + "b" * 64
    (root / "authority.json").write_text(
        json.dumps({"request": request, "declared_origin": "synthetic-fixture", "uploader_id": "fixture-human"})
    )
    code, result = await issuer_process(root, "admit", request=request, publication_root=str(instance.root))
    assert code == 2
    assert result == {"error": "M9_SOURCE_CAPABILITY_UNAVAILABLE"}
    assert not await asyncio.to_thread(lambda: list(root.glob("seal-*.json")))
    assert await instance.lookup_receipt(request["publication_key"]) is None


def publication_closure(publication: Any) -> Any:
    from datetime import UTC, datetime

    from r2.opportunity.manual_admission import AdmissionClosureIntent

    refs = {publication.publication_key} | {
        ref for obj in publication.objects for ref in (obj.payload_ref, obj.integrity_ref, obj.attestation_ref)
    }
    return AdmissionClosureIntent(
        closure_id="fixture-closure",
        user_id="u1",
        project_name="show-a",
        attempt_id=publication.request.attempt_id,
        attempt_version=publication.request.attempt_version,
        envelope_version=2,
        phase="CLEANUP_PENDING",
        version=2,
        object_refs=tuple(refs),
        fenced_at=datetime.now(UTC),
    )


@pytest.mark.parametrize("fault", ["issued_before_admission", "omitted_original_deadline"])
async def test_read_permit_cannot_omit_original_admission_bounds(tmp_path: Path, fault: str) -> None:
    from datetime import timedelta

    _, _, publication, instance = await publication_subject(tmp_path)
    envelope, permit = publication_access(publication)
    permit = permit.model_copy(
        update={"issued_at": envelope.admitted_at - timedelta(seconds=1)}
        if fault == "issued_before_admission"
        else {"access_deadline": None}
    )
    with pytest.raises(OpportunityError, match="M9_SOURCE_POLICY_FORBIDDEN"):
        await instance.read_verified(envelope, object_ref=publication.objects[0].payload_ref, permit=permit)


DELETION_WORKER = r"""
import asyncio,json,os,sys
from pathlib import Path
from r2.opportunity.manual_admission import AdmissionClosureIntent
from r2.opportunity.errors import OpportunityError
from server.services.m9_manual_publication import FileManualPublicationStore,ManualSealVerifier
body=json.load(sys.stdin)
def boundary(name):
    if name==body.get('crash_at'):
        os._exit(74)
def audit(event,args):
    if event=='open':
        path,mode,flags=args
        if isinstance(path,str) and Path(path).name in body['forbidden_reads'] and not flags & (os.O_WRONLY|os.O_RDWR):
            raise AssertionError('cleanup opened content or seal proof')
sys.addaudithook(audit)
store=FileManualPublicationStore(Path(body['root']),user_id='u1',project_name='show-a',boundary=boundary,
    verifier=ManualSealVerifier(public_key=bytes.fromhex(body['public_key']),verification_key_id=body['key_id']))
try:
    receipt=asyncio.run(store.delete_exact(AdmissionClosureIntent.model_validate(body['closure'])))
    print(json.dumps({'pid':os.getpid(),'receipt':receipt.model_dump(mode='json')}))
except OpportunityError as exc:
    print(json.dumps({'error':str(exc)}))
    raise SystemExit(2)
"""


async def deletion_process(
    instance: Any, publication: Any, closure: Any, crash_at: str | None = None
) -> tuple[int, dict[str, Any]]:
    body = {
        "root": str(instance.root),
        "public_key": instance.verifier.public_key.hex(),
        "key_id": instance.verifier.verification_key_id,
        "closure": closure.model_dump(mode="json"),
        "crash_at": crash_at,
        "forbidden_reads": [
            ref.rsplit(":", 1)[1] + suffix
            for obj in publication.objects
            for ref, suffix in ((obj.payload_ref, ".bin"), (obj.integrity_ref, ".json"), (obj.attestation_ref, ".json"))
        ],
    }
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        DELETION_WORKER,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate(json.dumps(body).encode())
    if process.returncode == 74 and crash_at is not None:
        return 74, {"pid": process.pid}
    assert process.returncode in (0, 2), stderr.decode()
    assert process.returncode is not None
    return process.returncode, json.loads(stdout)


@pytest.mark.parametrize(
    "boundary",
    [
        "deletion-plan-durable",
        "deletion-fence-durable",
        "deletion-attestations-durable",
        "deletion-headers-durable",
        "deletion-integrities-durable",
        "deletion-payloads-durable",
        "deletion-receipt-durable",
    ],
)
async def test_abrupt_deletion_restart_erases_exact_refs_without_reading_content(tmp_path: Path, boundary: str) -> None:
    from r2.opportunity.manual_admission import AdmissionDeletionReceipt

    _, _, publication, instance = await publication_subject(tmp_path)
    closure = publication_closure(publication)
    code, first = await deletion_process(instance, publication, closure, boundary)
    assert code == 74
    code, second = await deletion_process(instance, publication, closure)
    assert code == 0
    assert second["pid"] != first["pid"]
    receipt = AdmissionDeletionReceipt.model_validate(second["receipt"])
    assert await instance.delete_exact(closure) == receipt
    assert await instance.lookup_receipt(publication.publication_key) is None
    for category in ("payloads", "integrities", "attestations"):
        found = await asyncio.to_thread(lambda category=category: list(instance.root.rglob(category + "/*")))
        assert found == []


async def test_incomplete_closure_ref_set_cannot_delete_original_material(tmp_path: Path) -> None:
    _, _, publication, instance = await publication_subject(tmp_path)
    closure = publication_closure(publication)
    closure = closure.model_copy(
        update={"object_refs": tuple(ref for ref in closure.object_refs if ref != publication.objects[0].payload_ref)}
    )
    with pytest.raises(OpportunityError):
        await instance.delete_exact(closure)
    envelope, permit = publication_access(publication)
    assert await instance.read_verified(envelope, object_ref=publication.objects[0].payload_ref, permit=permit)


async def test_new_native_bytes_match_actual_existing_materialization_donor(tmp_path: Path) -> None:
    from r2.opportunity.acquisition import materialize_manual_page
    from server.services.m9_evidence_store import FileSnapshotEvidenceStore
    from tests.unit.r2.opportunity.test_manual_import import request, source, source_inputs

    _, _, publication, instance = await publication_subject(tmp_path)
    before = publication_module().manual_publication_measurements()
    _, grant, _ = source_inputs()
    page = await source().fetch_page(request())
    donor = FileSnapshotEvidenceStore(tmp_path / "donor", user_id="u1", project_name="show-a")
    materials = await materialize_manual_page(request(), page, grant, donor)
    assert publication_module().manual_publication_measurements() == before
    envelope, permit = publication_access(publication)
    by_kind = {obj.evidence_kind: obj for obj in publication.objects}
    assert await instance.read_verified(
        envelope, object_ref=by_kind["raw-page"].payload_ref, permit=permit
    ) == await donor.verify_and_read(materials.raw.payload_ref, materials.raw.payload_integrity_ref)
    actual = [
        (
            await instance.read_verified(envelope, object_ref=obj.payload_ref, permit=permit),
            obj.retained_material_digest,
        )
        for obj in publication.objects
        if obj.evidence_kind.startswith("native-field-")
    ]
    expected = [
        (
            await donor.verify_and_read(field.material_ref, field.material_integrity_ref),
            field.retained_normalized_value_digest,
        )
        for field in materials.fields
    ]
    assert Counter(actual) == Counter(expected)


async def test_read_uses_original_refs_after_private_ingest_path_is_removed(tmp_path: Path) -> None:
    root, _, publication, instance = await publication_subject(tmp_path)
    (root / "original.json").rename(root / "moved-original.json")
    (root / "original.json").write_bytes(b"CANARY_CURRENT_PATH_REPLACEMENT")
    envelope, permit = publication_access(publication)
    raw = next(obj for obj in publication.objects if obj.evidence_kind == "raw-page")
    material = await instance.read_verified(envelope, object_ref=raw.payload_ref, permit=permit)
    assert json.loads(material)["origin"] == "synthetic-fixture"
    assert b"CANARY_CURRENT_PATH_REPLACEMENT" not in material


async def test_forged_header_cannot_redirect_actual_physical_cleanup(tmp_path: Path) -> None:
    _, _, publication, instance = await publication_subject(tmp_path)
    target = header_path(instance.root)
    original = await asyncio.to_thread(target.read_bytes)
    forged = json.loads(original)
    forged["metadata"]["objects"][0]["payload_ref"] = "m9-manual-payload:" + "f" * 32
    forged["metadata_digest"] = (
        "sha256:" + hashlib.sha256(b"m9.manual-publication-metadata.v1\x00" + canonical(forged["metadata"])).hexdigest()
    )
    target.write_bytes(canonical(forged))
    with pytest.raises(OpportunityError, match="M9_RAW_DIGEST_MISMATCH"):
        await instance.delete_exact(publication_closure(publication))
    target.write_bytes(original)
    envelope, permit = publication_access(publication)
    for obj in publication.objects:
        assert await instance.read_verified(envelope, object_ref=obj.payload_ref, permit=permit)


async def test_original_issuer_header_recovery_never_allocates_successor_refs(tmp_path: Path) -> None:
    from tests.integration.server.services.test_m9_manual_custody_isolation import issuer_process

    root, request, publication, instance = await publication_subject(tmp_path)
    original = await instance.lookup_receipt(publication.publication_key)
    header_path(instance.root).unlink()
    code, result = await issuer_process(root, "admit", request=request, publication_root=str(instance.root))
    assert code == 0
    assert result["publication"] == publication.model_dump(mode="json")
    assert await instance.lookup_receipt(publication.publication_key) == original

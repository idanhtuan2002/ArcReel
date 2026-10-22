"""Custodian-owned upload claims persist across fresh issuer processes."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest

from tests.unit.r2.opportunity.test_manual_admission import request_data, rule_data

ISSUER = "tests.fixtures.r2.opportunity.manual_admission_custodian"
WORKER = r"""
import json,sys
from pathlib import Path
from tests.fixtures.r2.opportunity.manual_admission_custodian import FixtureManualUploadCustodian
from r2.opportunity.manual_admission import AdmissionRequest
from r2.opportunity.errors import OpportunityError
issuer=FixtureManualUploadCustodian(Path(sys.argv[1]))
body=json.load(sys.stdin)
try:
    if body.get('deny_material_read'):
        def audit(event,args):
            if event=='open':
                path,mode,flags=args
                if isinstance(path,str) and (path=='original.json' or path.startswith('material-')) and not flags & (os.O_WRONLY|os.O_RDWR):
                    raise AssertionError('spent cleanup opened content')
        import os
        sys.addaudithook(audit)
    if body.get('deny_spend_content_read'):
        import os,hashlib
        header_suffix='.'+hashlib.sha256(b'header').hexdigest()+'.json'
        def audit_spend(event,args):
            if event=='open':
                path,mode,flags=args
                if isinstance(path,str) and not flags & (os.O_WRONLY|os.O_RDWR):
                    name=os.path.basename(path)
                    if name=='original.json' or name.startswith('material-') or (name.startswith('seal-') and not name.endswith(header_suffix)) or (name.startswith('.rollback.') and name.endswith('.tmp')):
                        raise AssertionError('private spend opened content or material seal')
        sys.addaudithook(audit_spend)
    if body['operation']=='public':
        result={'public_key':issuer.public_key.hex()}
    elif body['operation']=='claim':
        result={'claim_ref':issuer.claim_original(AdmissionRequest.model_validate(body['request']))}
    elif body['operation']=='admit':
        import asyncio
        def boundary(name):
            if body.get('crash_at')==name:
                __import__('os')._exit(73)
        issuer=FixtureManualUploadCustodian(Path(sys.argv[1]),publication_root=Path(body['publication_root']),boundary=boundary)
        result={'publication':asyncio.run(issuer.admit(AdmissionRequest.model_validate(body['request']))).model_dump(mode='json')}
    elif body['operation']=='close':
        def boundary(name):
            if body.get('crash_at')==name:
                __import__('os')._exit(73)
        issuer=FixtureManualUploadCustodian(Path(sys.argv[1]),boundary=boundary)
        result={'receipt':issuer.close_original(AdmissionRequest.model_validate(body['request']),claim_ref=body['claim_ref'],closure_id=body['closure_id']).model_dump(mode='json')}
    else:
        issuer.mark_spent(AdmissionRequest.model_validate(body['request']),claim_ref=body['claim_ref'])
        result={'spent':True}
    result['pid']=__import__('os').getpid()
    print(json.dumps(result))
except OpportunityError as exc:
    print(json.dumps({'error':str(exc)}))
    raise SystemExit(2)
"""


async def issuer_process(root: Path, operation: str, **body: object) -> tuple[int, dict[str, Any]]:
    assert importlib.util.find_spec(ISSUER) is not None, "T4 original upload custodian missing"
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        WORKER,
        str(root),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate(json.dumps({"operation": operation, **body}).encode())
    if process.returncode == 73 and body.get("crash_at") is not None:
        return 73, {"crashed": True, "pid": process.pid}
    assert process.returncode in (0, 2), stderr.decode()
    assert process.returncode is not None
    return process.returncode, json.loads(stdout)


async def setup_custodian(tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    root = tmp_path / "issuer"
    root.mkdir(mode=0o700)
    code, public = await issuer_process(root, "public")
    assert code == 0
    request = request_data()
    request["descriptor"]["verification_key_digest"] = (
        "sha256:" + hashlib.sha256(bytes.fromhex(public["public_key"])).hexdigest()
    )
    now = datetime.now(UTC)
    classes = ("manual-excerpt", "manual-public-metadata")
    request["data_rules"] = [rule_data(name) for name in classes]
    request["original_clocks"] = [
        {
            "data_class": name,
            "captured_at": now.isoformat(),
            "refresh_due_at": (now + timedelta(seconds=30)).isoformat(),
            "retention_due_at": (now + timedelta(seconds=90)).isoformat(),
        }
        for name in classes
    ]
    fixture = await asyncio.to_thread(Path("tests/fixtures/r2/opportunity/manual_import.json").read_bytes)
    (root / "original.json").write_bytes(fixture)
    (root / "original.json").chmod(0o600)
    (root / "authority.json").write_text(
        json.dumps({"request": request, "declared_origin": "synthetic-fixture", "uploader_id": "fixture-human"})
    )
    (root / "authority.json").chmod(0o600)
    return root, request


async def test_equal_and_conflicting_upload_claims_across_processes(tmp_path: Path) -> None:
    root, request = await setup_custodian(tmp_path)
    results = await asyncio.gather(*(issuer_process(root, "claim", request=request) for _ in range(4)))
    assert all(code == 0 for code, _ in results)
    claims = {body["claim_ref"] for _, body in results}
    assert len(claims) == 1
    assert len({body["pid"] for _, body in results}) == 4
    replay = json.loads(json.dumps(request))
    replay["attempt_id"] = "019a0000-0000-7000-8000-000000000002"
    replay["context"]["command_id"] = replay["attempt_id"]
    replay["publication_key"] = "another-publication"
    code, result = await issuer_process(root, "claim", request=replay)
    assert code == 0
    assert result["claim_ref"] in claims
    original = root / "original.json"
    original.write_bytes(original.read_bytes().replace(b'"value": 125', b'"value": 126'))
    code, result = await issuer_process(root, "claim", request=replay)
    assert code == 2
    assert result == {"error": "M9_COMMAND_REPLAY_CONFLICT"}


async def test_spent_upload_version_cannot_be_reissued(tmp_path: Path) -> None:
    root, request = await setup_custodian(tmp_path)
    code, result = await issuer_process(root, "claim", request=request)
    assert code == 0
    claim = result["claim_ref"]
    code, result = await issuer_process(root, "spend", request=request, claim_ref=claim)
    assert code == 0
    assert not await asyncio.to_thread((root / "original.json").exists)
    names = await asyncio.to_thread(lambda: [p.name for p in root.iterdir()])
    assert not any(name.startswith("material-") for name in names)
    tombstones = await asyncio.to_thread(lambda: {p.name: p.read_bytes() for p in root.glob("upload-*.json")})
    assert len(tombstones) == 1
    assert b"SPENT" in next(iter(tombstones.values()))
    assert b"Entirely synthetic" not in next(iter(tombstones.values()))
    code, result = await issuer_process(root, "claim", request=request)
    assert code == 2
    assert result == {"error": "M9_EVIDENCE_RETENTION_EXPIRED"}
    code, _ = await issuer_process(root, "spend", request=request, claim_ref=claim)
    assert code == 0
    assert tombstones == await asyncio.to_thread(lambda: {p.name: p.read_bytes() for p in root.glob("upload-*.json")})


async def test_changed_original_policy_or_command_is_refused(tmp_path: Path) -> None:
    root, request = await setup_custodian(tmp_path)
    assert (await issuer_process(root, "claim", request=request))[0] == 0
    command = json.loads(json.dumps(request))
    command["query_revision"] = 2
    code, result = await issuer_process(root, "claim", request=command)
    assert code == 2
    assert result == {"error": "M9_COMMAND_REPLAY_CONFLICT"}
    command = json.loads(json.dumps(request))
    command["descriptor"]["normalizer_digest"] = "sha256:" + "b" * 64
    code, result = await issuer_process(root, "claim", request=command)
    assert code == 2
    assert result == {"error": "M9_SOURCE_POLICY_FORBIDDEN"}


async def test_custodian_files_are_private_and_symlink_root_refused(tmp_path: Path) -> None:
    root, request = await setup_custodian(tmp_path)
    assert (await issuer_process(root, "claim", request=request))[0] == 0
    files = await asyncio.to_thread(lambda: list(root.iterdir()))
    assert all(p.stat().st_mode & 0o077 == 0 for p in files)
    alias = tmp_path / "alias"
    alias.symlink_to(root, target_is_directory=True)
    code, result = await issuer_process(alias, "claim", request=request)
    assert code == 2
    assert result == {"error": "M9_RAW_DIGEST_MISMATCH"}


@pytest.mark.parametrize(
    "fault", ["key_missing", "index_missing", "comparison_missing", "authority_symlink", "key_mode", "key_hardlink"]
)
async def test_missing_or_replaced_original_authority_never_reissues(tmp_path: Path, fault: str) -> None:
    root, request = await setup_custodian(tmp_path)
    assert (await issuer_process(root, "claim", request=request))[0] == 0
    if fault == "key_missing":
        (root / "issuer.key").unlink()
    elif fault == "index_missing":
        next(root.glob("upload-*.json")).unlink()
    elif fault == "comparison_missing":
        next(root.glob("material-*.json")).unlink()
    elif fault == "authority_symlink":
        authority = root / "authority.json"
        authority.rename(root / "authority.saved")
        authority.symlink_to(root / "authority.saved")
    elif fault == "key_mode":
        (root / "issuer.key").chmod(0o640)
    else:
        (root / "another-key").hardlink_to(root / "issuer.key")
    code, result = await issuer_process(root, "claim", request=request)
    assert code == 2
    assert result["error"] in ("M9_RAW_DIGEST_MISMATCH", "M9_COMMAND_REPLAY_CONFLICT")


async def docker_command(*argv: str) -> tuple[int, bytes, bytes]:
    process = await asyncio.create_subprocess_exec(
        "docker", *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, stderr = await process.communicate()
    assert process.returncode is not None
    return process.returncode, stdout, stderr


async def test_separate_uid_store_writer_cannot_read_issuer_key_or_ledger(tmp_path: Path) -> None:
    container = "arcreel-m9b-disposable-20261019"
    code, stdout, stderr = await docker_command("inspect", container)
    assert code == 0, stderr.decode()
    info = json.loads(stdout)[0]
    assert info["Id"] == "9cf1d8726ff1198a2749985ccde704c2774e380f7649fb0a741ab1e501c04b03"
    assert info["State"]["Running"] is True
    assert info["Config"]["Labels"]["arcreel.disposable"] == "true"
    assert info["Config"]["Labels"]["arcreel.scope"] == "m9b-disposable-test"
    root, request = await setup_custodian(tmp_path)
    assert (await issuer_process(root, "claim", request=request))[0] == 0
    ledger = await asyncio.to_thread(lambda: next(root.glob("upload-*.json")).name)
    owner = uuid4().hex
    scratch = "/tmp/m9b-custody-" + owner
    setup = 'mkdir -m 711 "$1" && printf %s "$2" > "$1/.m9b-test-owner" && mkdir -m 700 "$1/publication" && chown 31002:31002 "$1/publication"'
    code, _, stderr = await docker_command("exec", "--user", "0", container, "sh", "-c", setup, "sh", scratch, owner)
    assert code == 0, stderr.decode()
    try:
        code, _, stderr = await docker_command("cp", str(root), container + ":" + scratch + "/issuer")
        assert code == 0, stderr.decode()
        code, _, stderr = await docker_command(
            "exec", "--user", "0", container, "chown", "-R", "31001:31001", scratch + "/issuer"
        )
        assert code == 0, stderr.decode()
        read = 'test "$(id -u)" = "$2" && cat "$1/issuer/issuer.key" > /dev/null && cat "$1/issuer/$3" > /dev/null'
        code, _, stderr = await docker_command(
            "exec", "--user", "31001:31001", container, "sh", "-c", read, "sh", scratch, "31001", ledger
        )
        assert code == 0, stderr.decode()
        writer = 'test "$(id -u)" = 31002 && printf writable > "$1/publication/probe" && ! cat "$1/issuer/issuer.key" > /dev/null 2>&1 && ! cat "$1/issuer/$2" > /dev/null 2>&1'
        code, _, stderr = await docker_command(
            "exec", "--user", "31002:31002", container, "sh", "-c", writer, "sh", scratch, ledger
        )
        assert code == 0, stderr.decode()
    finally:
        cleanup = 'test "$(cat "$1/.m9b-test-owner")" = "$2" && rm -rf -- "$1"'
        code, _, stderr = await docker_command(
            "exec", "--user", "0", container, "sh", "-c", cleanup, "sh", scratch, owner
        )
        assert code == 0, stderr.decode()


@pytest.mark.parametrize("shape", ["zero", "missing"])
async def test_claim_preserves_original_zero_and_missingness_material(tmp_path: Path, shape: str) -> None:
    root, request = await setup_custodian(tmp_path)
    original = root / "original.json"
    body = json.loads(await asyncio.to_thread(original.read_bytes))
    record = body["records"][0]
    if shape == "zero":
        record["value"] = 0
    else:
        del record["value"]
        record["missing_reason"] = "NOT_RETURNED"
    original.write_text(json.dumps(body))
    code, first = await issuer_process(root, "claim", request=request)
    assert code == 0
    code, replay = await issuer_process(root, "claim", request=request)
    assert code == 0
    assert replay["claim_ref"] == first["claim_ref"]


async def test_spent_cleanup_reads_no_original_or_comparison_content(tmp_path: Path) -> None:
    root, request = await setup_custodian(tmp_path)
    code, first = await issuer_process(root, "claim", request=request)
    assert code == 0
    code, _ = await issuer_process(
        root, "spend", request=request, claim_ref=first["claim_ref"], deny_material_read=True
    )
    assert code == 0


async def test_interrupted_material_erasure_keeps_spent_fence_and_exact_retry(tmp_path: Path) -> None:
    root, request = await setup_custodian(tmp_path)
    code, first = await issuer_process(root, "claim", request=request)
    assert code == 0
    original = root / "original.json"
    original.unlink()
    original.mkdir(mode=0o700)
    code, result = await issuer_process(root, "spend", request=request, claim_ref=first["claim_ref"])
    assert code == 2
    assert result == {"error": "M9_RAW_DIGEST_MISMATCH"}
    code, result = await issuer_process(root, "claim", request=request)
    assert code == 2
    assert result == {"error": "M9_EVIDENCE_RETENTION_EXPIRED"}
    tombstone = await asyncio.to_thread(lambda: next(root.glob("upload-*.json")).read_bytes())
    original.rmdir()
    code, _ = await issuer_process(root, "spend", request=request, claim_ref=first["claim_ref"])
    assert code == 0
    assert tombstone == await asyncio.to_thread(lambda: next(root.glob("upload-*.json")).read_bytes())


async def test_spent_cleanup_erases_interrupted_atomic_write_comparison(tmp_path: Path) -> None:
    root, request = await setup_custodian(tmp_path)
    code, first = await issuer_process(root, "claim", request=request)
    assert code == 0
    temporary = root / ".rollback.interrupted.tmp"
    temporary.write_bytes(b"CANARY_ORPHANED_COMPARISON")
    temporary.chmod(0o600)
    code, _ = await issuer_process(root, "spend", request=request, claim_ref=first["claim_ref"])
    assert code == 0
    assert not await asyncio.to_thread(temporary.exists)


async def test_expired_original_clock_refuses_before_material_read(tmp_path: Path) -> None:
    root, request = await setup_custodian(tmp_path)
    past = datetime.now(UTC) - timedelta(minutes=10)
    for clock in request["original_clocks"]:
        clock.update(
            captured_at=past.isoformat(),
            refresh_due_at=(past + timedelta(seconds=30)).isoformat(),
            retention_due_at=(past + timedelta(seconds=90)).isoformat(),
        )
    (root / "authority.json").write_text(
        json.dumps({"request": request, "declared_origin": "synthetic-fixture", "uploader_id": "fixture-human"})
    )
    code, result = await issuer_process(root, "claim", request=request, deny_material_read=True)
    assert code == 2
    assert result == {"error": "M9_EVIDENCE_RETENTION_EXPIRED"}


@pytest.mark.parametrize("fault", ["claim_nonce", "boolean_version"])
async def test_mutated_index_cannot_become_original_authority_for_new_command(tmp_path: Path, fault: str) -> None:
    root, request = await setup_custodian(tmp_path)
    assert (await issuer_process(root, "claim", request=request))[0] == 0
    index_path = await asyncio.to_thread(lambda: next(root.glob("upload-*.json")))
    index = json.loads(await asyncio.to_thread(index_path.read_bytes))
    if fault == "claim_nonce":
        index["claim_ref"] = "m9-upload-claim:NOT_AN_ORIGINAL_NONCE"
    else:
        index["identity"]["upload_version"] = True
    index_path.write_text(json.dumps(index, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    replay = json.loads(json.dumps(request))
    replay["attempt_id"] = "019a0000-0000-7000-8000-000000000002"
    replay["context"]["command_id"] = replay["attempt_id"]
    replay["publication_key"] = "another-publication"
    code, result = await issuer_process(root, "claim", request=replay)
    assert code == 2
    assert result == {"error": "M9_RAW_DIGEST_MISMATCH"}


async def private_spend_subject(tmp_path: Path, *, expired=False):
    from importlib import import_module

    from tests.integration.server.services.test_m9_manual_publication import prepare_publication

    assert hasattr(import_module(ISSUER).FixtureManualUploadCustodian, "close_original"), (
        "T7 private spending receipt missing"
    )
    root, request, instance = await prepare_publication(tmp_path)
    if expired:
        now = datetime.now(UTC)
        for clock in request["original_clocks"]:
            clock.update(
                captured_at=now.isoformat(),
                refresh_due_at=(now + timedelta(seconds=6)).isoformat(),
                retention_due_at=(now + timedelta(seconds=6)).isoformat(),
            )
        (root / "authority.json").write_text(
            json.dumps({"request": request, "declared_origin": "synthetic-fixture", "uploader_id": "fixture-human"})
        )
    code, result = await issuer_process(root, "admit", request=request, publication_root=str(instance.root))
    assert code == 0, result
    if expired:
        deadline = datetime.fromisoformat(request["original_clocks"][0]["retention_due_at"])
        await asyncio.sleep(max(0, (deadline - datetime.now(UTC)).total_seconds()) + 0.01)
    return root, request, result["publication"], instance


@pytest.mark.parametrize("expired", [False, True])
async def test_private_spend_receipt_is_original_metadata_only_and_replays_across_processes(tmp_path: Path, expired):
    from importlib import import_module

    from r2.advanced_creative.digests import canonical_json_bytes
    from r2.opportunity.manual_admission import AdmissionRequest

    root, request, publication, instance = await private_spend_subject(tmp_path, expired=expired)
    code, first = await issuer_process(
        root,
        "close",
        request=request,
        claim_ref=publication["claim_ref"],
        closure_id="fixture-logical-closure",
        deny_spend_content_read=True,
    )
    assert code == 0, first
    verify = import_module("server.services.m9_manual_publication").verify_custodian_spent
    receipt = verify(
        canonical_json_bytes(first["receipt"]),
        public_key=instance.verifier.public_key,
        expected_request=AdmissionRequest.model_validate(request),
        closure_id="fixture-logical-closure",
    )
    assert receipt.metadata.root_request == AdmissionRequest.model_validate(request)
    assert receipt.metadata.claim_ref == publication["claim_ref"]
    assert receipt.metadata.deleted_at >= receipt.metadata.spent_at
    assert len(receipt.metadata.publications) == 1
    original = receipt.metadata.publications[0]
    assert original.state == "ORIGINAL_HEADER"
    assert original.header.metadata.publication_key == request["publication_key"]
    assert "material_digest" not in receipt.model_dump_json()
    assert "Entirely synthetic fixture text." not in receipt.model_dump_json()
    assert not (root / "original.json").exists()
    assert not list(root.glob("material-*.json"))
    assert not list(root.glob("seal-*.json"))
    assert await instance.lookup_receipt(request["publication_key"]) == original.header
    code, replay = await issuer_process(
        root,
        "close",
        request=request,
        claim_ref=publication["claim_ref"],
        closure_id="fixture-logical-closure",
        deny_spend_content_read=True,
    )
    assert code == 0
    assert replay["receipt"] == first["receipt"]
    assert replay["pid"] != first["pid"]
    code, refused = await issuer_process(root, "admit", request=request, publication_root=str(instance.root))
    assert code == 2
    assert refused == {"error": "M9_EVIDENCE_RETENTION_EXPIRED"}


@pytest.mark.parametrize("fault", ["closure", "signature", "key", "noncanonical", "duplicate"])
async def test_store_owner_cannot_forge_private_spending_receipt(tmp_path: Path, fault):
    from importlib import import_module

    from r2.advanced_creative.digests import canonical_json_bytes
    from r2.opportunity.errors import OpportunityError
    from r2.opportunity.manual_admission import AdmissionRequest

    root, request, publication, instance = await private_spend_subject(tmp_path)
    code, result = await issuer_process(
        root, "close", request=request, claim_ref=publication["claim_ref"], closure_id="fixture-logical-closure"
    )
    assert code == 0
    body = result["receipt"]
    key = instance.verifier.public_key
    if fault == "closure":
        body["metadata"]["closure_id"] = "different-closure"
        metadata = import_module("r2.opportunity.acquisition_v2").CustodianSpendMetadata.model_validate(
            body["metadata"]
        )
        body["metadata_digest"] = import_module("r2.opportunity.acquisition_v2").custodian_spend_metadata_digest(
            metadata
        )
    elif fault == "signature":
        body["signature"] = "A" * 86
    elif fault == "key":
        key = b"0" * 32
    raw = canonical_json_bytes(body)
    if fault == "noncanonical":
        raw = json.dumps(body, indent=2).encode()
    elif fault == "duplicate":
        raw = raw[:-1] + b',"signature":' + json.dumps(body["signature"]).encode() + b"}"
    verify = import_module("server.services.m9_manual_publication").verify_custodian_spent
    with pytest.raises(OpportunityError, match="M9_RAW_DIGEST_MISMATCH"):
        verify(
            raw,
            public_key=key,
            expected_request=AdmissionRequest.model_validate(request),
            closure_id="fixture-logical-closure",
        )


@pytest.mark.parametrize("fault", ["header", "upload", "unissued"])
async def test_invalid_private_closure_inventory_refuses_before_original_erasure(tmp_path: Path, fault):
    from r2.advanced_creative.digests import canonical_json_bytes
    from r2.opportunity.manual_admission import PublicationReceiptMetadata, publication_metadata_digest

    root, request, publication, _ = await private_spend_subject(tmp_path)
    code, crashed = await issuer_process(
        root,
        "close",
        request=request,
        claim_ref=publication["claim_ref"],
        closure_id="fixture-logical-closure",
        crash_at="custodian-spend-plan-durable",
    )
    assert code == 73
    assert crashed["crashed"]
    paths = list(root.glob("closure-*.json"))
    assert len(paths) == 1
    body = json.loads(paths[0].read_bytes())
    if fault == "header":
        header = body["publications"][0]["header"]
        header["metadata"]["objects"][0]["payload_ref"] = "m9-manual-payload:" + "f" * 32
        header["metadata_digest"] = publication_metadata_digest(
            PublicationReceiptMetadata.model_validate(header["metadata"])
        )
    elif fault == "upload":
        body["publications"][0]["request"]["opaque_upload_id"] = "different-original-upload"
    else:
        body["publications"][0].update(state="NEVER_ISSUED", header=None)
    paths[0].write_bytes(canonical_json_bytes(body))
    code, refused = await issuer_process(
        root,
        "close",
        request=request,
        claim_ref=publication["claim_ref"],
        closure_id="fixture-logical-closure",
        deny_spend_content_read=True,
    )
    assert code == 2
    assert refused == {"error": "M9_RAW_DIGEST_MISMATCH"}
    assert (root / "original.json").exists()
    assert list(root.glob("material-*.json"))
    indexes = list(root.glob("upload-*.json"))
    assert len(indexes) == 1
    assert json.loads(indexes[0].read_bytes())["phase"] == "ACTIVE"


@pytest.mark.parametrize(
    "boundary",
    [
        "custodian-spend-plan-durable",
        "custodian-spent-fence-durable",
        "custodian-original-unlinked",
        "custodian-comparison-unlinked",
        "custodian-header-unlinked",
        "custodian-material-seal-unlinked",
        "custodian-spend-receipt-durable",
    ],
)
async def test_private_spending_restart_keeps_original_inventory_and_stable_tombstone(tmp_path: Path, boundary):
    from importlib import import_module

    from r2.advanced_creative.digests import canonical_json_bytes
    from r2.opportunity.manual_admission import AdmissionRequest

    root, request, publication, instance = await private_spend_subject(tmp_path)
    header = await instance.lookup_receipt(request["publication_key"])
    code, crashed = await issuer_process(
        root,
        "close",
        request=request,
        claim_ref=publication["claim_ref"],
        closure_id="fixture-logical-closure",
        crash_at=boundary,
        deny_spend_content_read=True,
    )
    assert code == 73
    assert crashed["crashed"]
    code, recovered = await issuer_process(
        root,
        "close",
        request=request,
        claim_ref=publication["claim_ref"],
        closure_id="fixture-logical-closure",
        deny_spend_content_read=True,
    )
    assert code == 0, recovered
    assert recovered["pid"] != crashed["pid"]
    receipt = import_module("server.services.m9_manual_publication").verify_custodian_spent(
        canonical_json_bytes(recovered["receipt"]),
        public_key=instance.verifier.public_key,
        expected_request=AdmissionRequest.model_validate(request),
        closure_id="fixture-logical-closure",
    )
    assert receipt.metadata.publications[0].header == header
    assert not (root / "original.json").exists()
    assert not list(root.glob("material-*.json"))
    assert not list(root.glob("seal-*.json"))
    code, replay = await issuer_process(
        root,
        "close",
        request=request,
        claim_ref=publication["claim_ref"],
        closure_id="fixture-logical-closure",
        deny_spend_content_read=True,
    )
    assert code == 0
    assert replay["receipt"] == recovered["receipt"]
    if boundary == "custodian-spend-receipt-durable":
        paths = list(root.glob("closure-*.json"))
        assert len(paths) == 1
        assert json.loads(paths[0].read_bytes())["receipt"] == recovered["receipt"]


@pytest.mark.parametrize("new_command", [False, True])
async def test_combined_original_ledger_loss_never_reissues_under_another_command(tmp_path: Path, new_command):
    root, request = await setup_custodian(tmp_path)
    code, original = await issuer_process(root, "claim", request=request)
    assert code == 0
    assert original["claim_ref"].startswith("m9-upload-claim:")
    for path in (*root.glob("upload-*.json"), *root.glob("material-*.json")):
        path.unlink()
    retry = json.loads(json.dumps(request))
    if new_command:
        retry["context"]["command_id"] = "019a0000-0000-7000-8000-000000000099"
        retry["attempt_id"] = retry["context"]["command_id"]
        retry["publication_key"] = "other-original-publication"
    code, result = await issuer_process(root, "claim", request=retry)
    assert code == 2
    assert result["error"] in ("M9_RAW_DIGEST_MISMATCH", "M9_COMMAND_REPLAY_CONFLICT")
    assert not list(root.glob("upload-*.json"))
    assert not list(root.glob("material-*.json"))


@pytest.mark.parametrize("retain_custody", [False, True])
async def test_total_original_ledger_loss_never_becomes_a_fresh_upload(tmp_path: Path, retain_custody):
    root, request = await setup_custodian(tmp_path)
    assert (await issuer_process(root, "claim", request=request))[0] == 0
    for pattern in ("upload-*.json", "material-*.json", "command-*.json", "seal-*.json", "closure-*.json"):
        for path in root.glob(pattern):
            path.unlink()
    if not retain_custody:
        (root / "custody.json").unlink(missing_ok=True)
    retry = json.loads(json.dumps(request))
    retry["context"]["command_id"] = "019a0000-0000-7000-8000-000000000098"
    retry["attempt_id"] = retry["context"]["command_id"]
    retry["publication_key"] = "other-original-after-loss"
    code, result = await issuer_process(root, "claim", request=retry)
    assert code == 2
    assert result["error"] in ("M9_RAW_DIGEST_MISMATCH", "M9_COMMAND_REPLAY_CONFLICT")
    assert not list(root.glob("upload-*.json"))


async def test_never_claimed_original_can_be_spent_without_content_or_a_fabricated_claim(tmp_path: Path):
    from importlib import import_module

    from r2.advanced_creative.digests import canonical_json_bytes
    from r2.opportunity.manual_admission import AdmissionRequest
    from tests.integration.server.services.test_m9_manual_publication import prepare_publication

    root, request, instance = await prepare_publication(tmp_path)
    assert not list(root.glob("upload-*.json"))
    assert await instance.lookup_receipt(request["publication_key"]) is None
    code, result = await issuer_process(
        root,
        "close",
        request=request,
        claim_ref=None,
        closure_id="unpublished-logical-closure",
        deny_spend_content_read=True,
    )
    assert code == 0, result
    receipt = import_module("server.services.m9_manual_publication").verify_custodian_spent(
        canonical_json_bytes(result["receipt"]),
        public_key=instance.verifier.public_key,
        expected_request=AdmissionRequest.model_validate(request),
        closure_id="unpublished-logical-closure",
    )
    assert receipt.metadata.claim_ref is None
    assert receipt.metadata.inventory_complete
    assert receipt.metadata.publications[0].state == "NEVER_ISSUED"
    assert receipt.metadata.publications[0].header is None
    assert not (root / "original.json").exists()
    assert not list(root.glob("upload-*.json"))
    code, refused = await issuer_process(root, "claim", request=request)
    assert code == 2
    assert refused == {"error": "M9_EVIDENCE_RETENTION_EXPIRED"}


@pytest.mark.parametrize("lost", ["plan", "plan-key", "plan-index"])
async def test_completed_private_receipt_survives_lost_plan_without_renewal(tmp_path: Path, lost):
    root, request, publication, _ = await private_spend_subject(tmp_path)
    options = {
        "request": request,
        "claim_ref": publication["claim_ref"],
        "closure_id": "fixture-logical-closure",
        "deny_spend_content_read": True,
    }
    code, original = await issuer_process(root, "close", **options)
    assert code == 0
    for path in root.glob("closure-*.json"):
        path.unlink()
    if lost == "plan-key":
        (root / "issuer.key").unlink()
    elif lost == "plan-index":
        for path in root.glob("upload-*.json"):
            path.unlink()
    code, recovered = await issuer_process(root, "close", **options)
    assert code == 0, recovered
    assert original["pid"] != recovered["pid"]
    assert recovered["receipt"] == original["receipt"]


@pytest.mark.parametrize("retained", ["custody", "none"])
async def test_private_spending_after_original_metadata_loss_requires_positive_history(tmp_path: Path, retained):
    root, request, publication, _ = await private_spend_subject(tmp_path)
    for pattern in ("upload-*.json", "command-*.json", "seal-*.json"):
        for path in root.glob(pattern):
            path.unlink()
    if retained == "none":
        (root / "custody.json").unlink()
    code, result = await issuer_process(
        root,
        "close",
        request=request,
        claim_ref=publication["claim_ref"],
        closure_id="fixture-logical-closure",
        deny_spend_content_read=True,
    )
    if retained == "none":
        assert code == 2
        assert result == {"error": "M9_RAW_DIGEST_MISMATCH"}
        assert (root / "original.json").exists()
        assert list(root.glob("material-*.json"))
        assert not list(root.glob("upload-*.json"))
    else:
        assert code == 0, result
        assert result["receipt"]["metadata"]["claim_ref"] == publication["claim_ref"]
        assert result["receipt"]["metadata"]["inventory_complete"]
        assert result["receipt"]["metadata"]["publications"][0]["state"] == "ORIGINAL_HEADER"
        assert not (root / "original.json").exists()
        assert not list(root.glob("material-*.json"))
        index = json.loads(next(root.glob("upload-*.json")).read_bytes())
        assert index["phase"] == "SPENT"
        assert index["claim_ref"] == publication["claim_ref"]


async def test_cached_private_receipt_refuses_reappeared_material_without_reading_it(tmp_path: Path):
    root, request, publication, _ = await private_spend_subject(tmp_path)
    options = {
        "request": request,
        "claim_ref": publication["claim_ref"],
        "closure_id": "fixture-logical-closure",
        "deny_spend_content_read": True,
    }
    code, first = await issuer_process(root, "close", **options)
    assert code == 0
    original = root / "original.json"
    original.write_bytes(b"REAPPEARED_PRIVATE_CANARY")
    original.chmod(0o600)
    code, refused = await issuer_process(root, "close", **options)
    assert code == 2
    assert refused == {"error": "M9_RAW_DIGEST_MISMATCH"}
    assert original.read_bytes() == b"REAPPEARED_PRIVATE_CANARY"
    assert json.loads((root / "custody.json").read_bytes())["receipt"] == first["receipt"]

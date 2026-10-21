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
    if body['operation']=='public':
        result={'public_key':issuer.public_key.hex()}
    elif body['operation']=='claim':
        result={'claim_ref':issuer.claim_original(AdmissionRequest.model_validate(body['request']))}
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

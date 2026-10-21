"""Original signed headers remain discoverable without opening expired material."""

from __future__ import annotations

import asyncio
import hashlib
import importlib
import importlib.util
import json
import os
import sys
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

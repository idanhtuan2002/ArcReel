"""Relocated metadata keeps existing schemas, serialized bodies and legacy aliases."""

from __future__ import annotations

import hashlib
import json

from r2.contracts.artifact_metadata import ApprovedMasterMetadata, DependencySnapshot, R2ArtifactMetadata, R2ContractRef

SCHEMA_HASHES = {
    "R2ContractRef": "9be5b08773bac123c7ab15e9e9e610ef0edf4ad56196731dbf6ea127628ae9ae",
    "DependencySnapshot": "4b471d583aaf977c89dcf012262bb5ff0e210582c80a11b3c17f4b5bf0784f93",
    "ApprovedMasterMetadata": "5cb848826ff65a91446032614205f855e53e3e7c0bdcc841f299e9dd7cb88162",
    "R2ArtifactMetadata": "ad446f57d8eb9ebe5fcaef92cb2967e220a112e9e53a52a011acdc5dd6d5d45a",
}
INPUT = {
    "metadata_schema_version": "1",
    "contract_ref": {"contract_type": "ShotSpec", "id": "SH042", "version": 4, "schema_version": "2.1"},
    "content_basis": {"basis_type": "NARRATIVE", "basis_version": "canon-v7", "refs": ["event:1"]},
    "direct_dependencies": [
        {
            "ref": "binding:B02",
            "version": "5",
            "fingerprint": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        },
        {
            "ref": "binding:B01",
            "version": "2",
            "fingerprint": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        },
    ],
    "content_fingerprint": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
}
EXPECTED = {
    "metadata_schema_version": "1",
    "contract_ref": {"contract_type": "ShotSpec", "id": "SH042", "version": 4, "schema_version": "2.1"},
    "content_basis": {"basis_type": "NARRATIVE", "basis_version": "canon-v7", "refs": ["event:1"]},
    "direct_dependencies": [
        {
            "ref": "binding:B01",
            "version": "2",
            "fingerprint": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        },
        {
            "ref": "binding:B02",
            "version": "5",
            "fingerprint": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        },
    ],
    "content_fingerprint": "cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc",
    "approved_master": None,
}


def test_legacy_imports_reexport_identical_class_objects() -> None:
    from r2.production import artifact_metadata as legacy

    for cls in [R2ContractRef, DependencySnapshot, ApprovedMasterMetadata, R2ArtifactMetadata]:
        assert getattr(legacy, cls.__name__) is cls


def test_public_json_schemas_match_frozen_pre_extraction_hashes() -> None:
    for cls in [R2ContractRef, DependencySnapshot, ApprovedMasterMetadata, R2ArtifactMetadata]:
        body = json.dumps(cls.model_json_schema(), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        assert hashlib.sha256(body).hexdigest() == SCHEMA_HASHES[cls.__name__]


def test_normalized_json_body_matches_frozen_pre_extraction_fixture() -> None:
    assert R2ArtifactMetadata.model_validate(INPUT).model_dump(mode="json") == EXPECTED

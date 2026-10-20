"""Independent material seals reject substitutions without exposing protected input."""

from __future__ import annotations

import base64
import hashlib
import importlib
import importlib.util
import json
import traceback
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import ValidationError

from r2.opportunity.errors import OpportunityError

ID = "019a0000-0000-7000-8000-000000000001"
H = "sha256:" + "a" * 64
PRIVATE = Ed25519PrivateKey.from_private_bytes(bytes.fromhex("00" * 31 + "01"))
PUBLIC = PRIVATE.public_key().public_bytes_raw()
DOMAIN = b"m9.manual-material-seal.v1\x00"
MATERIAL = b"Entirely synthetic fixture text."


def modules() -> tuple[Any, Any]:
    for name in ("r2.opportunity.manual_admission", "server.services.m9_manual_authenticity"):
        assert importlib.util.find_spec(name) is not None, "manual seal verifier missing"
    return importlib.import_module("r2.opportunity.manual_admission"), importlib.import_module(
        "server.services.m9_manual_authenticity"
    )


def expectation() -> dict[str, Any]:
    return {
        "schema_version": "m9.manual-material-seal.v1",
        "source_kind": "manual-import",
        "source_contract_version": "manual-import.v1",
        "verification_key_id": "fixture-upload-custodian-1",
        "context": {"user_id": "u1", "project_name": "show-a", "actor_id": "human-a", "command_id": ID},
        "request_digest": H,
        "query_id": ID,
        "query_revision": 1,
        "query_digest": H,
        "attempt_id": ID,
        "attempt_version": 2,
        "publication_key": "opaque-publication-1",
        "claim_ref": "opaque-claim-1",
        "upload_version": 1,
        "descriptor_digest": H,
        "payload_ref": "opaque-payload-1",
        "integrity_ref": "opaque-integrity-1",
        "attestation_ref": "opaque-seal-1",
        "evidence_kind": "native-field-1",
        "data_classes": ["manual-excerpt"],
        "data_rules": [
            {
                "data_class": "manual-excerpt",
                "refresh_interval_seconds": 30,
                "retention_seconds": 90,
                "delete_on_revoke": True,
                "digest_proof_may_be_retained": False,
            }
        ],
        "original_clocks": [
            {
                "data_class": "manual-excerpt",
                "captured_at": "2026-10-17T00:00:00Z",
                "refresh_due_at": "2026-10-17T00:00:30Z",
                "retention_due_at": "2026-10-17T00:01:30Z",
            }
        ],
    }


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def seal(binding: dict[str, Any], *, material: bytes = MATERIAL, domain: bytes = DOMAIN, extra: bool = False) -> bytes:
    body = {"binding": binding, "material_digest": "sha256:" + hashlib.sha256(material).hexdigest()}
    if extra:
        body["unapproved"] = "CANARY_PRIVATE_MATERIAL"
    signature = base64.urlsafe_b64encode(PRIVATE.sign(domain + canonical(body))).decode().rstrip("=")
    return canonical({"body": body, "signature": signature})


def test_original_actual_bytes_verify_under_pinned_public_key():
    c, v = modules()
    expected = c.SealExpectation.model_validate(expectation())
    assert v.verify_manual_seal(seal(expectation()), MATERIAL, public_key=PUBLIC, expected=expected) is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_kind", "another-source"),
        ("source_contract_version", "manual-import.v999"),
        ("claim_ref", "different-claim"),
        ("upload_version", 2),
        ("payload_ref", "different-object"),
        ("integrity_ref", "different-integrity"),
        ("attestation_ref", "different-seal"),
        ("publication_key", "different-publication"),
        ("request_digest", "sha256:" + "b" * 64),
        ("query_digest", "sha256:" + "b" * 64),
        ("attempt_version", 3),
        ("descriptor_digest", "sha256:" + "b" * 64),
        ("verification_key_id", "another-authority"),
    ],
)
def test_valid_signature_for_another_binding_is_refused(field, value):
    c, v = modules()
    foreign = {**expectation(), field: value}
    with pytest.raises(OpportunityError, match="M9_RAW_DIGEST_MISMATCH"):
        v.verify_manual_seal(
            seal(foreign), MATERIAL, public_key=PUBLIC, expected=c.SealExpectation.model_validate(expectation())
        )


def test_valid_cross_scope_signature_cannot_substitute_original_material():
    c, v = modules()
    foreign = expectation()
    foreign["context"]["project_name"] = "another-project"
    with pytest.raises(OpportunityError):
        v.verify_manual_seal(
            seal(foreign), MATERIAL, public_key=PUBLIC, expected=c.SealExpectation.model_validate(expectation())
        )


@pytest.mark.parametrize(
    "fault",
    [
        "material",
        "hash_rewritten",
        "wrong_key",
        "wrong_domain",
        "extra_body",
        "noncanonical",
        "duplicate",
        "malformed",
        "oversize",
    ],
)
def test_store_owner_tamper_and_malformed_input_are_sanitized(fault):
    c, v = modules()
    expected = c.SealExpectation.model_validate(expectation())
    raw = seal(expectation())
    actual = MATERIAL
    key = PUBLIC
    if fault == "material":
        actual = b"CANARY_PRIVATE_MATERIAL"
    elif fault == "hash_rewritten":
        actual = b"CANARY_PRIVATE_MATERIAL"
        body = json.loads(raw)
        body["body"]["material_digest"] = "sha256:" + hashlib.sha256(actual).hexdigest()
        raw = canonical(body)
    elif fault == "wrong_key":
        key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex("00" * 31 + "02")).public_key().public_bytes_raw()
    elif fault == "wrong_domain":
        raw = seal(expectation(), domain=b"m9.some-other-purpose.v1\x00")
    elif fault == "extra_body":
        raw = seal(expectation(), extra=True)
    elif fault == "noncanonical":
        raw = json.dumps(json.loads(raw), indent=2).encode()
    elif fault == "duplicate":
        raw = raw.replace(b'{"body":', b'{"body":{},"body":', 1)
    elif fault == "malformed":
        raw = b'{"CANARY_PRIVATE_MATERIAL":'
    else:
        raw = b"CANARY_PRIVATE_MATERIAL" * 4096
    with pytest.raises(OpportunityError) as raised:
        v.verify_manual_seal(raw, actual, public_key=key, expected=expected)
    assert str(raised.value) == "M9_RAW_DIGEST_MISMATCH"
    assert "CANARY_PRIVATE_MATERIAL" not in "".join(traceback.format_exception(raised.value))


@pytest.mark.parametrize("extra", [{"material_digest": H}, {"signature": "secret"}, {"raw_payload": "secret"}])
def test_expected_sql_binding_cannot_retain_material_proof(extra):
    c, _ = modules()
    with pytest.raises(ValidationError):
        c.SealExpectation.model_validate({**expectation(), **extra})


@pytest.mark.parametrize(
    "changes",
    [
        {"data_classes": []},
        {"data_rules": []},
        {"original_clocks": []},
        {"data_classes": ["manual-public-metadata"]},
        {"source_contract_version": "manual-import.v999"},
    ],
)
def test_sql_expectation_rejects_unbound_source_or_class_semantics(changes):
    c, _ = modules()
    with pytest.raises(ValidationError):
        c.SealExpectation.model_validate({**expectation(), **changes})

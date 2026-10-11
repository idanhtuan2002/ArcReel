"""A checkpoint has canonical, bounded bytes and unambiguous scoped heads."""

from __future__ import annotations

import base64
import hashlib
import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from lib.content_digest import canonical_json_bytes
from r2.contracts.grant_checkpoint import CheckpointInvalid, parse_grant_checkpoint
from r2.governance.checkpoint_signature import verify_grant_checkpoint


def _head(user: str, project: str = "show-a", principal: str = "reviewer-a") -> dict[str, object]:
    return {
        "user_id": user,
        "project_name": project,
        "principal": principal,
        "head_sequence": 1,
        "head_event_digest": "sha256:" + "a" * 64,
    }


def _body(*, heads: list[dict[str, object]] | None = None) -> dict[str, object]:
    return {
        "schema": "governance.grant_head_checkpoint.v1",
        "deployment_id": "arcreel-prod-a",
        "checkpoint_sequence": 1,
        "previous_checkpoint_digest": None,
        "issued_at": "2026-10-12T00:00:00Z",
        "signer_key_id": "checkpoint-key-1",
        "heads": [] if heads is None else heads,
    }


def _raw(body: dict[str, object]) -> bytes:
    signature = base64.urlsafe_b64encode(b"\x00" * 64).decode("ascii").rstrip("=")
    return canonical_json_bytes({"body": body, "signature": signature}, allow_nan=False)


def _signed(body: dict[str, object], key: Ed25519PrivateKey) -> bytes:
    signature = (
        base64.urlsafe_b64encode(key.sign(canonical_json_bytes(body, allow_nan=False))).decode("ascii").rstrip("=")
    )
    return canonical_json_bytes({"body": body, "signature": signature}, allow_nan=False)


def test_parser_accepts_empty_genesis_and_sorted_successor() -> None:
    genesis_body = _body()
    genesis = parse_grant_checkpoint(_raw(genesis_body))
    assert genesis.body.heads == ()
    assert genesis.signature == b"\x00" * 64
    assert genesis.signed_bytes == canonical_json_bytes(genesis_body, allow_nan=False)
    assert genesis.checkpoint_digest == "sha256:" + hashlib.sha256(genesis.signed_bytes).hexdigest()

    successor_body = _body(heads=[_head("tenant-a"), _head("tenant-b")]) | {
        "checkpoint_sequence": 2,
        "previous_checkpoint_digest": genesis.checkpoint_digest,
    }
    successor = parse_grant_checkpoint(_raw(successor_body))
    assert successor.body.checkpoint_sequence == 2
    assert [(head.user_id, head.project_name, head.principal) for head in successor.body.heads] == [
        ("tenant-a", "show-a", "reviewer-a"),
        ("tenant-b", "show-a", "reviewer-a"),
    ]


@pytest.mark.parametrize(
    "body",
    [
        _body(heads=[_head("tenant-a"), _head("tenant-a")]),
        _body(heads=[_head("tenant-b"), _head("tenant-a")]),
        _body(heads=[_head("*")]),
        _body(heads=[_head(" tenant-a")]),
        _body(heads=[_head("tenant-a") | {"head_sequence": True}]),
        _body(heads=[_head("tenant-a") | {"head_event_digest": "sha256:BAD"}]),
        _body() | {"checkpoint_sequence": True},
        _body() | {"checkpoint_sequence": 2},
        _body() | {"previous_checkpoint_digest": "sha256:" + "a" * 64},
        _body() | {"issued_at": "2026-10-12T00:00:00+00:00"},
        _body() | {"signer_key_id": "*"},
        _body() | {"deployment_id": "arcreel-prod-a "},
        _body() | {"unexpected": 1},
    ],
)
def test_parser_denies_invalid_body_without_echo(body: dict[str, object]) -> None:
    with pytest.raises(CheckpointInvalid) as exc:
        parse_grant_checkpoint(_raw(body))
    assert "tenant-a" not in str(exc.value)
    assert "checkpoint-key-1" not in str(exc.value)


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"\xff",
        b" " + _raw(_body()),
        _raw(_body()) + b" ",
        b'{"body":{},"body":{},"signature":"x"}',
        b"[1,2]",
        _raw(_body()) + b" " * 4_194_305,
    ],
    ids=["empty", "invalid-utf8", "leading-space", "trailing-space", "duplicate-key", "array", "oversize"],
)
def test_parser_denies_malformed_or_noncanonical_envelope(raw: bytes) -> None:
    with pytest.raises(CheckpointInvalid):
        parse_grant_checkpoint(raw)


def test_parser_denies_more_than_10000_scopes() -> None:
    body = _body(heads=[_head(f"tenant-{index:05d}") for index in range(10_001)])
    assert len(_raw(body)) < 4_194_304
    with pytest.raises(CheckpointInvalid, match="scope_count"):
        parse_grant_checkpoint(_raw(body))


def test_parser_denies_noncanonical_signature_encoding() -> None:
    envelope = _raw(_body()).decode("utf-8")
    with pytest.raises(CheckpointInvalid):
        parse_grant_checkpoint(envelope.replace('"signature":"', '"signature":"!').encode("utf-8"))


def test_explicit_key_verifies_genesis_and_two_scope_successor() -> None:
    private = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    genesis = verify_grant_checkpoint(
        _signed(_body(), private),
        deployment_id="arcreel-prod-a",
        key_id="checkpoint-key-1",
        public_key=public,
    )
    assert genesis.body.heads == ()
    assert genesis.head_for_scope(user_id="tenant-a", project_name="show-a", principal="reviewer-a") is None
    assert genesis.checkpoint_digest == "sha256:2e06792ad5801dddb873d2e461343eaf245fddab7f7d32608480760c3d47c60c"
    assert base64.urlsafe_b64encode(genesis.signature).decode("ascii").rstrip("=") == (
        "ZrQrRHUcoyXTBVaSTi7WAmwLZYXEPTVGj0Ggr4VNOUl9GAFSsl6w23XtfpeUm_9mRabVXcpkesk5J9HpUAfdDQ"
    )

    successor_body = _body(heads=[_head("tenant-a"), _head("tenant-b")]) | {
        "checkpoint_sequence": 2,
        "previous_checkpoint_digest": genesis.checkpoint_digest,
    }
    successor = verify_grant_checkpoint(
        _signed(successor_body, private),
        deployment_id="arcreel-prod-a",
        key_id="checkpoint-key-1",
        public_key=public,
    )
    assert successor.checkpoint_digest == "sha256:c8b95048e02e0866dcfa8da3972713c4cb7aa16f152541f5a50cd79f4dce8976"
    assert base64.urlsafe_b64encode(successor.signature).decode("ascii").rstrip("=") == (
        "41e_fJ8bqrWGnrv8icbrUGGFUero2IbVqAVWKDmtKxpx1y2_Dw60Qd2BO0WxRdsYBWCD9UXZ6DeM-VeaW07bDA"
    )
    assert (
        successor.head_for_scope(user_id="tenant-b", project_name="show-a", principal="reviewer-a")
        == (successor.body.heads[1])
    )
    assert successor.head_for_scope(user_id="tenant-b", project_name="other-show", principal="reviewer-a") is None


def test_verifier_denies_wrong_deployment_key_and_tampering_without_echo() -> None:
    private = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    other_public = (
        Ed25519PrivateKey.generate()
        .public_key()
        .public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    )
    raw = _signed(_body(heads=[_head("tenant-a")]), private)
    changed_body = json.loads(raw)
    changed_body["body"]["heads"][0]["user_id"] = "tenant-b"
    altered_signature = bytearray(raw)
    altered_signature[-4] = ord("A") if altered_signature[-4] != ord("A") else ord("B")
    cases = [
        (raw, "other-deployment", "checkpoint-key-1", public),
        (raw, "arcreel-prod-a", "wrong-key-id", public),
        (raw, "arcreel-prod-a", "checkpoint-key-1", other_public),
        (raw, "arcreel-prod-a", "checkpoint-key-1", b"short"),
        (canonical_json_bytes(changed_body, allow_nan=False), "arcreel-prod-a", "checkpoint-key-1", public),
        (bytes(altered_signature), "arcreel-prod-a", "checkpoint-key-1", public),
    ]
    for submitted, deployment_id, key_id, key_bytes in cases:
        with pytest.raises(CheckpointInvalid) as exc:
            verify_grant_checkpoint(
                submitted,
                deployment_id=deployment_id,
                key_id=key_id,
                public_key=key_bytes,
            )
        assert "tenant-a" not in str(exc.value)
        assert "checkpoint-key-1" not in str(exc.value)

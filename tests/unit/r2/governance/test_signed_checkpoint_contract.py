"""A checkpoint has canonical, bounded bytes and unambiguous scoped heads."""

from __future__ import annotations

import base64
import hashlib

import pytest

from lib.content_digest import canonical_json_bytes
from r2.contracts.grant_checkpoint import CheckpointInvalid, parse_grant_checkpoint


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

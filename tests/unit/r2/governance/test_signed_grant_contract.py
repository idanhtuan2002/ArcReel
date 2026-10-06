"""Canonical, scoped Governance grant events stay independent of host sessions."""

from __future__ import annotations

import base64
import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from lib.content_digest import canonical_json_bytes
from r2.contracts.showrunner_grant import GrantEventInvalid, parse_grant_event
from r2.governance.grant_signature import verify_grant_event
from r2.governance.grant_transition import GrantScopeV1, verify_next_grant_event


def _body(event_type: str = "ISSUE") -> dict[str, object]:
    body: dict[str, object] = {
        "schema": "governance.showrunner_grant_event.v1",
        "event_type": event_type,
        "user_id": "tenant-a",
        "project_name": "show-a",
        "principal": "reviewer-a",
        "role": "HUMAN_SHOWRUNNER",
        "sequence": 1,
        "previous_event_digest": None,
        "issued_at": "2026-10-06T10:00:00Z",
        "signer_key_id": "governance-key-1",
    }
    if event_type == "ISSUE":
        body["not_before"] = "2026-10-06T10:00:00Z"
        body["expires_at"] = "2026-10-07T10:00:00Z"
    return body


def _raw(body: dict[str, object]) -> bytes:
    signature = base64.urlsafe_b64encode(b"\x00" * 64).decode("ascii").rstrip("=")
    return canonical_json_bytes({"body": body, "signature": signature}, allow_nan=False)


def _signed(body: dict[str, object], key: Ed25519PrivateKey) -> bytes:
    signature = (
        base64.urlsafe_b64encode(key.sign(canonical_json_bytes(body, allow_nan=False))).decode("ascii").rstrip("=")
    )
    return canonical_json_bytes({"body": body, "signature": signature}, allow_nan=False)


def test_issue_and_revoke_have_exact_signed_bytes_and_digest() -> None:
    issue = parse_grant_event(_raw(_body()))
    assert issue.body.event_type == "ISSUE"
    assert issue.body.sequence == 1
    assert issue.body.model_dump(mode="json") == _body()
    assert issue.signature == b"\x00" * 64
    assert issue.signed_bytes == canonical_json_bytes(_body(), allow_nan=False)
    assert issue.event_digest == "sha256:" + hashlib.sha256(issue.signed_bytes).hexdigest()

    revoke_body = _body("REVOKE") | {
        "sequence": 2,
        "previous_event_digest": issue.event_digest,
        "issued_at": "2026-10-06T11:00:00Z",
    }
    revoke = parse_grant_event(_raw(revoke_body))
    assert revoke.body.event_type == "REVOKE"
    assert revoke.body.previous_event_digest == issue.event_digest


@pytest.mark.parametrize(
    "raw",
    [
        b"",
        b"\xff",
        b" " + _raw(_body()),
        _raw(_body()) + b" ",
        b'{"body":{},"body":{},"signature":"x"}',
        b"[1,2]",
        b'{"body":{"project_name":"\\ud800"},"signature":"x"}',
        b"{" + b" " * 65_536 + b"}",
    ],
)
def test_noncanonical_or_malformed_envelope_denies_without_echo(raw: bytes) -> None:
    with pytest.raises(GrantEventInvalid) as exc:
        parse_grant_event(raw)
    assert "tenant-a" not in str(exc.value)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema", "other"),
        ("role", "admin"),
        ("user_id", "*"),
        ("project_name", " show-a"),
        ("sequence", True),
        ("sequence", 0),
        ("previous_event_digest", "sha256:bad"),
        ("issued_at", "2026-10-06T10:00:00+00:00"),
        ("expires_at", "2026-10-06T09:00:00Z"),
        ("extra", "unexpected"),
    ],
)
def test_invalid_issue_fields_deny(field: str, value: object) -> None:
    body = deepcopy(_body())
    body[field] = value
    with pytest.raises(GrantEventInvalid):
        parse_grant_event(_raw(body))


def test_revoke_rejects_issue_window_and_missing_predecessor() -> None:
    body = _body("REVOKE") | {"sequence": 2}
    with pytest.raises(GrantEventInvalid):
        parse_grant_event(_raw(body))
    body["previous_event_digest"] = "sha256:" + "a" * 64
    body["expires_at"] = "2026-10-07T10:00:00Z"
    with pytest.raises(GrantEventInvalid):
        parse_grant_event(_raw(body))


def test_signature_must_be_canonical_unpadded_base64url_64_bytes() -> None:
    decoded = json.loads(_raw(_body()))
    for bad in ["a", "A" * 88, decoded["signature"] + "==", "!" * 86]:
        with pytest.raises(GrantEventInvalid):
            parse_grant_event(canonical_json_bytes({**decoded, "signature": bad}, allow_nan=False))


def test_pinned_key_verifies_fixed_issue_and_revoke_vectors() -> None:
    private = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    issue = verify_grant_event(_signed(_body(), private), key_id="governance-key-1", public_key=public)
    assert issue.body.event_type == "ISSUE"
    assert issue.event_digest == "sha256:39143a963970d6b5db596d288f9260f95cee0ba3332c4084810d5297c07fa55c"
    assert base64.urlsafe_b64encode(issue.signature).decode("ascii").rstrip("=") == (
        "FRS4KBzPsf42KmhN_sEVVKcFLPbpHQLqBYe_5XaXalvz-PGHmSsWuSZavHAjwBXjJvsO19WlyLJTjBkcaQeODA"
    )
    revoke = _body("REVOKE") | {
        "sequence": 2,
        "previous_event_digest": issue.event_digest,
        "issued_at": "2026-10-06T11:00:00Z",
    }
    assert verify_grant_event(_signed(revoke, private), key_id="governance-key-1", public_key=public).body.sequence == 2


def test_signature_verifier_denies_wrong_key_scope_and_tampering() -> None:
    private = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    raw = _signed(_body(), private)
    changed = json.loads(raw)
    changed["body"]["project_name"] = "other-show"
    other_public = (
        Ed25519PrivateKey.generate()
        .public_key()
        .public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    )
    cases = [
        (raw, "wrong-key-id", public),
        (raw, "governance-key-1", other_public),
        (raw, "governance-key-1", b"short"),
        (canonical_json_bytes(changed, allow_nan=False), "governance-key-1", public),
    ]
    for submitted, key_id, key_bytes in cases:
        with pytest.raises(GrantEventInvalid) as exc:
            verify_grant_event(submitted, key_id=key_id, public_key=key_bytes)
        assert "tenant-a" not in str(exc.value)
        assert "governance-key-1" not in str(exc.value)


def test_transition_checks_signed_predecessor_scope_and_db_time() -> None:
    private = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    scope = GrantScopeV1(user_id="tenant-a", project_name="show-a", principal="reviewer-a")
    now = datetime(2026, 10, 6, 12, tzinfo=UTC)
    issue_raw = _signed(_body(), private)
    issue = verify_next_grant_event(issue_raw, None, scope=scope, key_id="governance-key-1", public_key=public, now=now)
    revoke_body = _body("REVOKE") | {
        "sequence": 2,
        "previous_event_digest": issue.event_digest,
        "issued_at": "2026-10-06T11:00:00Z",
    }
    revoke_raw = _signed(revoke_body, private)
    revoke = verify_next_grant_event(
        revoke_raw, issue_raw, scope=scope, key_id="governance-key-1", public_key=public, now=now
    )
    reissue = _body() | {
        "sequence": 3,
        "previous_event_digest": revoke.event_digest,
        "issued_at": "2026-10-06T12:00:00Z",
        "not_before": "2026-10-06T12:00:00Z",
    }
    assert (
        verify_next_grant_event(
            _signed(reissue, private), revoke_raw, scope=scope, key_id="governance-key-1", public_key=public, now=now
        ).body.sequence
        == 3
    )


def test_transition_denies_gap_wrong_predecessor_wrong_scope_and_invalid_action() -> None:
    private = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    scope = GrantScopeV1(user_id="tenant-a", project_name="show-a", principal="reviewer-a")
    now = datetime(2026, 10, 6, 12, tzinfo=UTC)
    issue_raw = _signed(_body(), private)
    issue_digest = verify_grant_event(issue_raw, key_id="governance-key-1", public_key=public).event_digest
    bad_events = [
        (_body("REVOKE"), None, scope),
        (_body() | {"sequence": 2, "previous_event_digest": "sha256:" + "a" * 64}, issue_raw, scope),
        (
            _body() | {"sequence": 2, "previous_event_digest": issue_digest, "issued_at": "2026-10-06T11:00:00Z"},
            issue_raw,
            scope,
        ),
        (_body() | {"sequence": 3, "previous_event_digest": "sha256:" + "a" * 64}, issue_raw, scope),
        (_body() | {"project_name": "other-show"}, None, scope),
        (_body() | {"issued_at": "2026-10-06T13:00:00Z", "not_before": "2026-10-06T13:00:00Z"}, None, scope),
        (_body() | {"expires_at": "2026-10-06T11:00:00Z"}, None, scope),
    ]
    for body, previous_raw, expected_scope in bad_events:
        with pytest.raises(GrantEventInvalid):
            verify_next_grant_event(
                _signed(body, private),
                previous_raw,
                scope=expected_scope,
                key_id="governance-key-1",
                public_key=public,
                now=now,
            )
    tampered_previous = json.loads(issue_raw)
    tampered_previous["body"]["principal"] = "other-reviewer"
    with pytest.raises(GrantEventInvalid):
        verify_next_grant_event(
            _signed(
                _body("REVOKE")
                | {"sequence": 2, "previous_event_digest": issue_digest, "issued_at": "2026-10-06T11:00:00Z"},
                private,
            ),
            canonical_json_bytes(tampered_previous, allow_nan=False),
            scope=scope,
            key_id="governance-key-1",
            public_key=public,
            now=now,
        )
    with pytest.raises(GrantEventInvalid):
        verify_next_grant_event(
            _signed(_body("REVOKE") | {"sequence": 2, "previous_event_digest": "sha256:" + "a" * 64}, private),
            issue_raw,
            scope=scope,
            key_id="governance-key-1",
            public_key=public,
            now=now.replace(tzinfo=None),
        )

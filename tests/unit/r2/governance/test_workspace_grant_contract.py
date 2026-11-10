"""A workspace grant event is its own signed schema; neither kind can pass as the other."""

from __future__ import annotations

import json

import pytest

from r2.contracts.fingerprints import canonical_json_bytes
from r2.contracts.showrunner_grant import (
    GRANT_EVENT_SCHEMA_V1,
    GRANT_EVENT_SCHEMA_V2,
    WORKSPACE_SCOPE,
    GrantEventInvalid,
    parse_grant_event,
)
from r2.governance.ceremony import decode_public_key, generate_key, sign_grant_event
from r2.governance.grant_signature import verify_grant_event

_EXPIRES = "2099-01-01T00:00:00Z"


def _sign(project_name: str) -> tuple[bytes, bytes, bytes]:
    key = generate_key()
    raw, _ = sign_grant_event(
        private_raw=key.private_raw,
        signer_key_id="grant-key",
        event_type="ISSUE",
        user_id="u1",
        project_name=project_name,
        principal="showrunner",
        sequence=1,
        previous_event_digest=None,
        expires_at=_EXPIRES,
        issued_at="2026-11-10T00:00:00Z",
    )
    return raw, key.private_raw, decode_public_key(key.public_encoded)


def test_ceremony_signs_a_v2_event_for_the_workspace_and_v1_for_a_project() -> None:
    workspace, _, public = _sign(WORKSPACE_SCOPE)
    project, _, _ = _sign("show-a")
    assert parse_grant_event(workspace).body.event_schema == GRANT_EVENT_SCHEMA_V2
    assert parse_grant_event(project).body.event_schema == GRANT_EVENT_SCHEMA_V1
    assert verify_grant_event(workspace, key_id="grant-key", public_key=public).body.project_name == WORKSPACE_SCOPE


@pytest.mark.parametrize(
    ("schema", "project_name"), [(GRANT_EVENT_SCHEMA_V1, WORKSPACE_SCOPE), (GRANT_EVENT_SCHEMA_V2, "show-a")]
)
def test_schema_and_scope_must_agree(schema: str, project_name: str) -> None:
    raw, _, _ = _sign("show-a")
    envelope = json.loads(raw)
    envelope["body"]["schema"] = schema
    envelope["body"]["project_name"] = project_name
    with pytest.raises(GrantEventInvalid):
        parse_grant_event(canonical_json_bytes(envelope))


def test_a_signature_does_not_carry_over_to_the_other_schema() -> None:
    raw, _, public = _sign(WORKSPACE_SCOPE)
    envelope = json.loads(raw)
    envelope["body"]["schema"] = GRANT_EVENT_SCHEMA_V1
    envelope["body"]["project_name"] = "show-a"
    forged = canonical_json_bytes(envelope)
    parse_grant_event(forged)
    with pytest.raises(GrantEventInvalid, match="signature"):
        verify_grant_event(forged, key_id="grant-key", public_key=public)

"""Pure predecessor and scope checks for a signed Governance grant event."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from r2.contracts.showrunner_grant import GrantEventInvalid
from r2.governance.grant_signature import VerifiedGrantEventV1, verify_grant_event


@dataclass(frozen=True)
class GrantScopeV1:
    user_id: str
    project_name: str
    principal: str


def _event_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _matches_scope(event: VerifiedGrantEventV1, scope: GrantScopeV1) -> bool:
    return (
        event.body.user_id == scope.user_id
        and event.body.project_name == scope.project_name
        and event.body.principal == scope.principal
        and event.body.role == "HUMAN_SHOWRUNNER"
    )


def verify_next_grant_event(
    raw: bytes,
    previous_raw: bytes | None,
    *,
    scope: GrantScopeV1,
    key_id: str,
    public_key: bytes,
    now: datetime,
) -> VerifiedGrantEventV1:
    """Check the next signed event against a caller-locked predecessor and DB time."""

    if now.utcoffset() != timedelta(0):
        raise GrantEventInvalid("database_time")
    event = verify_grant_event(raw, key_id=key_id, public_key=public_key)
    if not _matches_scope(event, scope) or _event_time(event.body.issued_at) > now:
        raise GrantEventInvalid("event_scope_or_time")
    if event.body.event_type == "ISSUE" and (
        event.body.expires_at is None or _event_time(event.body.expires_at) <= now
    ):
        raise GrantEventInvalid("event_expired")
    if previous_raw is None:
        if event.body.sequence != 1 or event.body.previous_event_digest is not None or event.body.event_type != "ISSUE":
            raise GrantEventInvalid("event_predecessor")
        return event
    previous = verify_grant_event(previous_raw, key_id=key_id, public_key=public_key)
    if (
        not _matches_scope(previous, scope)
        or event.body.sequence != previous.body.sequence + 1
        or event.body.previous_event_digest != previous.event_digest
        or _event_time(event.body.issued_at) <= _event_time(previous.body.issued_at)
        or event.body.event_type == previous.body.event_type
    ):
        raise GrantEventInvalid("event_predecessor")
    return event


__all__ = ["GrantScopeV1", "verify_next_grant_event"]

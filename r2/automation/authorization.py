"""Canonical automatic actor identities; data never substitutes for locked authority."""

import re

from pydantic import TypeAdapter

from r2.automation.identity import digest_value
from r2.contracts.automation import (
    AuthorizationSubject,
    AutomationAuthorizationV1,
    ExactIdentity,
    GrantRequest,
    PositiveInt,
)
from r2.contracts.common import ensure_json_value


def authorization_subject_digest(subject: AuthorizationSubject) -> str:
    subject = AuthorizationSubject.model_validate(subject)
    return digest_value("r2.automation-authorization-subject.v1", ensure_json_value(subject.model_dump(mode="json")))


def grant_request_digest(request: GrantRequest) -> str:
    request = GrantRequest.model_validate(request)
    body = request.model_dump(mode="json")
    body["operations"] = sorted(operation.value for operation in request.operations)
    return digest_value("r2.automation-delegation-request.v1", ensure_json_value(body))


def automation_principal(run_id: str) -> str:
    return "automation:" + digest_value("r2.automation-principal.v1", {"run_id": run_id}).removeprefix("sha256:")


_REFERENCE = re.compile(r"automation:v1:([^:\s]+):(auto-[0-9a-f]{64}):([^:\s]+):([1-9][0-9]{0,18})")
_IDENTITY = TypeAdapter(ExactIdentity)
_VERSION = TypeAdapter(PositiveInt)


def parse_automation_authorization_reference(value: str) -> tuple[str, str, str, int]:
    """Resolve only the shape of a bounded reference; the host resolves its actual durable evidence."""
    match = _REFERENCE.fullmatch(value)
    if match is None or len(value.encode("utf-8")) > 255:
        raise ValueError("invalid automatic authorization reference")
    run_id, command_id, grant_id, version = match.groups()
    return (
        _IDENTITY.validate_python(run_id),
        command_id,
        _IDENTITY.validate_python(grant_id),
        _VERSION.validate_python(int(version)),
    )


def automation_authorization_reference(proof: AutomationAuthorizationV1) -> str:
    subject = AutomationAuthorizationV1.model_validate(proof).subject
    value = f"automation:v1:{subject.run_id}:{subject.command_id}:{subject.grant_id}:{subject.grant_version}"
    parse_automation_authorization_reference(value)
    return value

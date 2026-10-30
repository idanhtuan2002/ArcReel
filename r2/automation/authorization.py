"""Canonical automatic actor identities; data never substitutes for locked authority."""

from r2.automation.identity import digest_value
from r2.contracts.automation import AuthorizationSubject, GrantRequest
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

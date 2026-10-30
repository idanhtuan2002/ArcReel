"""Final automatic authority hook; Human proof semantics remain in their existing port."""

import hashlib

from r2.contracts.common import R2ContractModel
from r2.contracts.fingerprints import canonical_json_bytes
from r2.contracts.narrative_lifecycle import (
    NarrativeAutomationDecisionAuthorizationV1,
    NarrativeAutomationRetryAuthenticationV1,
    NarrativeDecisionAuthorizationEvidence,
    NarrativeDecisionCommand,
    NarrativeDecisionRetryAuthenticationEvidence,
)
from r2.narrative_lifecycle.errors import NarrativeDecisionAuthorizationError
from r2.narrative_lifecycle.ports import NarrativeAutomationAuthorityPort, NarrativeDecisionAuthorityPort


async def require_automatic_owner_authority(
    authority: NarrativeDecisionAuthorityPort,
    unit_of_work: object,
    command: R2ContractModel,
    evidence: NarrativeDecisionAuthorizationEvidence | NarrativeDecisionRetryAuthenticationEvidence,
) -> None:
    automatic = isinstance(
        evidence, (NarrativeAutomationDecisionAuthorizationV1, NarrativeAutomationRetryAuthenticationV1)
    )
    guarded = isinstance(authority, NarrativeAutomationAuthorityPort)
    if automatic != guarded:
        raise NarrativeDecisionAuthorizationError("automatic provenance requires its owning-transaction guard")
    if guarded:
        await authority.require_current_in_owner(unit_of_work, command)


def automatic_authorization_fingerprints(command: NarrativeDecisionCommand) -> tuple[str, str]:
    canonical = command.model_copy(update={"retry_authentication": None})
    scope = canonical_json_bytes(canonical.work_scope.model_dump(mode="json"))
    body = canonical_json_bytes(canonical.model_dump(mode="json"))
    return "nss:" + hashlib.sha256(scope).hexdigest(), "ndc:" + hashlib.sha256(body).hexdigest()

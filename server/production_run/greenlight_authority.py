"""Run-scoped automatic Gate A greenlight of one exact brief digest (ADR-0111 BRIEF)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.repositories.gates import GreenlightRepository
from r2.automation.authorization import automation_authorization_reference, automation_principal
from r2.automation.identity import digest_value
from r2.contracts.automation import AuthorizationSubject, AutomationOperation
from r2.contracts.gates import GateAutomationAuthorizationV1, GreenlightDecision
from server.services.automation_grants import RunAutomationAuthority


def greenlight_subject_digest(*, source_digest: str) -> str:
    """The BRIEF authorization subject: exactly the brief digest Story start will check against Gate A."""
    return digest_value("r2.automatic-greenlight.v1", {"source_digest": source_digest})


async def greenlight_automatically(
    *,
    sessions: async_sessionmaker[AsyncSession],
    authority: RunAutomationAuthority,
    subject: AuthorizationSubject,
    source_digest: str,
) -> GreenlightDecision:
    """Append (or replay) the run's greenlight; the grant is re-required after the write, before commit."""
    if type(authority) is not RunAutomationAuthority:
        raise PermissionError("ACTIVATED_AUTOMATION_AUTHORITY_REQUIRED")
    subject = AuthorizationSubject.model_validate(subject)
    if subject.operation is not AutomationOperation.BRIEF or subject.subject_digest != greenlight_subject_digest(
        source_digest=source_digest
    ):
        raise PermissionError("GREENLIGHT_SUBJECT_MISMATCH")
    async with sessions() as session, session.begin():
        proof = await authority.require_locked(session, subject=subject)
    if proof.principal != automation_principal(subject.run_id):
        raise PermissionError("AUTOMATION_PRINCIPAL_MISMATCH")
    reference = automation_authorization_reference(proof)
    decision_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"r2-automatic-greenlight/{reference}/{source_digest}"))
    async with sessions() as session, session.begin():
        repository = GreenlightRepository(session)
        stored = await _decision(repository, subject, decision_id)
        if stored is None:
            await repository.append(
                GreenlightDecision(
                    decision_id=decision_id,
                    user_id=subject.user_id,
                    project_name=subject.project_name,
                    source_digest=source_digest,
                    action="GREENLIGHT",
                    authorization=GateAutomationAuthorizationV1(
                        authenticated_principal=proof.principal,
                        automation_reference=reference,
                        authorized_at=datetime.now(UTC),
                    ),
                    sequence=1,  # ignored by append(); the repository assigns the real, race-safe value
                    created_at=datetime.now(UTC),
                )
            )
            stored = await _decision(repository, subject, decision_id)
        if await authority.require_locked(session, subject=subject) != proof:
            raise PermissionError("AUTOMATION_AUTHORITY_PROJECTION_MISMATCH")
    if stored is None or stored.source_digest != source_digest or stored.action != "GREENLIGHT":
        raise RuntimeError("automatic greenlight is not the stored decision")
    return stored


async def _decision(
    repository: GreenlightRepository, subject: AuthorizationSubject, decision_id: str
) -> GreenlightDecision | None:
    history = await repository.list_for_project(user_id=subject.user_id, project_name=subject.project_name)
    return next((d for d in history if d.decision_id == decision_id), None)


__all__ = ["greenlight_automatically", "greenlight_subject_digest"]

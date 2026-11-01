"""Run-scoped automatic Gate C approval of one sealed R2 shot through the shared master core."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Self

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.async_thread import run_noninterruptible_sync
from r2.automation.authorization import automation_authorization_reference, automation_principal
from r2.automation.identity import digest_value
from r2.contracts.automation import AuthorizationSubject, AutomationAuthorizationV1, AutomationOperation, OwnerReceipt
from r2.contracts.common import ensure_json_value
from r2.m3.host_integration import validate_m3_target_ref
from server.routers.gates import CutApproval, CutApprovalActor, approve_cut_core
from server.services.automation_grants import RunAutomationAuthority
from server.services.r2_shot_approval import (
    R2_SHOT_EPISODE,
    R2ShotApprovalRefused,
    R2ShotCut,
    prepare_r2_shot_cut,
    require_slot_owner,
)

MASTER_OWNER = "gate-c"
_BINDING_SEAL = object()


def master_subject_digest(*, target_id: str, task_id: str) -> str:
    """The MASTER authorization subject: exactly one shot target and the generation task that produced it."""
    return digest_value("r2.automatic-master-approval.v1", {"target_id": target_id, "task_id": task_id})


class MasterApprovalRefused(Exception):
    """The shot cannot become this target's master now; ``code`` names the owner's reason."""

    def __init__(self, code: str, status: int = 409) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


class AutomaticMasterApproval:
    """A bound shot grants no effect: every master write re-checks the run authority in the owner transaction."""

    def __init__(
        self,
        *,
        sessions: async_sessionmaker[AsyncSession],
        authority: RunAutomationAuthority,
        subject: AuthorizationSubject,
        project_dir: Path,
        task_id: str,
        cut: R2ShotCut,
        proof: AutomationAuthorizationV1,
        binding: object | None = None,
    ) -> None:
        if binding is not _BINDING_SEAL:
            raise PermissionError("VALIDATED_SHOT_BINDING_REQUIRED")
        self._sessions, self._authority, self._subject = sessions, authority, subject
        self._project_dir, self._task_id, self._cut, self._proof = project_dir, task_id, cut, proof

    @classmethod
    async def bind(
        cls,
        *,
        sessions: async_sessionmaker[AsyncSession],
        authority: RunAutomationAuthority,
        subject: AuthorizationSubject,
        project_dir: Path,
        target_id: str,
        task_id: str,
    ) -> Self:
        if type(authority) is not RunAutomationAuthority:
            raise PermissionError("ACTIVATED_AUTOMATION_AUTHORITY_REQUIRED")
        subject = AuthorizationSubject.model_validate(subject)
        validate_m3_target_ref(target_id)
        if subject.operation is not AutomationOperation.MASTER or subject.subject_digest != master_subject_digest(
            target_id=target_id, task_id=task_id
        ):
            raise PermissionError("MASTER_SUBJECT_MISMATCH")
        async with sessions() as session, session.begin():
            proof = await authority.require_locked(session, subject=subject)
        if proof.principal != automation_principal(subject.run_id):
            raise PermissionError("AUTOMATION_PRINCIPAL_MISMATCH")
        try:
            cut = await prepare_r2_shot_cut(
                session_factory=sessions,
                project_dir=project_dir,
                user_id=subject.user_id,
                project_name=subject.project_name,
                target_id=target_id,
                task_id=task_id,
            )
        except R2ShotApprovalRefused as exc:
            raise MasterApprovalRefused(exc.code, exc.status) from exc
        return cls(
            sessions=sessions,
            authority=authority,
            subject=subject,
            project_dir=project_dir,
            task_id=task_id,
            cut=cut,
            proof=proof,
            binding=_BINDING_SEAL,
        )

    @property
    def selected_by(self) -> str:
        return self._proof.principal

    async def _require_current(self, session: AsyncSession) -> None:
        if await self._authority.require_locked(session, subject=self._subject) != self._proof:
            raise PermissionError("AUTOMATION_AUTHORITY_PROJECTION_MISMATCH")

    async def promote(self) -> OwnerReceipt:
        cut, target_id = self._cut, self._cut.target_ref
        approval_record = automation_authorization_reference(self._proof)

        async def slot_guard(_session: AsyncSession) -> None:
            try:
                await run_noninterruptible_sync(lambda: require_slot_owner(self._project_dir, target_id))
            except R2ShotApprovalRefused as exc:
                raise HTTPException(status_code=exc.status, detail=exc.code) from exc

        request_digest = hashlib.sha256(
            f"r2-shot-auto/{target_id}/{self._task_id}/{approval_record}/{cut.produced.sha256}".encode()
        ).hexdigest()
        try:
            result = await approve_cut_core(
                actor=CutApprovalActor(user_id=self._subject.user_id, principal=self._proof.principal),
                project_name=self._subject.project_name,
                project_dir=self._project_dir,
                approval=CutApproval(
                    resource_type="videos",
                    episode=R2_SHOT_EPISODE,
                    target_ref=target_id,
                    content_fingerprint=cut.content_fingerprint,
                    content_basis=cut.content_basis,
                    direct_dependencies=cut.direct_dependencies,
                    contract_version=cut.contract_version,
                    contract_schema_version=cut.contract_schema_version,
                    approval_record=approval_record,
                    audio_decision=None,
                    produced=cut.produced,
                    request_digest=request_digest,
                    slot_guard=slot_guard,
                ),
                sessions=self._sessions,
                authority_guard=self._require_current,
            )
        except HTTPException as exc:
            raise MasterApprovalRefused(str(exc.detail), exc.status_code) from exc
        receipt = result["receipt"]
        if not isinstance(receipt, dict):
            raise RuntimeError("Gate C returned no receipt")
        return OwnerReceipt(
            owner=MASTER_OWNER,
            receipt_ref=str(receipt["selected_candidate_id"]),
            digest=digest_value("r2.automatic-master-receipt.v1", ensure_json_value(receipt)),
            task_id=self._task_id,
        )


__all__ = ["AutomaticMasterApproval", "MasterApprovalRefused", "master_subject_digest"]

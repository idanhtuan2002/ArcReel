"""``MASTER``: each episode's verified render becomes that episode's approved final master through Gate C.

The final is staged and promoted by the shared Gate C core (``approve_cut_core``) as the episode's
``auto-final-e<n>`` target, selected by the run's automation principal; the run authority is re-required inside the
owner transaction and must still be the proof admitted for the step. The approval record is stable per step and
episode, so a replay after a crash returns the stored receipt instead of promoting twice. Before staging, the final
is re-hashed against the render manifest; a changed file never becomes a master.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from lib.presentation_renderer import sha256_file
from lib.project_manager import ProjectManager
from r2.automation.authorization import automation_principal
from r2.automation.identity import digest_value
from r2.contracts.automation import (
    AuthorizationSubject,
    AutomationAuthorizationV1,
    BudgetReservation,
    DispatchIntent,
    OwnerReceipt,
    RunSnapshot,
    RunStage,
    StageOutcome,
    UsageReceipt,
)
from r2.contracts.common import ensure_json_value
from r2.contracts.content_basis import ContentBasis
from r2.contracts.enums import ContentBasisType, ProductionMethod
from r2.m3.render_plan import RenderedCutAsset
from server.production_run.owner_support import (
    OwnerBlocked,
    Sessions,
    current_subject,
    outcome,
    required_outcome,
    usage_receipt,
)
from server.production_run.ports import StepPlan
from server.production_run.text_adapter import receipt_revision
from server.routers.gates import CutApproval, CutApprovalActor, approve_cut_core
from server.services.automation_grants import RunAutomationAuthority

FINAL_MASTER_OWNER = "gate-c"


def final_target_ref(episode: int) -> str:
    return f"auto-final-e{episode}"


class FinalMasterAdapter:
    owner = FINAL_MASTER_OWNER

    def __init__(self, sessions: Sessions, *, authority: RunAutomationAuthority, projects: ProjectManager) -> None:
        self._sessions, self._authority, self._projects = sessions, authority, projects

    async def plan(self, *, run: RunSnapshot) -> StepPlan:
        render = await required_outcome(self._sessions, run, RunStage.RENDER)
        return StepPlan(
            unit_key="master",
            input_refs=render.receipts,
            estimated_cost_minor_units=0,
            estimated_model_calls=0,
            estimated_tasks=0,
            estimated_runtime_seconds=60 * len(render.receipts),
        )

    async def dispatch(self, intent: DispatchIntent) -> OwnerReceipt:
        digest = self._subject_digest(intent)
        await self._approve_all(intent, digest)
        return OwnerReceipt(owner=self.owner, receipt_ref=intent.identity.command_id, digest=digest)

    async def inspect(self, *, intent: DispatchIntent, receipt: OwnerReceipt) -> StageOutcome:
        receipts = await self._approve_all(intent, receipt.digest)
        return outcome(intent, "PASS", receipts=receipts, owner_state="APPROVED_MASTER")

    async def usage(self, *, receipt: OwnerReceipt, reservation: BudgetReservation) -> UsageReceipt | None:
        return usage_receipt(receipt, reservation)

    # --- helpers -------------------------------------------------------------------------------------

    @staticmethod
    def _subject_digest(intent: DispatchIntent) -> str:
        return digest_value(
            "r2.production-final-master.v1",
            ensure_json_value({"input_refs": [ref.model_dump(mode="json") for ref in intent.input_refs]}),
        )

    async def _approve_all(self, intent: DispatchIntent, subject_digest: str) -> tuple[OwnerReceipt, ...]:
        subject = await current_subject(self._sessions, intent, subject_digest=subject_digest)
        async with self._sessions() as session, session.begin():
            proof = await self._authority.require_locked(session, subject=subject)
        if proof.principal != automation_principal(intent.scope.run_id):
            raise PermissionError("AUTOMATION_PRINCIPAL_MISMATCH")
        project_dir = self._projects.get_project_path(intent.scope.project_name)
        return tuple([await self._approve(intent, subject, proof, project_dir, render) for render in intent.input_refs])

    async def _approve(
        self,
        intent: DispatchIntent,
        subject: AuthorizationSubject,
        proof: AutomationAuthorizationV1,
        project_dir: Path,
        render: OwnerReceipt,
    ) -> OwnerReceipt:
        episode = int(render.receipt_ref.split(":")[1])
        final = (project_dir / receipt_revision(render)).resolve()
        if (project_dir / "production").resolve() not in final.parents:
            raise OwnerBlocked("RENDER_OUTPUT_OUTSIDE_PRODUCTION")
        manifest_path = final.with_name(f"episode_{episode}.manifest.json")
        if not final.is_file() or "sha256:" + sha256_file(manifest_path) != render.digest:
            raise OwnerBlocked("RENDER_OUTPUT_CHANGED")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if sha256_file(final) != manifest["final_sha256"]:
            raise OwnerBlocked("RENDER_OUTPUT_CHANGED")
        target = final_target_ref(episode)
        approval_record = f"auto-final:{intent.identity.command_id}:e{episode}"
        produced = RenderedCutAsset(
            target_ref=target,
            method=ProductionMethod.DETERMINISTIC,
            path=final,
            sha256="sha256:" + manifest["final_sha256"],
            duration_seconds=float(manifest["duration_seconds"]),
            execution_fingerprint=render.digest,
            tool="ffmpeg",
            tool_version=str(manifest["tool_version"]),
            wall_time_seconds=0.0,
            external_provider_cost=Decimal(0),
            source_master_refs=(),
        )
        request_digest = hashlib.sha256(
            f"auto-final/{intent.scope.run_id}/{approval_record}/{render.digest}".encode()
        ).hexdigest()

        async def require_current(session: AsyncSession) -> None:
            if await self._authority.require_locked(session, subject=subject) != proof:
                raise PermissionError("AUTOMATION_AUTHORITY_PROJECTION_MISMATCH")

        try:
            result = await approve_cut_core(
                actor=CutApprovalActor(user_id=intent.scope.user_id, principal=proof.principal),
                project_name=intent.scope.project_name,
                project_dir=project_dir,
                approval=CutApproval(
                    resource_type="videos",
                    episode=episode,
                    target_ref=target,
                    content_fingerprint=render.digest,
                    content_basis=ContentBasis(
                        basis_type=ContentBasisType.NARRATIVE,
                        basis_version="r2.production-render-manifest.v1",
                        refs=[f"render:{render.digest}"],
                    ),
                    direct_dependencies=[],
                    contract_version=1,
                    contract_schema_version="1",
                    approval_record=approval_record,
                    audio_decision=None,
                    produced=produced,
                    request_digest=request_digest,
                ),
                sessions=self._sessions,
                authority_guard=require_current,
            )
        except HTTPException as exc:
            raise OwnerBlocked("MASTER_" + str(exc.status_code)) from None
        receipt = result["receipt"]
        if not isinstance(receipt, dict):
            raise OwnerBlocked("OUTCOME_UNKNOWN")
        return OwnerReceipt(
            owner=self.owner,
            receipt_ref=f"episode:{episode}:master@{receipt['selected_candidate_id']}",
            digest=digest_value("r2.production-final-master-receipt.v1", ensure_json_value(receipt)),
        )


__all__ = ["FINAL_MASTER_OWNER", "FinalMasterAdapter", "final_target_ref"]

"""The host format evidence gate for M8-A preview and promotion of FORMAT candidates (M8-E E3).

A FORMAT candidate may be previewed or promoted into a slot only while all of this still holds: the
slot is the format slot of the plan's source artifact and profile; the render execution succeeded
for that plan and produced exactly the candidate's artifact; the latest technical and semantic
reports for that plan and artifact both pass and are the ones the candidate names; and the plan's
source master is still the current head of its artifact key.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from lib.db.models.formats import FormatRenderModel
from lib.db.repositories.formats import FormatRepository, report_digest
from lib.db.repositories.host_hardening import MasterAuthorityRepository
from r2.advanced_creative.errors import PromotionBindingStaleError
from r2.advanced_creative.formats import FormatInvalidError, format_slot_key, parse_source_master_id, validate_plan
from r2.contracts.advanced_creative import FormatCandidate


class HostFormatEvidence:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def verify(self, *, user_id: str, project_name: str, target_ref: str, payload: FormatCandidate) -> None:
        render = await self._session.get(FormatRenderModel, (user_id, project_name, payload.execution_id))
        if render is None or render.state != "SUCCEEDED" or render.artifact_digest != payload.rendered_artifact_digest:
            raise PromotionBindingStaleError("the candidate's render is not a succeeded render of its artifact")
        repository = FormatRepository(self._session)
        plan = await repository.get_plan(user_id=user_id, project_name=project_name, plan_id=render.plan_id)
        if plan is None or plan.plan_digest != payload.plan_digest:
            raise PromotionBindingStaleError("the candidate's plan changed")
        try:
            validate_plan(plan)
            artifact_key, master_version = parse_source_master_id(plan.source_master_id)
        except FormatInvalidError as exc:
            raise PromotionBindingStaleError("the candidate's plan is not valid") from exc
        if target_ref != format_slot_key(artifact_key, plan.output_profile.profile_ref):
            raise PromotionBindingStaleError("the target is not this projection's format slot")
        reports = await repository.passing_reports(
            user_id=user_id,
            project_name=project_name,
            plan_id=plan.plan_id,
            artifact_digest=payload.rendered_artifact_digest,
        )
        if reports is None:
            raise PromotionBindingStaleError("technical and semantic reports do not both pass")
        technical, semantic = reports
        if (technical.report_id, report_digest(technical), semantic.report_id, report_digest(semantic)) != (
            payload.technical_report_id,
            payload.technical_report_digest,
            payload.semantic_report_id,
            payload.semantic_report_digest,
        ):
            raise PromotionBindingStaleError("the candidate names reports that are no longer the latest")
        master = await MasterAuthorityRepository(self._session).get_current(
            user_id=user_id, project_name=project_name, artifact_key=artifact_key
        )
        if (
            master is None
            or master.master_version != master_version
            or master.content_digest != plan.source_master_digest
        ):
            raise PromotionBindingStaleError("the source master moved since the plan")


__all__ = ["HostFormatEvidence"]

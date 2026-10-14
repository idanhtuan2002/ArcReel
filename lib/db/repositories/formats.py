"""Persistence for M8-E format projections (plan 2026-10-14 M8-E E1).

Writes happen inside the caller's transaction and never update or delete. A ref or id that already
holds the same digest replays; different content under it is a conflict. A plan is admitted only
when its digest verifies and the exact profile and overlay rows it embeds are stored. Reports are
validated against their plan before they are appended.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lib.db.models.formats import (
    FormatPlanModel,
    FormatProfileModel,
    FormatSemanticReportModel,
    FormatTechnicalReportModel,
    OverlayConstraintSetModel,
)
from r2.advanced_creative.digests import digest_canonical
from r2.advanced_creative.errors import FormatConflictError, FormatNotFoundError
from r2.advanced_creative.formats import (
    overlay_digest,
    profile_digest,
    validate_output_profile,
    validate_overlay_set,
    validate_semantic_report,
    validate_technical_report,
    verify_plan_digest,
)
from r2.contracts.advanced_creative import (
    FormatProjectionPlan,
    OutputProfile,
    OverlayConstraintSet,
    SemanticParityReport,
    TechnicalValidationReport,
)

Clock = Callable[[], datetime]


def report_digest(report: TechnicalValidationReport | SemanticParityReport) -> str:
    return digest_canonical({"contract_version": "1", "report": report})


class FormatRepository:
    def __init__(self, session: AsyncSession, *, clock: Clock | None = None) -> None:
        self.session = session
        self._clock = clock or (lambda: datetime.now(UTC))

    async def put_profile(self, *, user_id: str, project_name: str, profile: OutputProfile) -> OutputProfile:
        validate_output_profile(profile)
        digest = profile_digest(profile)
        row = await self.session.get(FormatProfileModel, (user_id, project_name, profile.profile_ref))
        if row is not None:
            if row.profile_digest != digest:
                raise FormatConflictError("profile ref already names another profile")
            return profile
        self.session.add(
            FormatProfileModel(
                user_id=user_id,
                project_name=project_name,
                profile_ref=profile.profile_ref,
                profile_json=profile.model_dump(mode="json"),
                profile_digest=digest,
                created_at=self._clock(),
            )
        )
        await self.session.flush()
        return profile

    async def put_overlay(
        self, *, user_id: str, project_name: str, overlay: OverlayConstraintSet
    ) -> OverlayConstraintSet:
        validate_overlay_set(overlay)
        digest = overlay_digest(overlay)
        row = await self.session.get(OverlayConstraintSetModel, (user_id, project_name, overlay.constraint_ref))
        if row is not None:
            if row.overlay_digest != digest:
                raise FormatConflictError("overlay ref already names another overlay set")
            return overlay
        self.session.add(
            OverlayConstraintSetModel(
                user_id=user_id,
                project_name=project_name,
                constraint_ref=overlay.constraint_ref,
                overlay_json=overlay.model_dump(mode="json"),
                overlay_digest=digest,
                created_at=self._clock(),
            )
        )
        await self.session.flush()
        return overlay

    async def create_plan(self, *, user_id: str, project_name: str, plan: FormatProjectionPlan) -> FormatProjectionPlan:
        verify_plan_digest(plan)
        profile = await self.session.get(FormatProfileModel, (user_id, project_name, plan.output_profile.profile_ref))
        overlay = await self.session.get(
            OverlayConstraintSetModel, (user_id, project_name, plan.overlay_constraints.constraint_ref)
        )
        if profile is None or overlay is None:
            raise FormatNotFoundError("plan names an unknown profile or overlay set")
        if profile.profile_digest != profile_digest(plan.output_profile) or overlay.overlay_digest != overlay_digest(
            plan.overlay_constraints
        ):
            raise FormatConflictError("plan embeds a profile or overlay that differs from the stored one")
        row = await self.session.get(FormatPlanModel, (user_id, project_name, plan.plan_id))
        if row is not None:
            if row.plan_digest != plan.plan_digest:
                raise FormatConflictError("plan id already names another plan")
            return plan
        self.session.add(
            FormatPlanModel(
                user_id=user_id,
                project_name=project_name,
                plan_id=plan.plan_id,
                plan_digest=plan.plan_digest,
                plan_json=plan.model_dump(mode="json"),
                profile_ref=plan.output_profile.profile_ref,
                constraint_ref=plan.overlay_constraints.constraint_ref,
                source_master_id=plan.source_master_id,
                source_master_digest=plan.source_master_digest,
                created_at=self._clock(),
            )
        )
        await self.session.flush()
        return plan

    async def get_plan(self, *, user_id: str, project_name: str, plan_id: str) -> FormatProjectionPlan | None:
        row = await self.session.get(FormatPlanModel, (user_id, project_name, plan_id))
        return None if row is None else FormatProjectionPlan.model_validate(row.plan_json)

    async def _plan_or_missing(self, *, user_id: str, project_name: str, plan_id: str) -> FormatProjectionPlan:
        plan = await self.get_plan(user_id=user_id, project_name=project_name, plan_id=plan_id)
        if plan is None:
            raise FormatNotFoundError("report names an unknown plan")
        return plan

    async def append_technical_report(
        self, *, user_id: str, project_name: str, plan_id: str, report: TechnicalValidationReport
    ) -> TechnicalValidationReport:
        plan = await self._plan_or_missing(user_id=user_id, project_name=project_name, plan_id=plan_id)
        validate_technical_report(report, plan)
        digest = report_digest(report)
        row = await self.session.get(FormatTechnicalReportModel, (user_id, project_name, report.report_id))
        if row is not None:
            if row.report_digest != digest:
                raise FormatConflictError("report id already names another report")
            return report
        self.session.add(
            FormatTechnicalReportModel(
                user_id=user_id,
                project_name=project_name,
                report_id=report.report_id,
                plan_id=plan_id,
                artifact_digest=report.artifact_digest,
                report_json=report.model_dump(mode="json"),
                report_digest=digest,
                passed=report.passed,
                created_at=self._clock(),
            )
        )
        await self.session.flush()
        return report

    async def append_semantic_report(
        self, *, user_id: str, project_name: str, plan_id: str, report: SemanticParityReport, deviation: str | None
    ) -> SemanticParityReport:
        plan = await self._plan_or_missing(user_id=user_id, project_name=project_name, plan_id=plan_id)
        reviewer_count = validate_semantic_report(report, plan, deviation=deviation)
        digest = report_digest(report)
        row = await self.session.get(FormatSemanticReportModel, (user_id, project_name, report.report_id))
        if row is not None:
            if row.report_digest != digest:
                raise FormatConflictError("report id already names another report")
            return report
        self.session.add(
            FormatSemanticReportModel(
                user_id=user_id,
                project_name=project_name,
                report_id=report.report_id,
                plan_id=plan_id,
                artifact_digest=report.artifact_digest,
                report_json=report.model_dump(mode="json"),
                report_digest=digest,
                reviewer_count=reviewer_count,
                deviation=deviation if reviewer_count < 2 else None,
                passed=report.passed,
                created_at=self._clock(),
            )
        )
        await self.session.flush()
        return report

    async def passing_reports(
        self, *, user_id: str, project_name: str, plan_id: str, artifact_digest: str
    ) -> tuple[TechnicalValidationReport, SemanticParityReport] | None:
        """The latest passing technical and semantic reports for one plan and artifact, or None.

        A later failing report of either plane supersedes an earlier pass for that plane.
        """
        latest: list[object] = []
        for model, contract in (
            (FormatTechnicalReportModel, TechnicalValidationReport),
            (FormatSemanticReportModel, SemanticParityReport),
        ):
            row = await self.session.scalar(
                select(model)
                .where(
                    model.user_id == user_id,
                    model.project_name == project_name,
                    model.plan_id == plan_id,
                    model.artifact_digest == artifact_digest,
                )
                .order_by(model.created_at.desc(), model.report_id.desc())
                .limit(1)
            )
            if row is None or not row.passed:
                return None
            latest.append(contract.model_validate(row.report_json))
        technical, semantic = latest
        assert isinstance(technical, TechnicalValidationReport)
        assert isinstance(semantic, SemanticParityReport)
        return technical, semantic


__all__ = ["FormatRepository", "report_digest"]

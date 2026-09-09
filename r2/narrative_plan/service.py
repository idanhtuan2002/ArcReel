"""The sole NarrativePlan commit authority.

``commit_revision`` is the only plan write path. ``expected_version=None`` is a genesis
proposal that creates the scoped head row inside the same approved transaction that
appends version 1; ``expected_version=N`` appends exactly version ``N + 1``. The Canon
basis is resolved exactly and read-only; approval never falls back to the Canon head.
"""

from __future__ import annotations

from datetime import datetime

from r2.contracts import (
    NarrativePlan,
    NarrativePlanApproval,
    NarrativePlanCommitResult,
    NarrativePlanContent,
    NarrativePlanHeadSnapshot,
    NarrativePlanRevisionProposal,
    NarrativePlanVersionSnapshot,
)
from r2.narrative.canon_state import ResolvedCanonView
from r2.narrative.validation import NarrativeInvariantValidator

from .errors import (
    NarrativePlanApprovalError,
    NarrativePlanIdentityConflictError,
    NarrativePlanNotFoundError,
    NarrativePlanValidationError,
    NarrativePlanVersionConflict,
)
from .hashing import compute_plan_content_hash, compute_scene_semantic_hash
from .ports import CanonVersionReader, NarrativePlanUnitOfWorkFactory
from .validation import validate_plan_hierarchy, validate_scene_version


class NarrativePlanService:
    def __init__(
        self,
        uow_factory: NarrativePlanUnitOfWorkFactory,
        canon_reader: CanonVersionReader,
        *,
        validator: NarrativeInvariantValidator | None = None,
    ) -> None:
        self._uow_factory = uow_factory
        self._canon_reader = canon_reader
        self._validator = validator or NarrativeInvariantValidator()

    async def commit_revision(
        self,
        *,
        proposal: NarrativePlanRevisionProposal,
        approval: NarrativePlanApproval,
        project_name: str,
        user_id: str,
        now: datetime,
    ) -> NarrativePlanCommitResult:
        self._require_matching_scope(proposal=proposal, approval=approval, project_name=project_name, user_id=user_id)
        content = proposal.proposed_content
        recomputed_hash = compute_plan_content_hash(content)
        if proposal.content_hash != recomputed_hash:
            raise NarrativePlanValidationError("proposal content_hash does not match its content")
        if approval.content_hash != recomputed_hash:
            raise NarrativePlanApprovalError("approval content_hash does not match the proposed content")
        if content.parent_version != proposal.expected_version:
            raise NarrativePlanValidationError(
                "proposed_content.parent_version must equal the proposal expected_version"
            )

        async with self._uow_factory() as uow:
            repository = uow.repository

            existing = await repository.get_version_by_revision(
                plan_revision_id=proposal.plan_revision_id, project_name=project_name, user_id=user_id
            )
            if existing is not None:
                return self._resolve_exact_retry(
                    existing=existing,
                    proposal=proposal,
                    approval=approval,
                    project_name=project_name,
                    user_id=user_id,
                )

            approved_elsewhere = await repository.get_version_by_approval(
                approval_ref=approval.approval_ref, project_name=project_name, user_id=user_id
            )
            if approved_elsewhere is not None:
                raise NarrativePlanApprovalError(
                    f"approval {approval.approval_ref!r} already committed revision "
                    f"{approved_elsewhere.plan_revision_id!r}"
                )

            head = await repository.lock_plan(plan_id=proposal.plan_id, project_name=project_name, user_id=user_id)
            if proposal.expected_version is None:
                if head is not None:
                    raise NarrativePlanVersionConflict(expected=None, current=head.head_version)
                new_version = 1
                history: tuple[NarrativePlanVersionSnapshot, ...] = ()
            else:
                if head is None:
                    raise NarrativePlanNotFoundError(f"narrative plan {proposal.plan_id!r} not found in scope")
                if head.head_version != proposal.expected_version:
                    raise NarrativePlanVersionConflict(expected=proposal.expected_version, current=head.head_version)
                new_version = proposal.expected_version + 1
                history = await repository.list_plan_versions(
                    plan_id=proposal.plan_id, project_name=project_name, user_id=user_id
                )

            canon_view = await self._resolve_canon_basis(content, project_name=project_name, user_id=user_id)
            plan = self._build_plan(proposal=proposal, approval=approval, version=new_version, now=now)
            self._validate_content(content=content, plan=plan, canon_view=canon_view, history=history)

            if proposal.expected_version is None:
                await repository.insert_plan(
                    NarrativePlanHeadSnapshot(
                        plan_id=proposal.plan_id,
                        user_id=user_id,
                        project_name=project_name,
                        head_version=None,
                        created_at=now,
                        created_by=proposal.created_by,
                    )
                )
            await repository.insert_version(
                self._version_snapshot(
                    proposal=proposal, approval=approval, plan=plan, project_name=project_name, user_id=user_id
                )
            )
            await repository.advance_head(
                plan_id=proposal.plan_id,
                expected_version=proposal.expected_version,
                new_version=new_version,
                project_name=project_name,
                user_id=user_id,
            )
            await repository.flush()
            await uow.commit()

        return NarrativePlanCommitResult(plan=plan, plan_revision_id=proposal.plan_revision_id)

    async def get_version(self, *, plan_id: str, version: int, project_name: str, user_id: str) -> NarrativePlan:
        async with self._uow_factory() as uow:
            snapshot = await uow.repository.get_version(
                plan_id=plan_id, version=version, project_name=project_name, user_id=user_id
            )
        if snapshot is None:
            raise NarrativePlanNotFoundError(f"narrative plan {plan_id!r} version {version} not found in scope")
        return NarrativePlan(
            plan_id=snapshot.plan_id,
            version=snapshot.version,
            content=snapshot.content,
            content_hash=snapshot.content_hash,
            committed_at=snapshot.committed_at,
            committed_by=snapshot.committed_by,
            approval_ref=snapshot.approval_ref,
        )

    # -- internals ---------------------------------------------------------------

    @staticmethod
    def _require_matching_scope(
        *,
        proposal: NarrativePlanRevisionProposal,
        approval: NarrativePlanApproval,
        project_name: str,
        user_id: str,
    ) -> None:
        if (
            approval.plan_revision_id != proposal.plan_revision_id
            or approval.plan_id != proposal.plan_id
            or approval.expected_version != proposal.expected_version
            or approval.project_name != project_name
            or approval.user_id != user_id
        ):
            raise NarrativePlanApprovalError("approval receipt does not match the proposal or request scope")

    @staticmethod
    def _resolve_exact_retry(
        *,
        existing: NarrativePlanVersionSnapshot,
        proposal: NarrativePlanRevisionProposal,
        approval: NarrativePlanApproval,
        project_name: str,
        user_id: str,
    ) -> NarrativePlanCommitResult:
        expected_parent = None if proposal.expected_version is None else proposal.expected_version
        if (
            existing.approval_ref != approval.approval_ref
            or existing.content_hash != proposal.content_hash
            or existing.plan_id != proposal.plan_id
            or existing.parent_version != expected_parent
            or existing.user_id != user_id
            or existing.project_name != project_name
        ):
            raise NarrativePlanIdentityConflictError(
                f"plan revision {proposal.plan_revision_id!r} was already committed with a different identity"
            )
        return NarrativePlanCommitResult(
            plan=NarrativePlan(
                plan_id=existing.plan_id,
                version=existing.version,
                content=existing.content,
                content_hash=existing.content_hash,
                committed_at=existing.committed_at,
                committed_by=existing.committed_by,
                approval_ref=existing.approval_ref,
            ),
            plan_revision_id=proposal.plan_revision_id,
        )

    async def _resolve_canon_basis(
        self, content: NarrativePlanContent, *, project_name: str, user_id: str
    ) -> ResolvedCanonView:
        view = await self._canon_reader.get_exact(
            branch_id=content.canon_basis.branch_id,
            canon_version_id=content.canon_basis.canon_version_id,
            project_name=project_name,
            user_id=user_id,
        )
        if view is None:
            raise NarrativePlanValidationError(
                f"canon basis {content.canon_basis.canon_version_id!r} not found in scope"
            )
        # ``get_exact`` is a claim; verify the returned identity so a fallback-to-head
        # adapter cannot approve a plan against a different Canon version.
        if (
            view.branch_id != content.canon_basis.branch_id
            or view.canon_version_id != content.canon_basis.canon_version_id
        ):
            raise NarrativePlanValidationError(
                "Canon reader returned a view that does not match the requested exact basis"
            )
        return view

    @staticmethod
    def _build_plan(
        *,
        proposal: NarrativePlanRevisionProposal,
        approval: NarrativePlanApproval,
        version: int,
        now: datetime,
    ) -> NarrativePlan:
        return NarrativePlan(
            plan_id=proposal.plan_id,
            version=version,
            content=proposal.proposed_content,
            content_hash=proposal.content_hash,
            committed_at=now,
            committed_by=approval.approved_by,
            approval_ref=approval.approval_ref,
        )

    @staticmethod
    def _version_snapshot(
        *,
        proposal: NarrativePlanRevisionProposal,
        approval: NarrativePlanApproval,
        plan: NarrativePlan,
        project_name: str,
        user_id: str,
    ) -> NarrativePlanVersionSnapshot:
        return NarrativePlanVersionSnapshot(
            plan_id=plan.plan_id,
            version=plan.version,
            user_id=user_id,
            project_name=project_name,
            plan_revision_id=proposal.plan_revision_id,
            parent_version=None if plan.version == 1 else plan.version - 1,
            canon_branch_id=proposal.proposed_content.canon_basis.branch_id,
            canon_version_id=proposal.proposed_content.canon_basis.canon_version_id,
            content=proposal.proposed_content,
            content_hash=proposal.content_hash,
            approval_ref=approval.approval_ref,
            approved_by=approval.approved_by,
            approved_at=approval.approved_at,
            committed_at=plan.committed_at,
            committed_by=plan.committed_by,
        )

    def _validate_content(
        self,
        *,
        content: NarrativePlanContent,
        plan: NarrativePlan,
        canon_view: ResolvedCanonView,
        history: tuple[NarrativePlanVersionSnapshot, ...],
    ) -> None:
        hierarchy = validate_plan_hierarchy(content)
        if not hierarchy.ok:
            raise NarrativePlanValidationError([finding.rule_id for finding in hierarchy.findings])

        previous_scenes: dict[str, list] = {}
        for snapshot in history:
            for scene in snapshot.content.scene_contracts:
                previous_scenes.setdefault(scene.scene_contract_id, []).append(scene)

        for scene in content.scene_contracts:
            if compute_scene_semantic_hash(scene) != scene.semantic_hash:
                raise NarrativePlanIdentityConflictError(
                    f"scene {scene.scene_contract_id!r} semantic_hash does not match its content"
                )
            prior = previous_scenes.get(scene.scene_contract_id)
            if prior:
                validate_scene_version(previous=prior[-1], proposed=scene)
            elif scene.version != 1:
                raise NarrativePlanIdentityConflictError(
                    f"new scene {scene.scene_contract_id!r} must start at version 1"
                )
            report = self._validator.validate_scene(canon=canon_view, plan=plan, scene=scene)
            if not report.ok:
                raise NarrativePlanValidationError([finding.rule_id for finding in report.findings])

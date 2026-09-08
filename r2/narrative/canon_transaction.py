"""Branch creation and the only approved Canon commit orchestration.

``CanonTransactionService`` is the sole Canon commit authority and the sole
caller of authoritative write-port methods. Each call owns one fresh
``CanonAuthorityUnitOfWork`` transaction: the delta, the immutable version, the
branch head, and the disposable projection all persist inside it or none do.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from enum import StrEnum
from uuid import uuid4

from r2.contracts import (
    AcceptedCanonDeltaSnapshot,
    CanonBranchSnapshot,
    CanonBranchType,
    CanonCommitApproval,
    CanonCommitResult,
    CanonContent,
    CanonDelta,
    CanonValidationReport,
    CanonVersionSnapshot,
    CreateCanonBranch,
)
from r2.contracts.common import ensure_json_value
from r2.contracts.fingerprints import canonical_json_bytes

from .canon_resolver import CanonResolver
from .canon_state import ResolvedCanonView, apply_canon_delta
from .errors import (
    CanonApprovalError,
    CanonBaseVersionConflict,
    CanonIdentityConflictError,
    CanonIntegrityError,
    CanonNotFoundError,
    CanonOperationError,
    CanonValidationError,
)
from .hashing import compute_canon_content_hash, verify_canon_delta_hash
from .ports import CanonAuthorityUnitOfWorkFactory, CanonWriteRepositoryPort
from .validation import validate_canon_candidate

_CONTENT_HASH_ALGORITHM = "sha256"
_CONTENT_HASH_VERSION = "r2-canon-content-v1"
_CONTENT_SCHEMA_VERSION = "r2-canon-schema-v1"


class CanonCommitStage(StrEnum):
    BEFORE_DELTA_INSERT = "BEFORE_DELTA_INSERT"
    AFTER_DELTA_FLUSH = "AFTER_DELTA_FLUSH"
    AFTER_VERSION_FLUSH = "AFTER_VERSION_FLUSH"
    AFTER_HEAD_FLUSH = "AFTER_HEAD_FLUSH"
    BEFORE_PROJECTION_FLUSH = "BEFORE_PROJECTION_FLUSH"
    AFTER_PROJECTION_FLUSH = "AFTER_PROJECTION_FLUSH"
    BEFORE_COMMIT = "BEFORE_COMMIT"


def new_version_id() -> str:
    return f"canon-version-{uuid4().hex}"


def ignore_commit_stage(stage: CanonCommitStage) -> None:
    return None


def _canonical_delta_bytes(delta: CanonDelta) -> bytes:
    value = {
        "canon_delta_id": delta.canon_delta_id,
        "target_branch_id": delta.target_branch_id,
        "base_canon_version_id": delta.base_canon_version_id,
        "operations": [operation.model_dump(mode="json") for operation in delta.operations],
        "source_change_set_refs": sorted(set(delta.source_change_set_refs)),
        "author_decision_refs": sorted(set(delta.author_decision_refs)),
        "validation_report_refs": sorted(set(delta.validation_report_refs)),
        "payload_hash": delta.payload_hash,
        "payload_hash_algorithm": delta.payload_hash_algorithm,
        "payload_hash_version": delta.payload_hash_version,
        "content_schema_version": delta.content_schema_version,
        "created_at": delta.created_at.isoformat(),
        "created_by": delta.created_by,
    }
    return canonical_json_bytes(ensure_json_value(value))


class CanonTransactionService:
    def __init__(
        self,
        uow_factory: CanonAuthorityUnitOfWorkFactory,
        *,
        version_id_factory: Callable[[], str] = new_version_id,
        fault_hook: Callable[[CanonCommitStage], None] = ignore_commit_stage,
    ) -> None:
        self._uow_factory = uow_factory
        self._version_id_factory = version_id_factory
        self._fault_hook = fault_hook

    async def create_branch(self, command: CreateCanonBranch) -> CanonBranchSnapshot:
        async with self._uow_factory() as uow:
            repository = uow.repository
            existing = await repository.get_branch(
                branch_id=command.branch_id, project_name=command.project_name, user_id=command.user_id
            )
            if existing is not None:
                self._require_matching_branch(existing, command)
                return existing

            if command.branch_type is CanonBranchType.MAIN:
                if command.parent_branch_id is not None or command.parent_version_id is not None:
                    raise CanonValidationError("a MAIN Canon branch cannot declare a parent")
            else:
                if command.parent_branch_id is None or command.parent_version_id is None:
                    raise CanonValidationError(
                        "a NARRATIVE_BRANCH Canon branch requires a parent branch and pinned version"
                    )
                parent_branch = await repository.get_branch(
                    branch_id=command.parent_branch_id,
                    project_name=command.project_name,
                    user_id=command.user_id,
                )
                if parent_branch is None:
                    raise CanonNotFoundError(f"parent Canon branch {command.parent_branch_id!r} not found in scope")
                parent_version = await repository.get_version(
                    canon_version_id=command.parent_version_id,
                    project_name=command.project_name,
                    user_id=command.user_id,
                )
                if parent_version is None:
                    raise CanonNotFoundError(f"pinned Canon version {command.parent_version_id!r} not found in scope")
                if parent_version.branch_id != command.parent_branch_id:
                    raise CanonValidationError("the pinned Canon version does not belong to the parent branch")

            snapshot = CanonBranchSnapshot(
                branch_id=command.branch_id,
                user_id=command.user_id,
                project_name=command.project_name,
                branch_type=command.branch_type,
                parent_branch_id=command.parent_branch_id,
                parent_version_id=command.parent_version_id,
                head_version_id=None,
                created_at=command.created_at,
                created_by=command.created_by,
            )
            await repository.insert_branch(snapshot)
            await uow.commit()
            return snapshot

    @staticmethod
    def _require_matching_branch(existing: CanonBranchSnapshot, command: CreateCanonBranch) -> None:
        if (
            existing.branch_type is not command.branch_type
            or existing.parent_branch_id != command.parent_branch_id
            or existing.parent_version_id != command.parent_version_id
            or existing.user_id != command.user_id
            or existing.project_name != command.project_name
            or existing.created_by != command.created_by
        ):
            raise CanonIdentityConflictError(
                f"Canon branch {command.branch_id!r} already exists with a different definition"
            )

    async def commit(
        self,
        *,
        delta: CanonDelta,
        approval: CanonCommitApproval,
        project_name: str,
        user_id: str,
        now: datetime,
    ) -> CanonCommitResult:
        verify_canon_delta_hash(delta)
        self._validate_approval(delta=delta, approval=approval, project_name=project_name, user_id=user_id)

        async with self._uow_factory() as uow:
            repository = uow.repository
            branch = await repository.lock_branch(
                branch_id=delta.target_branch_id, project_name=project_name, user_id=user_id
            )

            existing = await repository.get_accepted_delta(
                canon_delta_id=delta.canon_delta_id, project_name=project_name, user_id=user_id
            )
            if existing is not None:
                return await self._resolve_exact_retry(
                    existing=existing,
                    delta=delta,
                    approval=approval,
                    repository=repository,
                    project_name=project_name,
                    user_id=user_id,
                )

            prior = await repository.get_accepted_delta_by_approval_ref(
                approval_ref=approval.approval_ref, project_name=project_name, user_id=user_id
            )
            if prior is not None and prior.delta.canon_delta_id != delta.canon_delta_id:
                raise CanonApprovalError(
                    f"approval {approval.approval_ref!r} already authorized Canon delta {prior.delta.canon_delta_id!r}"
                )

            current_base = branch.head_version_id if branch.head_version_id is not None else branch.parent_version_id
            if delta.base_canon_version_id != current_base:
                raise CanonBaseVersionConflict(expected=delta.base_canon_version_id, current=current_base)

            base_view = await CanonResolver(repository, clock=lambda: now).resolve(
                branch_id=branch.branch_id,
                version_id=current_base,
                project_name=project_name,
                user_id=user_id,
            )
            try:
                candidate = apply_canon_delta(base_view.content, delta)
            except CanonOperationError as exc:
                raise CanonValidationError(str(exc)) from exc

            report = validate_canon_candidate(base=base_view.content, delta=delta, candidate=candidate)
            if not report.ok:
                raise CanonValidationError(report)
            if candidate == base_view.content:
                raise CanonValidationError("Canon delta is a semantic no-op")

            self._validate_approval(delta=delta, approval=approval, project_name=project_name, user_id=user_id)

            result = await self._append_version_and_projection(
                repository=repository,
                branch=branch,
                delta=delta,
                approval=approval,
                candidate=candidate,
                validation_report=report,
                project_name=project_name,
                user_id=user_id,
                now=now,
            )
            self._fault_hook(CanonCommitStage.BEFORE_COMMIT)
            await uow.commit()
            return result

    def _validate_approval(
        self,
        *,
        delta: CanonDelta,
        approval: CanonCommitApproval,
        project_name: str,
        user_id: str,
    ) -> None:
        if approval.canon_delta_id != delta.canon_delta_id:
            raise CanonApprovalError("Canon commit approval is bound to a different delta id")
        if approval.payload_hash != delta.payload_hash:
            raise CanonApprovalError("Canon commit approval payload hash does not match the delta")
        if approval.project_name != project_name or approval.user_id != user_id:
            raise CanonApprovalError("Canon commit approval scope does not match the request scope")

    async def _resolve_exact_retry(
        self,
        *,
        existing: AcceptedCanonDeltaSnapshot,
        delta: CanonDelta,
        approval: CanonCommitApproval,
        repository: CanonWriteRepositoryPort,
        project_name: str,
        user_id: str,
    ) -> CanonCommitResult:
        if (
            _canonical_delta_bytes(existing.delta) != _canonical_delta_bytes(delta)
            or existing.delta.payload_hash != delta.payload_hash
            or existing.approval != approval
        ):
            raise CanonIdentityConflictError(
                f"Canon delta {delta.canon_delta_id!r} was already accepted with a different definition"
            )
        stored_version = await repository.get_version(
            canon_version_id=existing.committed_version_id, project_name=project_name, user_id=user_id
        )
        if stored_version is None:
            raise CanonIntegrityError(f"accepted Canon delta {delta.canon_delta_id!r} links a missing version")
        return CanonCommitResult(
            accepted_delta=existing,
            version=stored_version,
            validation_report=CanonValidationReport(findings=()),
        )

    async def _append_version_and_projection(
        self,
        *,
        repository: CanonWriteRepositoryPort,
        branch: CanonBranchSnapshot,
        delta: CanonDelta,
        approval: CanonCommitApproval,
        candidate: CanonContent,
        validation_report: CanonValidationReport,
        project_name: str,
        user_id: str,
        now: datetime,
    ) -> CanonCommitResult:
        version_id = self._version_id_factory()
        if branch.head_version_id is None:
            version_number = 1
            version_parent_id: str | None = None
        else:
            head_version = await repository.get_version(
                canon_version_id=branch.head_version_id, project_name=project_name, user_id=user_id
            )
            if head_version is None:
                raise CanonIntegrityError("locked Canon branch head points to a missing version")
            version_number = head_version.version_number + 1
            version_parent_id = branch.head_version_id

        content_hash = compute_canon_content_hash(candidate)
        version = CanonVersionSnapshot(
            canon_version_id=version_id,
            branch_id=branch.branch_id,
            version_number=version_number,
            parent_version_id=version_parent_id,
            committed_delta_id=delta.canon_delta_id,
            committed_at=now,
            committed_by=approval.approved_by,
            content_hash=content_hash,
            content_hash_algorithm=_CONTENT_HASH_ALGORITHM,
            content_hash_version=_CONTENT_HASH_VERSION,
            content_schema_version=_CONTENT_SCHEMA_VERSION,
        )
        accepted = AcceptedCanonDeltaSnapshot(delta=delta, approval=approval, committed_version_id=version_id)
        resolved_view = ResolvedCanonView(
            canon_version_id=version_id,
            branch_id=branch.branch_id,
            content_hash=content_hash,
            content=candidate,
        )

        self._fault_hook(CanonCommitStage.BEFORE_DELTA_INSERT)
        await repository.insert_delta(accepted)
        self._fault_hook(CanonCommitStage.AFTER_DELTA_FLUSH)
        await repository.insert_version(version)
        self._fault_hook(CanonCommitStage.AFTER_VERSION_FLUSH)
        await repository.advance_head(
            branch_id=branch.branch_id,
            expected_head_id=branch.head_version_id,
            version_id=version_id,
            project_name=project_name,
            user_id=user_id,
        )
        self._fault_hook(CanonCommitStage.AFTER_HEAD_FLUSH)
        self._fault_hook(CanonCommitStage.BEFORE_PROJECTION_FLUSH)
        await repository.upsert_projection(view=resolved_view, built_at=now, project_name=project_name, user_id=user_id)
        await repository.flush()
        self._fault_hook(CanonCommitStage.AFTER_PROJECTION_FLUSH)

        return CanonCommitResult(accepted_delta=accepted, version=version, validation_report=validation_report)

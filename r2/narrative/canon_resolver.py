"""Deterministic version-DAG replay with projection verification and rebuild.

The resolver reads through ``CanonProjectionRepositoryPort``; it never opens a
session, commits, or rolls back. A stored projection is trusted only when its
metadata equals the immutable version receipt and its content re-hashes to the
recorded hash; otherwise the version is replayed from its accepted delta and the
disposable projection row is rewritten.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from r2.contracts import CanonBranchSnapshot, CanonContent, CanonDelta, CanonVersionSnapshot

from .canon_state import ResolvedCanonView, apply_canon_delta, empty_canon_content
from .errors import CanonIntegrityError, CanonNotFoundError, CanonOperationError
from .hashing import compute_canon_content_hash, verify_canon_delta_hash
from .ports import CanonProjectionRepositoryPort
from .validation import validate_canon_candidate


def _utc_now() -> datetime:
    return datetime.now(UTC)


class CanonResolver:
    def __init__(
        self,
        repository: CanonProjectionRepositoryPort,
        *,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self._repository = repository
        self._clock = clock

    async def resolve(
        self, *, branch_id: str, version_id: str | None, project_name: str, user_id: str
    ) -> ResolvedCanonView:
        branch = await self._repository.get_branch(branch_id=branch_id, project_name=project_name, user_id=user_id)
        if branch is None:
            raise CanonNotFoundError(f"Canon branch {branch_id!r} not found in scope")

        selected = version_id if version_id is not None else branch.head_version_id
        if selected is None:
            if branch.parent_version_id is None:
                return ResolvedCanonView.for_empty_branch(branch)
            parent = await self._resolve_version(
                branch.parent_version_id, project_name=project_name, user_id=user_id, visiting=frozenset()
            )
            return parent.model_copy(update={"branch_id": branch.branch_id})

        await self._require_version_reachable_from_branch(
            branch=branch, version_id=selected, project_name=project_name, user_id=user_id
        )
        return await self._resolve_version(selected, project_name=project_name, user_id=user_id, visiting=frozenset())

    async def _require_version_reachable_from_branch(
        self, *, branch: CanonBranchSnapshot, version_id: str, project_name: str, user_id: str
    ) -> None:
        version = await self._repository.get_version(
            canon_version_id=version_id, project_name=project_name, user_id=user_id
        )
        if version is None:
            raise CanonNotFoundError(f"Canon version {version_id!r} not found in scope")
        if version.branch_id != branch.branch_id:
            raise CanonIntegrityError(f"Canon version {version_id!r} does not belong to branch {branch.branch_id!r}")

    async def _resolve_version(
        self, version_id: str, *, project_name: str, user_id: str, visiting: frozenset[str]
    ) -> ResolvedCanonView:
        if version_id in visiting:
            raise CanonIntegrityError(f"Canon version lineage contains a cycle at {version_id!r}")
        visiting = visiting | {version_id}

        version = await self._repository.get_version(
            canon_version_id=version_id, project_name=project_name, user_id=user_id
        )
        if version is None:
            raise CanonNotFoundError(f"Canon version {version_id!r} not found in scope")

        cached = await self._repository.load_projection(
            canon_version_id=version_id, project_name=project_name, user_id=user_id
        )
        if cached is not None and self._projection_matches_receipt(cached, version):
            return cached

        rebuilt = await self._rebuild_version(version, project_name=project_name, user_id=user_id, visiting=visiting)
        await self._repository.upsert_projection(
            view=rebuilt, built_at=self._clock(), project_name=project_name, user_id=user_id
        )
        return rebuilt

    def _projection_matches_receipt(self, view: ResolvedCanonView, version: CanonVersionSnapshot) -> bool:
        if (
            view.canon_version_id != version.canon_version_id
            or view.content_hash != version.content_hash
            or view.content_hash_algorithm != version.content_hash_algorithm
            or view.content_hash_version != version.content_hash_version
            or view.content_schema_version != version.content_schema_version
        ):
            return False
        recomputed = compute_canon_content_hash(
            view.content,
            algorithm=version.content_hash_algorithm,
            hash_version=version.content_hash_version,
            schema_version=version.content_schema_version,
        )
        return recomputed == version.content_hash

    async def _rebuild_version(
        self,
        version: CanonVersionSnapshot,
        *,
        project_name: str,
        user_id: str,
        visiting: frozenset[str],
    ) -> ResolvedCanonView:
        branch = await self._repository.get_branch(
            branch_id=version.branch_id, project_name=project_name, user_id=user_id
        )
        if branch is None:
            raise CanonIntegrityError(
                f"Canon version {version.canon_version_id!r} points to unknown branch {version.branch_id!r}"
            )

        accepted = await self._repository.get_accepted_delta(
            canon_delta_id=version.committed_delta_id, project_name=project_name, user_id=user_id
        )
        if accepted is None:
            raise CanonIntegrityError(
                f"Canon version {version.canon_version_id!r} references missing delta {version.committed_delta_id!r}"
            )
        delta = accepted.delta
        verify_canon_delta_hash(delta)

        base_content, expected_base = await self._resolve_semantic_base(
            version=version, branch=branch, project_name=project_name, user_id=user_id, visiting=visiting
        )
        if delta.base_canon_version_id != expected_base:
            raise CanonIntegrityError(
                f"Canon delta {delta.canon_delta_id!r} semantic base "
                f"{delta.base_canon_version_id!r} does not match expected {expected_base!r}"
            )

        candidate = self._apply_stored_delta(base_content, delta)
        report = validate_canon_candidate(base=base_content, delta=delta, candidate=candidate)
        if not report.ok:
            raise CanonIntegrityError(
                f"stored Canon delta {delta.canon_delta_id!r} fails validation: "
                f"{[finding.rule_id for finding in report.findings]}"
            )

        recomputed = compute_canon_content_hash(
            candidate,
            algorithm=version.content_hash_algorithm,
            hash_version=version.content_hash_version,
            schema_version=version.content_schema_version,
        )
        if recomputed != version.content_hash:
            raise CanonIntegrityError(
                f"recomputed content hash for Canon version {version.canon_version_id!r} "
                "does not match the stored receipt"
            )

        return ResolvedCanonView(
            canon_version_id=version.canon_version_id,
            branch_id=version.branch_id,
            content_hash=version.content_hash,
            content_hash_algorithm=version.content_hash_algorithm,
            content_hash_version=version.content_hash_version,
            content_schema_version=version.content_schema_version,
            content=candidate,
        )

    async def _resolve_semantic_base(
        self,
        *,
        version: CanonVersionSnapshot,
        branch: CanonBranchSnapshot,
        project_name: str,
        user_id: str,
        visiting: frozenset[str],
    ) -> tuple[CanonContent, str | None]:
        if version.parent_version_id is not None:
            parent = await self._resolve_version(
                version.parent_version_id, project_name=project_name, user_id=user_id, visiting=visiting
            )
            return parent.content, version.parent_version_id
        if branch.parent_version_id is not None:
            pinned = await self._resolve_version(
                branch.parent_version_id, project_name=project_name, user_id=user_id, visiting=visiting
            )
            return pinned.content, branch.parent_version_id
        return empty_canon_content(), None

    @staticmethod
    def _apply_stored_delta(base_content: CanonContent, delta: CanonDelta) -> CanonContent:
        try:
            return apply_canon_delta(base_content, delta)
        except CanonOperationError as exc:
            raise CanonIntegrityError(
                f"stored Canon delta {delta.canon_delta_id!r} does not apply to its base: {exc}"
            ) from exc

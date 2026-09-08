"""Executable logical-FK, lineage, linkage, and hash integrity checker.

The database omits the branch head/parent version foreign keys to avoid a
create-time cycle; this checker compensates. It reads only through the scoped
``CanonReadRepositoryPort`` (so nonexistent and cross-scope identifiers collapse
to the same ``*_MISSING_OR_OUT_OF_SCOPE`` rule), never consults a projection as
authority, collects findings rather than repairing, and leaves every row byte
identical.
"""

from __future__ import annotations

from pydantic import ConfigDict

from r2.contracts import CanonBranchSnapshot, CanonBranchType, CanonContent, CanonVersionSnapshot
from r2.contracts.common import NonEmptyStr, R2ContractModel

from .canon_state import apply_canon_delta, empty_canon_content
from .errors import CanonIntegrityError, CanonOperationError
from .hashing import compute_canon_content_hash, verify_canon_delta_hash
from .ports import CanonReadRepositoryPort

INTEGRITY_RULE_ORDER = (
    "M5A_HEAD_MISSING_OR_OUT_OF_SCOPE",
    "M5A_HEAD_BRANCH_MISMATCH",
    "M5A_HEAD_NOT_LATEST",
    "M5A_VERSION_GAP",
    "M5A_PARENT_MISSING_OR_OUT_OF_SCOPE",
    "M5A_PARENT_BRANCH_MISMATCH",
    "M5A_VERSION_PARENT_MISMATCH",
    "M5A_DELTA_LINK_MISMATCH",
    "M5A_HASH_VERSION_UNSUPPORTED",
    "M5A_AUTHORITATIVE_HASH_MISMATCH",
)
_RULE_INDEX = {rule_id: index for index, rule_id in enumerate(INTEGRITY_RULE_ORDER)}

_ALGORITHM = "sha256"
_CONTENT_HASH_VERSION = "r2-canon-content-v1"
_SCHEMA_VERSION = "r2-canon-schema-v1"


class CanonIntegrityFinding(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    rule_id: NonEmptyStr
    branch_id: NonEmptyStr
    affected_refs: tuple[NonEmptyStr, ...]
    message: NonEmptyStr


class CanonIntegrityReport(R2ContractModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    findings: tuple[CanonIntegrityFinding, ...]

    @property
    def ok(self) -> bool:
        return not self.findings


class CanonIntegrityChecker:
    def __init__(self, repository: CanonReadRepositoryPort) -> None:
        self._repository = repository

    async def check_scope(self, *, project_name: str, user_id: str) -> CanonIntegrityReport:
        branches = await self._repository.list_scope_branches(project_name=project_name, user_id=user_id)
        ordered = sorted(branches, key=lambda item: (item.branch_type is not CanonBranchType.MAIN, item.branch_id))
        content_by_version: dict[str, CanonContent] = {}
        findings: list[CanonIntegrityFinding] = []
        for branch in ordered:
            findings.extend(
                await self._check_branch(branch, content_by_version, project_name=project_name, user_id=user_id)
            )
        findings.sort(key=lambda item: (_RULE_INDEX[item.rule_id], item.branch_id, item.affected_refs))
        return CanonIntegrityReport(findings=tuple(findings))

    @staticmethod
    def _finding(
        rule_id: str, branch: CanonBranchSnapshot, affected_refs: tuple[str, ...], message: str
    ) -> CanonIntegrityFinding:
        return CanonIntegrityFinding(
            rule_id=rule_id, branch_id=branch.branch_id, affected_refs=affected_refs, message=message
        )

    async def _check_branch(
        self,
        branch: CanonBranchSnapshot,
        content_by_version: dict[str, CanonContent],
        *,
        project_name: str,
        user_id: str,
    ) -> list[CanonIntegrityFinding]:
        findings: list[CanonIntegrityFinding] = []
        versions = await self._repository.list_branch_versions(
            branch_id=branch.branch_id, project_name=project_name, user_id=user_id
        )
        numbers = [item.version_number for item in versions]

        findings.extend(await self._check_head(branch, versions, project_name=project_name, user_id=user_id))
        if numbers != list(range(1, len(versions) + 1)):
            findings.append(
                self._finding(
                    "M5A_VERSION_GAP",
                    branch,
                    (branch.branch_id,),
                    f"branch version numbers are not contiguous from 1: {numbers}",
                )
            )

        running, replay_ok, pinned_base = await self._branch_base(
            branch, content_by_version, findings, project_name=project_name, user_id=user_id
        )

        previous_local_id: str | None = None
        for index, version in enumerate(versions):
            expected_number = index + 1
            semantic_base = pinned_base if expected_number == 1 else version.parent_version_id
            findings.extend(
                await self._check_version_parent(
                    branch,
                    version,
                    expected_number=expected_number,
                    previous_local_id=previous_local_id,
                    project_name=project_name,
                    user_id=user_id,
                )
            )

            accepted = await self._repository.get_accepted_delta(
                canon_delta_id=version.committed_delta_id, project_name=project_name, user_id=user_id
            )
            if accepted is None:
                findings.append(
                    self._finding(
                        "M5A_DELTA_LINK_MISMATCH",
                        branch,
                        (version.canon_version_id, version.committed_delta_id),
                        f"version {version.canon_version_id!r} references missing delta {version.committed_delta_id!r}",
                    )
                )
                replay_ok = False
            elif (
                accepted.committed_version_id != version.canon_version_id
                or accepted.delta.target_branch_id != branch.branch_id
                or accepted.delta.base_canon_version_id != semantic_base
            ):
                findings.append(
                    self._finding(
                        "M5A_DELTA_LINK_MISMATCH",
                        branch,
                        (version.canon_version_id, version.committed_delta_id),
                        f"version {version.canon_version_id!r} delta linkage is inconsistent",
                    )
                )

            if (
                version.content_hash_algorithm != _ALGORITHM
                or version.content_hash_version != _CONTENT_HASH_VERSION
                or version.content_schema_version != _SCHEMA_VERSION
            ):
                findings.append(
                    self._finding(
                        "M5A_HASH_VERSION_UNSUPPORTED",
                        branch,
                        (version.canon_version_id,),
                        f"version {version.canon_version_id!r} uses unsupported hash or schema selectors",
                    )
                )
                replay_ok = False

            if replay_ok and accepted is not None:
                try:
                    verify_canon_delta_hash(accepted.delta)
                    running = apply_canon_delta(running, accepted.delta)
                    recomputed = compute_canon_content_hash(running)
                except (CanonIntegrityError, CanonOperationError):
                    findings.append(
                        self._finding(
                            "M5A_AUTHORITATIVE_HASH_MISMATCH",
                            branch,
                            (version.canon_version_id,),
                            f"version {version.canon_version_id!r} cannot be replayed from its accepted delta",
                        )
                    )
                    replay_ok = False
                else:
                    if recomputed != version.content_hash:
                        findings.append(
                            self._finding(
                                "M5A_AUTHORITATIVE_HASH_MISMATCH",
                                branch,
                                (version.canon_version_id,),
                                f"version {version.canon_version_id!r} content hash does not match its "
                                "replayed content",
                            )
                        )
                    content_by_version[version.canon_version_id] = running

            previous_local_id = version.canon_version_id

        return findings

    async def _check_head(
        self,
        branch: CanonBranchSnapshot,
        versions: tuple[CanonVersionSnapshot, ...],
        *,
        project_name: str,
        user_id: str,
    ) -> list[CanonIntegrityFinding]:
        head_id = branch.head_version_id
        if head_id is None:
            if versions:
                return [
                    self._finding(
                        "M5A_HEAD_NOT_LATEST",
                        branch,
                        (branch.branch_id,),
                        "branch head is null while local versions exist",
                    )
                ]
            return []

        head_version = await self._repository.get_version(
            canon_version_id=head_id, project_name=project_name, user_id=user_id
        )
        if head_version is None:
            return [
                self._finding(
                    "M5A_HEAD_MISSING_OR_OUT_OF_SCOPE",
                    branch,
                    (head_id,),
                    f"branch head {head_id!r} does not resolve in scope",
                )
            ]
        if head_version.branch_id != branch.branch_id:
            return [
                self._finding(
                    "M5A_HEAD_BRANCH_MISMATCH",
                    branch,
                    (head_id,),
                    f"branch head {head_id!r} belongs to branch {head_version.branch_id!r}",
                )
            ]
        latest_id = versions[-1].canon_version_id if versions else None
        if head_id != latest_id:
            return [
                self._finding(
                    "M5A_HEAD_NOT_LATEST",
                    branch,
                    (head_id,),
                    f"branch head {head_id!r} is not the highest local version",
                )
            ]
        return []

    async def _branch_base(
        self,
        branch: CanonBranchSnapshot,
        content_by_version: dict[str, CanonContent],
        findings: list[CanonIntegrityFinding],
        *,
        project_name: str,
        user_id: str,
    ) -> tuple[CanonContent, bool, str | None]:
        if branch.branch_type is CanonBranchType.MAIN:
            return empty_canon_content(), True, None

        pinned_id = branch.parent_version_id
        if pinned_id is None:
            findings.append(
                self._finding(
                    "M5A_PARENT_MISSING_OR_OUT_OF_SCOPE",
                    branch,
                    (branch.branch_id,),
                    "narrative branch does not pin a parent version",
                )
            )
            return empty_canon_content(), False, None

        pinned = await self._repository.get_version(
            canon_version_id=pinned_id, project_name=project_name, user_id=user_id
        )
        if pinned is None:
            findings.append(
                self._finding(
                    "M5A_PARENT_MISSING_OR_OUT_OF_SCOPE",
                    branch,
                    (pinned_id,),
                    f"pinned parent version {pinned_id!r} does not resolve in scope",
                )
            )
            return empty_canon_content(), False, pinned_id
        if pinned.branch_id != branch.parent_branch_id:
            findings.append(
                self._finding(
                    "M5A_PARENT_BRANCH_MISMATCH",
                    branch,
                    (pinned_id,),
                    f"pinned parent {pinned_id!r} belongs to branch {pinned.branch_id!r}",
                )
            )
            return empty_canon_content(), False, pinned_id

        base_content = content_by_version.get(pinned.canon_version_id)
        if base_content is None:
            return empty_canon_content(), False, pinned_id
        return base_content, True, pinned_id

    async def _check_version_parent(
        self,
        branch: CanonBranchSnapshot,
        version: CanonVersionSnapshot,
        *,
        expected_number: int,
        previous_local_id: str | None,
        project_name: str,
        user_id: str,
    ) -> list[CanonIntegrityFinding]:
        parent_version_id = version.parent_version_id
        version_id = version.canon_version_id
        findings: list[CanonIntegrityFinding] = []

        if expected_number == 1:
            if parent_version_id is not None:
                findings.append(
                    self._finding(
                        "M5A_VERSION_PARENT_MISMATCH",
                        branch,
                        (version_id,),
                        f"version {version_id!r} is version 1 but declares a local parent",
                    )
                )
            return findings

        if parent_version_id != previous_local_id:
            findings.append(
                self._finding(
                    "M5A_VERSION_PARENT_MISMATCH",
                    branch,
                    (version_id, str(parent_version_id)),
                    f"version {version_id!r} local parent should be {previous_local_id!r}",
                )
            )
        if parent_version_id is None:
            findings.append(
                self._finding(
                    "M5A_PARENT_MISSING_OR_OUT_OF_SCOPE",
                    branch,
                    (version_id,),
                    f"version {version_id!r} after version 1 has a null local parent",
                )
            )
            return findings

        local_parent = await self._repository.get_version(
            canon_version_id=parent_version_id, project_name=project_name, user_id=user_id
        )
        if local_parent is None:
            findings.append(
                self._finding(
                    "M5A_PARENT_MISSING_OR_OUT_OF_SCOPE",
                    branch,
                    (parent_version_id,),
                    f"local parent {parent_version_id!r} does not resolve in scope",
                )
            )
        elif local_parent.branch_id != branch.branch_id:
            findings.append(
                self._finding(
                    "M5A_PARENT_BRANCH_MISMATCH",
                    branch,
                    (parent_version_id,),
                    f"local parent {parent_version_id!r} belongs to branch {local_parent.branch_id!r}",
                )
            )
        return findings

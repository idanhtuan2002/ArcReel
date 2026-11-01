"""Manifest-bound automatic narrative provenance and final owner-transaction authority."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.canon_uow import CanonCommitBasisError, guarded_canon_authority_uow_factory, require_canon_commit_basis
from lib.db.narrative_lifecycle_uow import SqlAlchemyNarrativeLifecycleUnitOfWork
from lib.db.narrative_plan_uow import SqlAlchemyNarrativePlanUnitOfWork
from lib.db.repositories.narrative_plan import NarrativePlanRepository
from r2.automation.authorization import automation_authorization_reference
from r2.automation.identity import digest_value
from r2.contracts import CanonCommitResult, NarrativePlanCommitResult
from r2.contracts.automation import AuthorizationSubject, AutomationAuthorizationV1, AutomationOperation
from r2.contracts.common import R2ContractModel, ensure_json_value
from r2.contracts.narrative_lifecycle import (
    NarrativeAutomationDecisionAuthorizationV1,
    NarrativeAutomationRetryAuthenticationV1,
    NarrativeDecisionCommand,
    NarrativeDecisionReceipt,
    NarrativeWorkScope,
    RevisionAcceptanceCommand,
    RevisionAcceptanceHead,
)
from r2.narrative.canon_transaction import CanonTransactionService
from r2.narrative.errors import CanonError
from r2.narrative_lifecycle.acceptance import NarrativeAcceptanceService
from r2.narrative_lifecycle.authority_kernel import head_lock_sort_key
from r2.narrative_lifecycle.automation import automatic_authorization_fingerprints
from r2.narrative_lifecycle.errors import NarrativeDecisionAuthorizationError
from r2.narrative_lifecycle.evidence import NarrativeLifecycleEvidenceService
from r2.narrative_lifecycle.ports import NarrativeLifecycleUnitOfWorkFactory
from server.services.automation_grants import RunAutomationAuthority
from server.story_authoring.checks import Severity
from server.story_authoring.commit import (
    MANIFEST_SCHEMA,
    ManuscriptCommitManifest,
    commit_manifest_canon,
    commit_manifest_plan,
    compile_manifest_scene,
)
from server.story_authoring.narrative import (
    StoryBibleInput,
    StoryIdentity,
    acceptance_command,
    committed_canon_reader,
    committed_readers,
)

_BINDING_SEAL = object()


def _ref(prefix: str, values: list[str]) -> str:
    return prefix + digest_value("r2.automatic-narrative-reference.v1", ensure_json_value(values)).removeprefix(
        "sha256:"
    )


class _BoundNarrativeUnitOfWork(SqlAlchemyNarrativeLifecycleUnitOfWork):
    def __init__(self, owner: AutomaticNarrativeAuthority) -> None:
        super().__init__(owner._sessions)
        self.owner = owner
        self.locked_heads: dict[str, RevisionAcceptanceHead] = {}
        self.sources_locked = False

    async def __aenter__(self) -> Self:
        await super().__aenter__()
        try:
            await self.owner._lock_sources(self)
            self.sources_locked = True
            return self
        except BaseException as exc:
            await super().__aexit__(type(exc), exc, exc.__traceback__)
            raise


class _EvidenceCommitFence(_BoundNarrativeUnitOfWork):
    def __init__(self, owner: AutomaticNarrativeAuthority, index: int) -> None:
        super().__init__(owner)
        self.index = index

    async def _guard(self) -> None:
        self.owner._require_prefix(self, self.index)
        await self.owner._require_root(self.session)

    async def commit(self) -> None:
        await self._guard()
        await super().commit()

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        try:
            if exc_type is None and self.session.in_transaction():
                await self._guard()
        finally:
            await super().__aexit__(exc_type, exc, traceback)


class _PlanCommitFence(SqlAlchemyNarrativePlanUnitOfWork):
    def __init__(self, owner: AutomaticNarrativeAuthority) -> None:
        super().__init__(owner._sessions)
        self.owner = owner

    async def __aenter__(self) -> Self:
        await super().__aenter__()
        try:
            await self.owner._lock_canon(self.session)
            await self.repository.lock_plan(
                plan_id=self.owner._manifest.plan.plan_id,
                user_id=self.owner._subject.user_id,
                project_name=self.owner._subject.project_name,
            )
            return self
        except BaseException as exc:
            await super().__aexit__(type(exc), exc, exc.__traceback__)
            raise

    async def _guard(self) -> None:
        head = await self.repository.lock_plan(
            plan_id=self.owner._manifest.plan.plan_id,
            user_id=self.owner._subject.user_id,
            project_name=self.owner._subject.project_name,
        )
        if head is None or head.head_version != (self.owner._manifest.plan.expected_version or 0) + 1:
            raise NarrativeDecisionAuthorizationError("PLAN_BASIS_MOVED")
        await self.owner._require_root(self.session)

    async def commit(self) -> None:
        await self._guard()
        await super().commit()

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        try:
            if exc_type is None and self.session.in_transaction():
                await self._guard()
        finally:
            await super().__aexit__(exc_type, exc, traceback)


def _only_stylistic(manifest: ManuscriptCommitManifest, quality_record: bytes | None) -> bool:
    if not manifest.findings_open:
        return True
    if quality_record is None or manifest.quality_record_digest is None:
        return False
    if "sha256:" + hashlib.sha256(quality_record).hexdigest() != manifest.quality_record_digest:
        return False
    try:
        findings = json.loads(quality_record)["findings"]
        severities = {str(f["id"]): f["severity"] for f in findings}
    except (ValueError, KeyError, TypeError):
        return False
    return all(severities.get(finding) == Severity.STYLISTIC.value for finding in manifest.findings_open)


class AutomaticNarrativeAuthority:
    """Prepared provenance grants no effect without the final guard in this adapter's own UoW."""

    def __init__(
        self,
        *,
        sessions: async_sessionmaker[AsyncSession],
        authority: RunAutomationAuthority,
        subject: AuthorizationSubject,
        manifest: ManuscriptCommitManifest,
        proof: AutomationAuthorizationV1,
        binding: object | None = None,
    ) -> None:
        if binding is not _BINDING_SEAL:
            raise NarrativeDecisionAuthorizationError("VALIDATED_MANIFEST_BINDING_REQUIRED")
        self._sessions, self._authority = sessions, authority
        self._subject, self._manifest, self._proof = subject, manifest, proof
        self._reference = automation_authorization_reference(proof)

    @classmethod
    async def bind(
        cls,
        *,
        sessions: async_sessionmaker[AsyncSession],
        authority: RunAutomationAuthority,
        subject: AuthorizationSubject,
        manifest: ManuscriptCommitManifest,
        quality_record: bytes | None = None,
    ) -> Self:
        """Bind a manifest with no offered exception. Open findings bind only when ``quality_record`` is the
        manifest's exact quality record and names every open finding as ``STYLISTIC``."""
        if type(authority) is not RunAutomationAuthority:
            raise NarrativeDecisionAuthorizationError("ACTIVATED_AUTOMATION_AUTHORITY_REQUIRED")
        subject = AuthorizationSubject.model_validate(subject)
        manifest = ManuscriptCommitManifest.model_validate_json(manifest.model_dump_json())
        if manifest.exceptions_offered or not _only_stylistic(manifest, quality_record):
            raise NarrativeDecisionAuthorizationError("UNRESOLVED_STORY_FINDINGS")
        if (
            subject.operation is not AutomationOperation.STORY_COMMIT
            or subject.subject_digest != manifest.digest()
            or manifest.schema_id != MANIFEST_SCHEMA
            or not manifest.scenes
            or manifest.plan.proposed_content.canon_basis.branch_id != manifest.canon_genesis.target_branch_id
            or manifest.plan.proposed_content.canon_basis.canon_version_id != manifest.canon_version_id
            or len({entry.decision_id for entry in manifest.scenes}) != len(manifest.scenes)
        ):
            raise NarrativeDecisionAuthorizationError("MANIFEST_BINDING_MISMATCH")
        identity = StoryIdentity(subject.user_id, subject.project_name, manifest.run_id)
        if (identity.canon_branch_id, identity.plan_id) != (
            manifest.canon_genesis.target_branch_id,
            manifest.plan.plan_id,
        ):
            raise NarrativeDecisionAuthorizationError("MANIFEST_BINDING_MISMATCH")
        version = (manifest.plan.expected_version or 0) + 1
        for entry in manifest.scenes:
            scope = entry.revision.work_scope
            if (
                (scope.user_id, scope.project_name, scope.plan_id, scope.canon_branch_id)
                != (
                    subject.user_id,
                    subject.project_name,
                    manifest.plan.plan_id,
                    manifest.canon_genesis.target_branch_id,
                )
                or entry.candidate.work_scope != scope
                or entry.revision.base_candidate_id != entry.candidate.candidate_id
                or entry.revision.base_canon_version_id != manifest.canon_version_id
                or entry.revision.plan_version != version
                or entry.candidate.plan_version != version
                or entry.context_pack_id != entry.revision.context_pack_id
            ):
                raise NarrativeDecisionAuthorizationError("MANIFEST_BINDING_MISMATCH")
        try:
            async with sessions() as session, session.begin():
                proof = await authority.require_locked(session, subject=subject)
        except PermissionError:
            raise NarrativeDecisionAuthorizationError("AUTOMATION_AUTHORITY_NOT_CURRENT") from None
        return cls(
            sessions=sessions,
            authority=authority,
            subject=subject,
            manifest=manifest,
            proof=proof,
            binding=_BINDING_SEAL,
        )

    @property
    def actor_id(self) -> str:
        return self._proof.principal

    @property
    def parent_event_digest(self) -> str:
        return self._proof.parent_event_digest

    @property
    def admitted_at(self) -> datetime:
        return self._proof.admitted_at

    async def _require_root(self, session: AsyncSession) -> None:
        try:
            current = await self._authority.require_locked(session, subject=self._subject)
            if current != self._proof:
                raise NarrativeDecisionAuthorizationError("AUTOMATION_AUTHORITY_PROJECTION_MISMATCH")
        except PermissionError:
            raise NarrativeDecisionAuthorizationError("AUTOMATION_AUTHORITY_NOT_CURRENT") from None

    async def commit_canon(self) -> CanonCommitResult:
        return await commit_manifest_canon(
            StoryIdentity(self._subject.user_id, self._subject.project_name, self._manifest.run_id),
            self._manifest,
            actor_id=self._proof.principal,
            approved_at=self._proof.admitted_at,
            approval_ref=self._reference + ":canon",
            canon=CanonTransactionService(
                guarded_canon_authority_uow_factory(self._sessions, guard=self._guard_canon),
                version_id_factory=lambda: self._manifest.canon_version_id,
            ),
            clock=lambda: datetime.now(UTC),
        )

    async def commit_plan(self) -> NarrativePlanCommitResult:
        return await commit_manifest_plan(
            StoryIdentity(self._subject.user_id, self._subject.project_name, self._manifest.run_id),
            self._manifest,
            actor_id=self._proof.principal,
            approved_at=self._proof.admitted_at,
            approval_ref=self._reference + ":plan",
            uow_factory=lambda: _PlanCommitFence(self),
            canon_reader=committed_canon_reader(self._sessions),
            clock=lambda: datetime.now(UTC),
        )

    async def accept_scene(self, decision_id: str, *, bible: StoryBibleInput) -> NarrativeDecisionReceipt:
        index = next((i for i, entry in enumerate(self._manifest.scenes) if entry.decision_id == decision_id), None)
        if index is None:
            raise NarrativeDecisionAuthorizationError("MANIFEST_MEMBER_MISMATCH")
        identity = StoryIdentity(self._subject.user_id, self._subject.project_name, self._manifest.run_id)
        entry = await compile_manifest_scene(
            committed_readers(identity, bible, session_factory=self._sessions),
            identity,
            self._manifest,
            self._manifest.scenes[index].node_id,
        )
        evidence = NarrativeLifecycleEvidenceService(lambda: _EvidenceCommitFence(self, index))
        await evidence.record_draft_candidate(entry.candidate)
        await evidence.record_revision(entry.revision)
        return await NarrativeAcceptanceService(self.unit_of_work_factory(), self).decide_revision(
            acceptance_command(entry.revision, decision_id=decision_id, actor_id=self._proof.principal),
            authenticated_principal=self._proof.principal,
        )

    def _require_prefix(self, uow: _BoundNarrativeUnitOfWork, index: int) -> None:
        for earlier in self._manifest.scenes[:index]:
            if uow.locked_heads[earlier.decision_id].effective_decision_id != earlier.decision_id:
                raise NarrativeDecisionAuthorizationError("NARRATIVE_PREFIX_MOVED")

    def unit_of_work_factory(self) -> NarrativeLifecycleUnitOfWorkFactory:
        def factory() -> _BoundNarrativeUnitOfWork:
            return _BoundNarrativeUnitOfWork(self)

        return factory

    def _require_actor(self, principal: str) -> None:
        if principal != self._proof.principal:
            raise NarrativeDecisionAuthorizationError("AUTOMATIC_ACTOR_MISMATCH")
        if self._manifest.digest() != self._subject.subject_digest:
            raise NarrativeDecisionAuthorizationError("MANIFEST_BINDING_MISMATCH")

    def _member(self, command: R2ContractModel) -> int:
        if not isinstance(command, RevisionAcceptanceCommand):
            raise NarrativeDecisionAuthorizationError("AUTOMATIC_OWNER_COMMAND_NOT_DELEGATED")
        for index, entry in enumerate(self._manifest.scenes):
            expected = acceptance_command(entry.revision, decision_id=entry.decision_id, actor_id=self._proof.principal)
            if command.model_dump(exclude={"retry_authentication"}) == expected.model_dump(
                exclude={"retry_authentication"}
            ):
                return index
        raise NarrativeDecisionAuthorizationError("MANIFEST_MEMBER_MISMATCH")

    async def authorize_initial_decision(
        self, authenticated_principal: str, canonical_command: NarrativeDecisionCommand
    ) -> NarrativeAutomationDecisionAuthorizationV1:
        self._require_actor(authenticated_principal)
        self._member(canonical_command)
        scope_fingerprint, command_fingerprint = automatic_authorization_fingerprints(canonical_command)
        return NarrativeAutomationDecisionAuthorizationV1(
            authorization_ref=_ref("anda:v1:", [self._reference, canonical_command.decision_id, command_fingerprint]),
            user_id=self._subject.user_id,
            project_name=self._subject.project_name,
            actor_id=self._proof.principal,
            authority_role="RUN_AUTOMATION",
            decision_family=canonical_command.decision_family,
            action=canonical_command.action,
            decision_id=canonical_command.decision_id,
            stable_subject_fingerprint=scope_fingerprint,
            decision_command_fingerprint=command_fingerprint,
            authenticated_at=self._proof.admitted_at,
            authenticated_via=self._reference,
        )

    async def authenticate_exact_retry(
        self, authenticated_principal: str, decision_id: str, exact_scope: NarrativeWorkScope
    ) -> NarrativeAutomationRetryAuthenticationV1:
        self._require_actor(authenticated_principal)
        if not any(
            entry.decision_id == decision_id and entry.revision.work_scope == exact_scope
            for entry in self._manifest.scenes
        ):
            raise NarrativeDecisionAuthorizationError("MANIFEST_MEMBER_MISMATCH")
        return NarrativeAutomationRetryAuthenticationV1(
            retry_authentication_ref=_ref("anra:v1:", [self._reference, decision_id]),
            user_id=self._subject.user_id,
            project_name=self._subject.project_name,
            actor_id=self._proof.principal,
            authority_role="RUN_AUTOMATION",
            decision_id=decision_id,
            authenticated_at=self._proof.admitted_at,
            authenticated_via=self._reference,
        )

    async def authenticate_scoped_showrunner(
        self, authenticated_principal: str, subject_id: str, exact_scope: NarrativeWorkScope
    ) -> NarrativeAutomationRetryAuthenticationV1:
        raise NarrativeDecisionAuthorizationError("AUTOMATIC_CANON_HANDOFF_NOT_DELEGATED")

    async def _guard_canon(self, session: AsyncSession) -> None:
        await self._lock_canon(session, allow_empty=True)
        await self._require_root(session)

    async def _lock_canon(self, session: AsyncSession, *, allow_empty: bool = False) -> None:
        try:
            await require_canon_commit_basis(
                session,
                user_id=self._subject.user_id,
                project_name=self._subject.project_name,
                delta=self._manifest.canon_genesis,
                version_id=self._manifest.canon_version_id,
                allow_empty=allow_empty,
            )
        except CanonError:
            raise NarrativeDecisionAuthorizationError("CANON_BASIS_UNAVAILABLE") from None
        except CanonCommitBasisError:
            raise NarrativeDecisionAuthorizationError("CANON_BASIS_MOVED") from None

    async def _lock_sources(self, uow: _BoundNarrativeUnitOfWork) -> None:
        scope = {"user_id": self._subject.user_id, "project_name": self._subject.project_name}
        plans = NarrativePlanRepository(uow.session)
        await self._lock_canon(uow.session)
        head = await plans.lock_plan(plan_id=self._manifest.plan.plan_id, **scope)
        plan = await plans.get_version_by_revision(plan_revision_id=self._manifest.plan.plan_revision_id, **scope)
        version = (self._manifest.plan.expected_version or 0) + 1
        if (
            head is None
            or plan is None
            or head.head_version != version
            or (plan.user_id, plan.project_name, plan.plan_id)
            != (self._subject.user_id, self._subject.project_name, self._manifest.plan.plan_id)
            or plan.version != version
            or plan.parent_version != self._manifest.plan.expected_version
            or plan.content_hash != self._manifest.plan.content_hash
            or plan.content != self._manifest.plan.proposed_content
        ):
            raise NarrativeDecisionAuthorizationError("PLAN_BASIS_MOVED")
        entries = sorted(
            self._manifest.scenes,
            key=lambda entry: head_lock_sort_key(
                "REVISION_ACCEPTANCE",
                user_id=entry.revision.work_scope.user_id,
                project_name=entry.revision.work_scope.project_name,
                logical_key=(
                    entry.revision.work_scope.plan_id,
                    entry.revision.work_scope.scene_contract_id,
                    entry.revision.work_scope.canon_branch_id,
                ),
            ),
        )
        for entry in entries:
            uow.locked_heads[entry.decision_id] = await uow.repository.lock_or_insert_revision_head(
                entry.revision.work_scope
            )

    async def require_current_in_owner(self, unit_of_work: object, command: R2ContractModel) -> None:
        if (
            type(unit_of_work) is not _BoundNarrativeUnitOfWork
            or unit_of_work.owner is not self
            or not unit_of_work.sources_locked
        ):
            raise NarrativeDecisionAuthorizationError("OWNING_TRANSACTION_REQUIRED")
        self._require_actor(self._proof.principal)
        index = self._member(command)
        self._require_prefix(unit_of_work, index)
        entry = self._manifest.scenes[index]
        scope = {"user_id": self._subject.user_id, "project_name": self._subject.project_name}
        revision = await unit_of_work.repository.get_exact_revision(revision_id=entry.revision.revision_id, **scope)
        candidate = await unit_of_work.repository.get_exact_draft_candidate(
            candidate_id=entry.candidate.candidate_id, **scope
        )
        if revision != entry.revision or candidate != entry.candidate:
            raise NarrativeDecisionAuthorizationError("NARRATIVE_EVIDENCE_MOVED")
        await self._require_root(unit_of_work.session)

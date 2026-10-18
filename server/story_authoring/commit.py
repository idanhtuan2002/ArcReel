"""The touchpoint-2 commit protocol: one Human Approve turns an offered manifest into R2 records.

A :class:`ManuscriptCommitManifest` fixes, before the Human looks at it, every record the approval will write:
the bible-derived Canon genesis delta and its version id, the plan revision, and per scene the draft
candidate, revision, revision-acceptance decision id and the context binding it was generated with. Its
digest covers exactly that payload; the approval binds the digest.

Approve persists an :class:`~server.story_authoring.runtime.ApprovalRecord` first (phase ``APPROVING``), then
runs the steps in order through the existing owners only — ``CanonTransactionService``,
``NarrativePlanService``, ``NarrativeLifecycleEvidenceService`` and ``NarrativeAcceptanceService`` with the
grant-backed authority. Each step is idempotent through those owners' exact-retry paths, so resuming after a
crash re-sends a completed step and gets its original receipt back. Before each scene the context is
recompiled from the committed rows and must equal the manifest's binding; any difference or owner refusal
stops the sequence in ``COMMIT_BLOCKED`` with the exact step and reason, and nothing after it is sent.
``COMMITTED`` follows only a read-back of every record. R2 records are append-only: a blocked run either
continues under a successor manifest whose committed prefix is unchanged, or is aborted by the Human.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.canon_uow import canon_authority_uow_factory
from lib.db.narrative_lifecycle_uow import narrative_lifecycle_uow_factory
from lib.db.narrative_plan_uow import narrative_plan_uow_factory
from r2.contracts import (
    CanonCommitApproval,
    CanonDelta,
    CreateCanonBranch,
    NarrativeContextPack,
    NarrativePlanApproval,
    NarrativePlanRevisionProposal,
)
from r2.contracts.common import ensure_json_value
from r2.contracts.fingerprints import canonical_json_bytes
from r2.contracts.narrative import CanonBranchType
from r2.contracts.narrative_lifecycle import DraftCandidate, NarrativeRevision
from r2.narrative.canon_transaction import CanonTransactionService
from r2.narrative.errors import CanonError, NarrativeError
from r2.narrative_context.errors import NarrativeContextError
from r2.narrative_lifecycle.acceptance import NarrativeAcceptanceService
from r2.narrative_lifecycle.accepted_narrative_adapter import AcceptedNarrativeAdapter
from r2.narrative_lifecycle.evidence import NarrativeLifecycleEvidenceService
from r2.narrative_plan.errors import NarrativePlanError
from r2.narrative_plan.service import NarrativePlanService
from server.story_authoring.artifacts import BlobStoreError, StoryBlobStore
from server.story_authoring.authority import GrantNarrativeShowrunnerAuthority
from server.story_authoring.narrative import (
    ProvisionalAcceptance,
    SceneBases,
    SceneRef,
    StoryBibleInput,
    StoryIdentity,
    acceptance_command,
    binding,
    build_candidate,
    build_revision,
    committed_readers,
    compile_scene_context,
    provisional_canon_view,
    revision_decision_id,
    scene_contract,
)
from server.story_authoring.runtime import (
    ApprovalRecord,
    CommitProgress,
    RunPhase,
    RunState,
    RunStateStore,
    set_phase,
)

MANIFEST_SCHEMA = "story-commit-manifest-v1"
STEP_CANON = "canon"
STEP_PLAN = "plan"
APPROVABLE_PHASES = frozenset({RunPhase.READY_FOR_APPROVAL})
EXECUTING_PHASES = frozenset({RunPhase.APPROVING, RunPhase.PARTIALLY_COMMITTED})
ABORTABLE_PHASES = frozenset({RunPhase.PARTIALLY_COMMITTED, RunPhase.COMMIT_BLOCKED})
OFFERABLE_PHASES = frozenset({RunPhase.RUNNING, RunPhase.COMMIT_BLOCKED})


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SceneEntry(_Frozen):
    node_id: str
    chapter: int
    scene: int
    global_index: int
    candidate: DraftCandidate
    revision: NarrativeRevision
    decision_id: str
    context_pack_id: str
    context_content_hash: str

    @property
    def ref(self) -> SceneRef:
        return SceneRef(chapter=self.chapter, scene=self.scene, global_index=self.global_index)


class ManuscriptCommitManifest(_Frozen):
    schema_id: str = MANIFEST_SCHEMA
    run_id: str
    brief_digest: str
    gate_a_decision_id: str
    predecessor_manifest_digest: str | None = None
    committed_prefix: tuple[str, ...] = ()
    canon_genesis: CanonDelta
    canon_version_id: str
    plan: NarrativePlanRevisionProposal
    scenes: tuple[SceneEntry, ...]
    findings_open: tuple[str, ...] = ()
    exceptions_offered: tuple[str, ...] = ()
    export_digest: str

    def digest(self) -> str:
        return manifest_digest(self)

    def steps(self) -> tuple[str, ...]:
        return (STEP_CANON, STEP_PLAN, *(scene.node_id for scene in self.scenes))


def scene_entry(
    identity: StoryIdentity,
    scene: SceneRef,
    *,
    pack: NarrativeContextPack,
    canon_version_id: str,
    scene_contract_version: int,
    prose: str,
    model: str,
    writer_version: str,
    created_by: str,
    created_at: datetime,
) -> SceneEntry:
    """The manifest entry of one generated scene: its evidence, decision id and the context it was written from."""
    bases = SceneBases(canon_version_id, 1, scene_contract_version, pack.context_pack_id)
    candidate = build_candidate(
        identity,
        scene,
        bases,
        prose,
        model=model,
        writer_version=writer_version,
        created_by=created_by,
        created_at=created_at,
    )
    revision = build_revision(candidate, created_by=created_by, created_at=created_at)
    return SceneEntry(
        node_id=scene.node_id,
        chapter=scene.chapter,
        scene=scene.scene,
        global_index=scene.global_index,
        candidate=candidate,
        revision=revision,
        decision_id=revision_decision_id(identity, scene, revision),
        context_pack_id=pack.context_pack_id,
        context_content_hash=pack.content_hash,
    )


def provisional_acceptances(entries: Sequence[SceneEntry]) -> list[ProvisionalAcceptance]:
    return [ProvisionalAcceptance(revision=entry.revision, decision_id=entry.decision_id) for entry in entries]


def manifest_bytes(manifest: ManuscriptCommitManifest) -> bytes:
    """Canonical JSON of the whole manifest: its digest is the manifest digest and its blob id."""
    return canonical_json_bytes(ensure_json_value(manifest.model_dump(mode="json")))


def manifest_digest(manifest: ManuscriptCommitManifest) -> str:
    return "sha256:" + hashlib.sha256(manifest_bytes(manifest)).hexdigest()


def step_key(digest: str, index: int) -> str:
    """Host bookkeeping key of one step under one manifest; never part of the manifest payload."""
    return "sha256:" + hashlib.sha256(f"story-commit-v1|{digest}|{index}".encode()).hexdigest()


class CommitRefusal(StrEnum):
    STALE_MANIFEST = "STALE_MANIFEST"
    NOT_READY = "NOT_READY"
    EXCEPTIONS_NOT_ACCEPTED = "EXCEPTIONS_NOT_ACCEPTED"
    ALREADY_APPROVING = "ALREADY_APPROVING"
    NOT_RESUMABLE = "NOT_RESUMABLE"
    NOT_THE_APPROVER = "NOT_THE_APPROVER"
    SUCCESSOR_REFUSED = "SUCCESSOR_REFUSED"
    NOT_ABORTABLE = "NOT_ABORTABLE"
    NOT_OFFERABLE = "NOT_OFFERABLE"


class CommitRefused(Exception):
    def __init__(self, code: CommitRefusal, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code.value}: {detail}")


class BindingMismatch(Exception):
    pass


_BLOCKING_ERRORS = (
    CanonError,
    NarrativeError,
    NarrativePlanError,
    NarrativeContextError,
    BindingMismatch,
    BlobStoreError,
)


def _approval_ref(digest: str, step: str) -> str:
    return f"story-approval:{digest}:{step}"


class ManuscriptCommitter:
    def __init__(
        self,
        *,
        identity: StoryIdentity,
        bible: StoryBibleInput,
        store: RunStateStore,
        blobs: StoryBlobStore,
        session_factory: async_sessionmaker[AsyncSession],
        authority: GrantNarrativeShowrunnerAuthority,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._identity = identity
        self._bible = bible
        self._store = store
        self._blobs = blobs
        self._session_factory = session_factory
        self._authority = authority
        self._clock = clock
        lifecycle = narrative_lifecycle_uow_factory(session_factory)
        self._evidence = NarrativeLifecycleEvidenceService(lifecycle)
        self._acceptance = NarrativeAcceptanceService(lifecycle, authority)
        self._accepted = AcceptedNarrativeAdapter(lifecycle)

    # --- offering ----------------------------------------------------------------------------------

    async def offer(self, manifest: ManuscriptCommitManifest) -> str:
        """Store the manifest and offer it at touchpoint 2. A successor must keep its committed prefix."""
        digest = self._blobs.put(manifest_bytes(manifest))

        def change(state: RunState) -> tuple[RunState, CommitRefused | None]:
            if state.phase not in OFFERABLE_PHASES:
                return state, CommitRefused(CommitRefusal.NOT_OFFERABLE, f"run is {state.phase.value}")
            completed = state.commit.completed_steps if state.commit is not None else ()
            if state.phase is RunPhase.COMMIT_BLOCKED:
                previous = self._load_offered(state)
                refusal = _successor_refusal(previous, manifest, completed)
                if refusal is not None:
                    return state, CommitRefused(CommitRefusal.SUCCESSOR_REFUSED, refusal)
            elif manifest.predecessor_manifest_digest is not None or manifest.committed_prefix:
                return state, CommitRefused(CommitRefusal.SUCCESSOR_REFUSED, "a first manifest has no predecessor")
            progress = CommitProgress(offered_manifest_digest=digest, completed_steps=completed)
            return set_phase(state, RunPhase.READY_FOR_APPROVAL).model_copy(update={"commit": progress}), None

        _, refused = await self._store.apply(change)
        if refused is not None:
            raise refused
        return digest

    # --- approval and execution --------------------------------------------------------------------

    async def approve(
        self, *, principal: str, manifest_digest_seen: str, accepted_exceptions: Sequence[str]
    ) -> RunState:
        state = await self._store.load()
        if state.phase not in APPROVABLE_PHASES or state.commit is None:
            raise CommitRefused(CommitRefusal.NOT_READY, f"run is {state.phase.value}")
        if state.commit.offered_manifest_digest != manifest_digest_seen:
            raise CommitRefused(CommitRefusal.STALE_MANIFEST, "the offered manifest changed")
        manifest = self._load_offered(state)
        missing = sorted(set(manifest.exceptions_offered) - set(accepted_exceptions))
        if missing:
            raise CommitRefused(CommitRefusal.EXCEPTIONS_NOT_ACCEPTED, ", ".join(missing))
        proof = await self._authority.require_showrunner(
            principal, user_id=self._identity.user_id, project_name=self._identity.project_name
        )
        record = ApprovalRecord(
            manifest_digest=manifest_digest_seen,
            actor_id=proof.actor_id,
            grant_event_digest=proof.grant_event_digest,
            approved_at=proof.authenticated_at,
            accepted_exceptions=tuple(sorted(accepted_exceptions)),
        )

        def change(state: RunState) -> tuple[RunState, bool]:
            commit = state.commit
            if (
                state.phase not in APPROVABLE_PHASES
                or commit is None
                or commit.offered_manifest_digest != manifest_digest_seen
            ):
                return state, False
            approved = commit.model_copy(update={"approval": record, "blocked_step": None})
            return set_phase(state, RunPhase.APPROVING).model_copy(update={"commit": approved}), True

        _, won = await self._store.apply(change)
        if not won:
            raise CommitRefused(CommitRefusal.ALREADY_APPROVING, "another approval of this run is in progress")
        return await self._execute(manifest, record)

    async def resume(self, *, principal: str) -> RunState:
        """Continue an interrupted sequence under the recorded approval; only its approver may resume."""
        state = await self._store.load()
        commit = state.commit
        if state.phase not in EXECUTING_PHASES or commit is None or commit.approval is None:
            raise CommitRefused(CommitRefusal.NOT_RESUMABLE, f"run is {state.phase.value}")
        if commit.approval.actor_id != principal:
            raise CommitRefused(CommitRefusal.NOT_THE_APPROVER, "only the approving Showrunner may resume")
        await self._authority.require_showrunner(
            principal, user_id=self._identity.user_id, project_name=self._identity.project_name
        )
        return await self._execute(self._load_offered(state), commit.approval)

    async def abort(self, *, principal: str) -> RunState:
        await self._authority.require_showrunner(
            principal, user_id=self._identity.user_id, project_name=self._identity.project_name
        )

        def change(state: RunState) -> tuple[RunState, bool]:
            if state.phase not in ABORTABLE_PHASES:
                return state, False
            return set_phase(state, RunPhase.ABORTED_PARTIAL, reason=f"aborted by {principal}"), True

        state, done = await self._store.apply(change)
        if not done:
            raise CommitRefused(CommitRefusal.NOT_ABORTABLE, f"run is {state.phase.value}")
        return state

    async def _execute(self, manifest: ManuscriptCommitManifest, approval: ApprovalRecord) -> RunState:
        digest = approval.manifest_digest
        state = await self._store.load()
        completed = set(state.commit.completed_steps if state.commit is not None else ())
        for step in manifest.steps():
            if step in completed:
                continue
            try:
                await self._run_step(step, manifest, approval, digest)
            except _BLOCKING_ERRORS as exc:
                return await self._block(step, f"{type(exc).__name__}: {exc}")
            state = await self._complete(step)
            if state.phase is not RunPhase.PARTIALLY_COMMITTED:
                return state
        problems = await self._read_back(manifest)
        if problems:
            return await self._block("read-back", "; ".join(problems))
        state, _ = await self._store.apply(
            lambda s: (set_phase(s, RunPhase.COMMITTED), None) if s.phase in EXECUTING_PHASES else (s, None)
        )
        return state

    async def _run_step(
        self, step: str, manifest: ManuscriptCommitManifest, approval: ApprovalRecord, digest: str
    ) -> None:
        identity = self._identity
        if step == STEP_CANON:
            delta = manifest.canon_genesis
            canon = CanonTransactionService(
                canon_authority_uow_factory(self._session_factory), version_id_factory=lambda: manifest.canon_version_id
            )
            await canon.create_branch(
                CreateCanonBranch(
                    branch_id=identity.canon_branch_id,
                    user_id=identity.user_id,
                    project_name=identity.project_name,
                    branch_type=CanonBranchType.MAIN,
                    created_at=delta.created_at,
                    created_by=delta.created_by,
                )
            )
            result = await canon.commit(
                delta=delta,
                approval=CanonCommitApproval(
                    approval_ref=_approval_ref(digest, STEP_CANON),
                    canon_delta_id=delta.canon_delta_id,
                    payload_hash=delta.payload_hash,
                    payload_hash_algorithm=delta.payload_hash_algorithm,
                    payload_hash_version=delta.payload_hash_version,
                    content_schema_version=delta.content_schema_version,
                    project_name=identity.project_name,
                    user_id=identity.user_id,
                    approved_by=approval.actor_id,
                    approved_at=approval.approved_at,
                    status="APPROVED",
                ),
                project_name=identity.project_name,
                user_id=identity.user_id,
                now=self._clock(),
            )
            if result.version.canon_version_id != manifest.canon_version_id:
                raise BindingMismatch(
                    f"Canon genesis committed as {result.version.canon_version_id}, manifest names {manifest.canon_version_id}"
                )
            return
        readers = committed_readers(identity, self._bible, session_factory=self._session_factory)
        if step == STEP_PLAN:
            plan = manifest.plan
            service = NarrativePlanService(narrative_plan_uow_factory(self._session_factory), readers.canon_reader)
            await service.commit_revision(
                proposal=plan,
                approval=NarrativePlanApproval(
                    approval_ref=_approval_ref(digest, STEP_PLAN),
                    plan_revision_id=plan.plan_revision_id,
                    plan_id=plan.plan_id,
                    expected_version=plan.expected_version,
                    content_hash=plan.content_hash,
                    project_name=identity.project_name,
                    user_id=identity.user_id,
                    approved_by=approval.actor_id,
                    approved_at=approval.approved_at,
                ),
                project_name=identity.project_name,
                user_id=identity.user_id,
                now=self._clock(),
            )
            return
        index = next(i for i, scene in enumerate(manifest.scenes) if scene.node_id == step)
        entry = manifest.scenes[index]
        pack = await compile_scene_context(
            readers,
            identity,
            entry.ref,
            contract=scene_contract(manifest.plan, entry.ref),
            canon_version_id=manifest.canon_version_id,
            plan_version=1,
            recent_decision_ids=[earlier.decision_id for earlier in manifest.scenes[:index]],
        )
        if binding(pack) != (entry.context_pack_id, entry.context_content_hash):
            raise BindingMismatch(
                f"{step}: committed context {binding(pack)} differs from the generated "
                f"{(entry.context_pack_id, entry.context_content_hash)}"
            )
        await self._evidence.record_draft_candidate(entry.candidate)
        await self._evidence.record_revision(entry.revision)
        await self._acceptance.decide_revision(
            acceptance_command(entry.revision, decision_id=entry.decision_id, actor_id=approval.actor_id),
            authenticated_principal=approval.actor_id,
        )

    async def _complete(self, step: str) -> RunState:
        def change(state: RunState) -> tuple[RunState, None]:
            if state.phase not in EXECUTING_PHASES or state.commit is None:
                return state, None
            progress = state.commit.model_copy(update={"completed_steps": (*state.commit.completed_steps, step)})
            return set_phase(state, RunPhase.PARTIALLY_COMMITTED).model_copy(update={"commit": progress}), None

        state, _ = await self._store.apply(change)
        return state

    async def _block(self, step: str, reason: str) -> RunState:
        def change(state: RunState) -> tuple[RunState, None]:
            if state.phase not in EXECUTING_PHASES or state.commit is None:
                return state, None
            blocked = state.commit.model_copy(update={"blocked_step": step})
            return set_phase(state, RunPhase.COMMIT_BLOCKED, reason=reason).model_copy(update={"commit": blocked}), None

        state, _ = await self._store.apply(change)
        return state

    async def _read_back(self, manifest: ManuscriptCommitManifest) -> list[str]:
        identity = self._identity
        problems: list[str] = []
        readers = committed_readers(identity, self._bible, session_factory=self._session_factory)
        view = await readers.canon_reader.get_exact(
            branch_id=identity.canon_branch_id,
            canon_version_id=manifest.canon_version_id,
            project_name=identity.project_name,
            user_id=identity.user_id,
        )
        if view is None or view.content_hash != provisional_canon_view(manifest.canon_genesis).content_hash:
            problems.append("Canon genesis does not read back as approved")
        plan = await readers.plan_reader.get_exact_plan(
            plan_id=identity.plan_id, plan_version=1, project_name=identity.project_name, user_id=identity.user_id
        )
        if plan is None or plan.content_hash != manifest.plan.content_hash:
            problems.append("plan does not read back as approved")
        for entry in manifest.scenes:
            record = await self._accepted.get_exact(
                accepted_narrative_ref=entry.decision_id, project_name=identity.project_name, user_id=identity.user_id
            )
            if record is None or record.content != entry.revision.normalized_content:
                problems.append(f"{entry.node_id} is not the current accepted revision")
        return problems

    def _load_offered(self, state: RunState) -> ManuscriptCommitManifest:
        assert state.commit is not None
        return ManuscriptCommitManifest.model_validate_json(
            self._blobs.read_exact(state.commit.offered_manifest_digest)
        )


def _successor_refusal(
    previous: ManuscriptCommitManifest, successor: ManuscriptCommitManifest, completed: Sequence[str]
) -> str | None:
    """A successor may change only what is not committed yet, and must name its predecessor and prefix."""
    if successor.predecessor_manifest_digest != previous.digest():
        return "the successor does not name the blocked manifest as its predecessor"
    if tuple(successor.committed_prefix) != tuple(completed):
        return "the successor's committed prefix differs from the committed steps"
    if successor.run_id != previous.run_id:
        return "the successor belongs to another run"
    for step in completed:
        if step == STEP_CANON and (
            successor.canon_genesis != previous.canon_genesis or successor.canon_version_id != previous.canon_version_id
        ):
            return "the committed Canon genesis would change"
        if step == STEP_PLAN and successor.plan != previous.plan:
            return "the committed plan would change"
        if step not in (STEP_CANON, STEP_PLAN):
            before = next((s for s in previous.scenes if s.node_id == step), None)
            after = next((s for s in successor.scenes if s.node_id == step), None)
            if before is None or after is None or before != after:
                return f"committed scene {step} would change"
    return None

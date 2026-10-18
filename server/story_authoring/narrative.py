"""Mapping of one story run onto the existing R2 Canon, NarrativePlan, context and lifecycle owners.

Everything the touchpoint-2 approval will record is built here *before* the approval, deterministically from
the story inputs: the bible-derived Canon genesis delta and its version id, the plan revision, and per scene
the draft candidate, revision and revision-acceptance decision id. The same builders run again when the
approval executes, so the recorded rows equal the ones the Human saw.

Contexts are compiled by the real ``NarrativeContextCompiler`` over two reader sets with one shape:
:func:`provisional_readers` serves the not-yet-committed genesis, plan and accepted scenes from memory (the
accepted-narrative records go through the real ``AcceptedNarrativeAdapter`` over an in-memory store), and
:func:`committed_readers` serves the committed rows. Equal ``context_pack_id`` and ``content_hash`` from both
is the binding proof.

Canon stays at the genesis version for the whole run: story scenes are accepted narrative, and their events
are not extracted into Canon (Task3 decision, option A).
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import TracebackType
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.canon_uow import canon_projection_uow_factory
from lib.db.narrative_lifecycle_uow import narrative_lifecycle_uow_factory
from lib.db.narrative_plan_uow import narrative_plan_uow_factory
from r2.contracts import (
    CanonDelta,
    NarrativeContextPack,
    NarrativeContextRequest,
    NarrativePlan,
    NarrativePlanRevisionProposal,
    SceneContractValue,
)
from r2.contracts.common import ensure_json_value
from r2.contracts.enums import ProvenanceActor
from r2.contracts.fingerprints import canonical_json_bytes
from r2.contracts.narrative import (
    AddEntityOperation,
    AddFactOperation,
    CanonDeltaPayload,
    CanonOperation,
    Entity,
    EntityType,
    Fact,
)
from r2.contracts.narrative_context import ContextMode, RetrievalSnapshot
from r2.contracts.narrative_lifecycle import (
    DraftCandidate,
    NarrativeDecisionAuthorization,
    NarrativeRevision,
    NarrativeWorkScope,
    RevisionAcceptanceCommand,
    RevisionAcceptanceHead,
)
from r2.contracts.narrative_plan import (
    CanonBasis,
    NarrativePlanContent,
    NarrativePlanNode,
    SceneContract,
    SceneTemporalWindow,
)
from r2.contracts.provenance import Provenance
from r2.narrative.canon_resolution import CanonResolutionService
from r2.narrative.canon_state import ResolvedCanonView, apply_canon_delta, empty_canon_content
from r2.narrative.errors import CanonNotFoundError
from r2.narrative.hashing import compute_canon_content_hash, compute_canon_delta_hash
from r2.narrative_context.compiler import NarrativeContextCompiler
from r2.narrative_lifecycle.accepted_narrative_adapter import AcceptedNarrativeAdapter
from r2.narrative_lifecycle.hashing import (
    compute_evidence_semantic_fingerprint,
    compute_prose_content_hash,
    normalize_prose,
)
from r2.narrative_lifecycle.ports import NarrativeLifecycleUnitOfWorkFactory
from r2.narrative_plan.errors import NarrativePlanNotFoundError
from r2.narrative_plan.hashing import compute_plan_content_hash_dispatch, compute_scene_semantic_hash
from r2.narrative_plan.service import NarrativePlanService

CANON_SCHEMA_VERSION = "r2-canon-schema-v2"
CONTEXT_COMPILER_VERSION = "compiler-v1"
CONTEXT_TOKEN_BUDGET = 6000
STORY_TIME_ORIGIN = datetime(2000, 1, 1, tzinfo=UTC)
WRITER_KIND = "story-authoring"
DECISION_ID_VERSION = "story-decision-v1"
_KEY = re.compile(r"^[a-z0-9][a-z0-9-]{0,47}$")


def _sha(prefix: str, value: Any) -> str:
    return prefix + hashlib.sha256(canonical_json_bytes(ensure_json_value(value))).hexdigest()


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# --- story inputs (produced upstream by the planning stages) ---------------------------------------


class StoryEntityInput(_Frozen):
    key: str = Field(pattern=_KEY.pattern)
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)


class StoryBibleInput(_Frozen):
    title: str = Field(min_length=1)
    premise: str = Field(min_length=1)
    characters: tuple[StoryEntityInput, ...] = Field(min_length=1)
    locations: tuple[StoryEntityInput, ...] = ()
    style_rules: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _keys_unique(self) -> StoryBibleInput:
        keys = [e.key for e in self.characters] + [e.key for e in self.locations]
        if len(keys) != len(set(keys)):
            raise ValueError("character and location keys must be unique")
        return self


class SceneOutlineInput(_Frozen):
    purpose: str = Field(min_length=1)
    pov: str | None
    location: str | None
    participants: tuple[str, ...] = ()
    beats: tuple[str, ...] = Field(min_length=1)


class ChapterOutlineInput(_Frozen):
    intent: str = Field(min_length=1)
    scenes: tuple[SceneOutlineInput, ...] = Field(min_length=1)


class StoryOutlineInput(_Frozen):
    story_frame: str = Field(min_length=1)
    chapters: tuple[ChapterOutlineInput, ...] = Field(min_length=1)


@dataclass(frozen=True)
class SceneRef:
    chapter: int
    scene: int
    global_index: int

    @property
    def node_id(self) -> str:
        return f"scene_draft[{self.chapter},{self.scene}]"

    @property
    def scene_contract_id(self) -> str:
        return f"scene-c{self.chapter}-s{self.scene}"


def scene_refs(outline: StoryOutlineInput) -> tuple[SceneRef, ...]:
    refs: list[SceneRef] = []
    for c, chapter in enumerate(outline.chapters, start=1):
        for s, _ in enumerate(chapter.scenes, start=1):
            refs.append(SceneRef(chapter=c, scene=s, global_index=len(refs)))
    return tuple(refs)


@dataclass(frozen=True)
class StoryIdentity:
    """Stable R2 identities of one run inside one project; nothing here is minted by the model."""

    user_id: str
    project_name: str
    run_id: str

    @property
    def canon_branch_id(self) -> str:
        return f"story-{self.run_id}-canon"

    @property
    def plan_id(self) -> str:
        return f"story-{self.run_id}-plan"

    @property
    def policy_ref(self) -> str:
        return f"story-{self.run_id}-style"

    def work_scope(self, scene: SceneRef) -> NarrativeWorkScope:
        return NarrativeWorkScope(
            user_id=self.user_id,
            project_name=self.project_name,
            plan_id=self.plan_id,
            scene_contract_id=scene.scene_contract_id,
            canon_branch_id=self.canon_branch_id,
        )


def character_id(key: str) -> str:
    return f"char-{key}"


def location_id(key: str) -> str:
    return f"loc-{key}"


# --- Canon genesis ---------------------------------------------------------------------------------


def build_genesis_delta(
    identity: StoryIdentity, bible: StoryBibleInput, *, created_by: str, created_at: datetime
) -> CanonDelta:
    """Characters and locations as entities, each with its bible description as a fact."""
    operations: list[CanonOperation] = []
    for entity_type, entities, make_id in (
        (EntityType.CHARACTER, bible.characters, character_id),
        (EntityType.LOCATION, bible.locations, location_id),
    ):
        for entity in entities:
            target = make_id(entity.key)
            operations.append(
                AddEntityOperation(
                    operation_id=f"op-entity-{target}",
                    target_id=target,
                    entity=Entity(entity_id=target, entity_type=entity_type, canonical_name=entity.name),
                )
            )
            fact_id = f"fact-{target}-description"
            operations.append(
                AddFactOperation(
                    operation_id=f"op-{fact_id}",
                    target_id=fact_id,
                    fact=Fact(fact_id=fact_id, subject_ref=target, predicate="description", value=entity.description),
                )
            )
    payload = CanonDeltaPayload(
        canon_delta_id=f"{identity.canon_branch_id}-genesis",
        target_branch_id=identity.canon_branch_id,
        base_canon_version_id=None,
        operations=operations,
        source_change_set_refs=[],
        author_decision_refs=[],
        validation_report_refs=[],
        content_schema_version=CANON_SCHEMA_VERSION,
        created_at=created_at,
        created_by=created_by,
    )
    return CanonDelta(**payload.model_dump(), payload_hash=compute_canon_delta_hash(payload))


def genesis_canon_version_id(delta: CanonDelta) -> str:
    """The version id the genesis commit is given, so the pre-approval contexts name the real version."""
    return "canon-version-" + hashlib.sha256(f"{delta.canon_delta_id}|{delta.payload_hash}".encode()).hexdigest()[:32]


def provisional_canon_view(delta: CanonDelta) -> ResolvedCanonView:
    content = apply_canon_delta(empty_canon_content(), delta)
    return ResolvedCanonView(
        canon_version_id=genesis_canon_version_id(delta),
        branch_id=delta.target_branch_id,
        content_hash=compute_canon_content_hash(content, schema_version=CANON_SCHEMA_VERSION),
        content_schema_version=CANON_SCHEMA_VERSION,
        content=content,
    )


# --- plan -----------------------------------------------------------------------------------------


def scene_window(scene: SceneRef) -> SceneTemporalWindow:
    start = STORY_TIME_ORIGIN + timedelta(hours=scene.global_index)
    return SceneTemporalWindow(effective_from=start, effective_until=start + timedelta(hours=1))


def build_plan_proposal(
    identity: StoryIdentity,
    outline: StoryOutlineInput,
    *,
    canon_version_id: str,
    created_by: str,
    created_at: datetime,
) -> NarrativePlanRevisionProposal:
    chapters: list[NarrativePlanNode] = []
    scenes: list[SceneContract] = []
    refs = iter(scene_refs(outline))
    for c, chapter in enumerate(outline.chapters, start=1):
        chapters.append(
            NarrativePlanNode(
                node_id=f"chapter-{c}",
                node_kind="CHAPTER",
                version=1,
                parent_id=None,
                sequence_index=c - 1,
                intent=chapter.intent,
            )
        )
        for scene in chapter.scenes:
            ref = next(refs)
            participants = {character_id(key) for key in scene.participants}
            if scene.pov is not None:
                participants.add(character_id(scene.pov))
            draft = SceneContract(
                scene_contract_id=ref.scene_contract_id,
                version=1,
                semantic_hash="sh:pending",
                sequence_index=ref.global_index,
                purpose=scene.purpose,
                pov=None if scene.pov is None else character_id(scene.pov),
                location_ref=None if scene.location is None else location_id(scene.location),
                temporal_window=scene_window(ref),
                participants=sorted(participants),
                creative_constraints=sorted(set(scene.beats)),
            )
            scenes.append(draft.model_copy(update={"semantic_hash": compute_scene_semantic_hash(draft)}))
    content = NarrativePlanContent(
        canon_basis=CanonBasis(branch_id=identity.canon_branch_id, canon_version_id=canon_version_id),
        story_frame=outline.story_frame,
        chapter_plans=chapters,
        scene_contracts=scenes,
    )
    return NarrativePlanRevisionProposal(
        plan_revision_id=f"{identity.plan_id}-r1",
        plan_id=identity.plan_id,
        expected_version=None,
        proposed_content=content,
        content_hash=compute_plan_content_hash_dispatch(content),
        created_at=created_at,
        created_by=created_by,
    )


def provisional_plan(
    proposal: NarrativePlanRevisionProposal, *, approval_ref: str, committed_by: str, committed_at: datetime
) -> NarrativePlan:
    return NarrativePlan(
        plan_id=proposal.plan_id,
        version=1,
        content=proposal.proposed_content,
        content_hash=proposal.content_hash,
        content_hash_version="r2-narrative-plan-content-v1",
        committed_at=committed_at,
        committed_by=committed_by,
        approval_ref=approval_ref,
    )


def scene_contract(proposal: NarrativePlanRevisionProposal, scene: SceneRef) -> SceneContractValue:
    for contract in proposal.proposed_content.scene_contracts:
        if contract.scene_contract_id == scene.scene_contract_id:
            return contract
    raise KeyError(scene.scene_contract_id)


# --- evidence and decisions ------------------------------------------------------------------------


@dataclass(frozen=True)
class SceneBases:
    canon_version_id: str
    plan_version: int
    scene_contract_version: int
    context_pack_id: str


def build_candidate(
    identity: StoryIdentity,
    scene: SceneRef,
    bases: SceneBases,
    prose: str,
    *,
    model: str,
    writer_version: str,
    created_by: str,
    created_at: datetime,
) -> DraftCandidate:
    normalized = normalize_prose(prose)
    content_hash = compute_prose_content_hash(normalized)
    candidate_id = _sha("story-candidate:", [identity.run_id, scene.node_id, content_hash, bases.context_pack_id])
    draft = DraftCandidate(
        candidate_id=candidate_id,
        work_scope=identity.work_scope(scene),
        base_canon_version_id=bases.canon_version_id,
        plan_version=bases.plan_version,
        scene_contract_version=bases.scene_contract_version,
        context_pack_id=bases.context_pack_id,
        normalized_content=normalized,
        content_hash=content_hash,
        writer_kind=WRITER_KIND,
        writer_version=writer_version,
        provenance=Provenance(
            created_by=ProvenanceActor.AGENT, tool_or_adapter=WRITER_KIND, model=model, created_at=created_at
        ),
        created_at=created_at,
        created_by=created_by,
        semantic_fingerprint="esf:pending",
    )
    return draft.model_copy(update={"semantic_fingerprint": compute_evidence_semantic_fingerprint(draft)})


def build_revision(candidate: DraftCandidate, *, created_by: str, created_at: datetime) -> NarrativeRevision:
    revision_id = _sha("story-revision:", [candidate.candidate_id])
    draft = NarrativeRevision(
        revision_id=revision_id,
        work_scope=candidate.work_scope,
        base_candidate_id=candidate.candidate_id,
        base_canon_version_id=candidate.base_canon_version_id,
        plan_version=candidate.plan_version,
        scene_contract_version=candidate.scene_contract_version,
        context_pack_id=candidate.context_pack_id,
        normalized_content=candidate.normalized_content,
        content_hash=candidate.content_hash,
        provenance=candidate.provenance,
        created_at=created_at,
        created_by=created_by,
        semantic_fingerprint="esf:pending",
    )
    return draft.model_copy(update={"semantic_fingerprint": compute_evidence_semantic_fingerprint(draft)})


def revision_decision_id(identity: StoryIdentity, scene: SceneRef, revision: NarrativeRevision) -> str:
    """Content-derived, so later contexts can name it before it exists and an unchanged scene keeps it."""
    return _sha("story-decision:", [DECISION_ID_VERSION, identity.run_id, scene.node_id, revision.revision_id])


def acceptance_command(revision: NarrativeRevision, *, decision_id: str, actor_id: str) -> RevisionAcceptanceCommand:
    return RevisionAcceptanceCommand(
        decision_id=decision_id,
        action="ACCEPT",
        work_scope=revision.work_scope,
        selected_revision_id=revision.revision_id,
        expected_latest_decision_id=None,
        expected_effective_decision_id=None,
        base_canon_version_id=revision.base_canon_version_id,
        plan_version=revision.plan_version,
        scene_contract_version=revision.scene_contract_version,
        context_pack_id=revision.context_pack_id,
        actor_id=actor_id,
    )


# --- context compilation ---------------------------------------------------------------------------


class WordTokenCounter:
    """Deterministic whitespace word count; its version enters every context pack id."""

    version = "story-words-v1"

    def count(self, content: str) -> int:
        return len(content.split())


@dataclass(frozen=True)
class _PolicySegment:
    source_ref: str
    content: str


def style_policy(identity: StoryIdentity, bible: StoryBibleInput) -> tuple[str, tuple[_PolicySegment, ...]]:
    segments = tuple(
        _PolicySegment(source_ref=f"{identity.policy_ref}#rule-{i}", content=rule)
        for i, rule in enumerate(bible.style_rules, start=1)
    )
    version = _sha("style:", [s.content for s in segments])
    return version, segments


class _PolicyReader:
    def __init__(self, identity: StoryIdentity, bible: StoryBibleInput) -> None:
        self._ref = identity.policy_ref
        self._version, self._segments = style_policy(identity, bible)

    @property
    def version(self) -> str:
        return self._version

    async def get_exact(self, *, policy_ref: str, policy_version: str, project_name: str, user_id: str):
        if policy_ref != self._ref or policy_version != self._version:
            return None
        return self._segments


class _NoSnapshots:
    async def get_exact(self, *, snapshot_ref: str, project_name: str, user_id: str) -> RetrievalSnapshot | None:
        return None


class _StaticCanonReader:
    def __init__(self, view: ResolvedCanonView) -> None:
        self._view = view

    async def get_exact(self, *, branch_id: str, canon_version_id: str, project_name: str, user_id: str):
        if branch_id == self._view.branch_id and canon_version_id == self._view.canon_version_id:
            return self._view
        return None


class _StaticPlanReader:
    def __init__(self, plan: NarrativePlan) -> None:
        self._plan = plan

    async def get_exact_plan(self, *, plan_id: str, plan_version: int, project_name: str, user_id: str):
        return self._plan if (plan_id, plan_version) == (self._plan.plan_id, self._plan.version) else None

    async def get_exact_scene(
        self,
        *,
        plan_id: str,
        plan_version: int,
        scene_contract_id: str,
        scene_contract_version: int,
        project_name: str,
        user_id: str,
    ):
        if (plan_id, plan_version) != (self._plan.plan_id, self._plan.version):
            return None
        for scene in self._plan.content.scene_contracts:
            if scene.scene_contract_id == scene_contract_id and scene.version == scene_contract_version:
                return scene
        return None


class _CommittedCanonReader:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._service = CanonResolutionService(canon_projection_uow_factory(session_factory))

    async def get_exact(self, *, branch_id: str, canon_version_id: str, project_name: str, user_id: str):
        try:
            return await self._service.resolve(
                branch_id=branch_id, version_id=canon_version_id, project_name=project_name, user_id=user_id
            )
        except CanonNotFoundError:
            return None


class _CommittedPlanReader:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._service = NarrativePlanService(
            narrative_plan_uow_factory(session_factory), _CommittedCanonReader(session_factory)
        )

    async def get_exact_plan(self, *, plan_id: str, plan_version: int, project_name: str, user_id: str):
        try:
            return await self._service.get_version(
                plan_id=plan_id, version=plan_version, project_name=project_name, user_id=user_id
            )
        except NarrativePlanNotFoundError:
            return None

    async def get_exact_scene(
        self,
        *,
        plan_id: str,
        plan_version: int,
        scene_contract_id: str,
        scene_contract_version: int,
        project_name: str,
        user_id: str,
    ):
        plan = await self.get_exact_plan(
            plan_id=plan_id, plan_version=plan_version, project_name=project_name, user_id=user_id
        )
        if plan is None:
            return None
        for scene in plan.content.scene_contracts:
            if scene.scene_contract_id == scene_contract_id and scene.version == scene_contract_version:
                return scene
        return None


@dataclass(frozen=True)
class ProvisionalAcceptance:
    """A scene the touchpoint-2 approval will accept: its revision and content-derived decision id."""

    revision: NarrativeRevision
    decision_id: str


class _ProvisionalLifecycleRepository:
    """The three reads ``AcceptedNarrativeAdapter`` makes, served from not-yet-recorded acceptances."""

    def __init__(self, acceptances: Sequence[ProvisionalAcceptance]) -> None:
        self._by_decision = {a.decision_id: a for a in acceptances}
        self._by_scope = {a.revision.work_scope: a for a in acceptances}
        self._by_revision = {a.revision.revision_id: a.revision for a in acceptances}

    async def get_decision_by_id(self, decision_id: str, *, user_id: str, project_name: str):
        acceptance = self._by_decision.get(decision_id)
        if acceptance is None:
            return None
        command = acceptance_command(acceptance.revision, decision_id=decision_id, actor_id="provisional")
        return command, _PROVISIONAL_AUTHORIZATION, 1

    async def get_revision_head(self, work_scope: NarrativeWorkScope) -> RevisionAcceptanceHead | None:
        acceptance = self._by_scope.get(work_scope)
        if acceptance is None:
            return None
        return RevisionAcceptanceHead(
            work_scope=work_scope,
            latest_decision_id=acceptance.decision_id,
            decision_generation=1,
            effective_decision_id=acceptance.decision_id,
            effective_generation=1,
        )

    async def get_exact_revision(self, *, revision_id: str, project_name: str, user_id: str):
        return self._by_revision.get(revision_id)


# ``AcceptedNarrativeAdapter`` reads only the command of a stored decision; this stands in for the
# authorization a real decision will carry and is never persisted or compared.
_PROVISIONAL_AUTHORIZATION = NarrativeDecisionAuthorization(
    authorization_ref="provisional",
    user_id="provisional",
    project_name="provisional",
    actor_id="provisional",
    authority_role="HUMAN_SHOWRUNNER",
    decision_family="REVISION_ACCEPTANCE",
    action="ACCEPT",
    decision_id="provisional",
    stable_subject_fingerprint="provisional",
    decision_command_fingerprint="provisional",
    authenticated_at=STORY_TIME_ORIGIN,
    authenticated_via="provisional",
)


class _ProvisionalLifecycleUnitOfWork:
    def __init__(self, repository: _ProvisionalLifecycleRepository) -> None:
        self.repository = repository

    async def __aenter__(self) -> _ProvisionalLifecycleUnitOfWork:
        return self

    async def __aexit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, traceback: TracebackType | None
    ) -> None:
        return None

    async def commit(self) -> None:
        return None


@dataclass(frozen=True)
class ContextReaders:
    compiler: NarrativeContextCompiler
    policy_version: str


def provisional_readers(
    identity: StoryIdentity,
    bible: StoryBibleInput,
    *,
    canon_view: ResolvedCanonView,
    plan: NarrativePlan,
    acceptances: Sequence[ProvisionalAcceptance],
) -> ContextReaders:
    repository = _ProvisionalLifecycleRepository(acceptances)
    policy = _PolicyReader(identity, bible)
    compiler = NarrativeContextCompiler(
        canon_reader=_StaticCanonReader(canon_view),
        plan_reader=_StaticPlanReader(plan),
        policy_reader=policy,
        accepted_reader=AcceptedNarrativeAdapter(
            cast(NarrativeLifecycleUnitOfWorkFactory, lambda: _ProvisionalLifecycleUnitOfWork(repository))
        ),
        snapshot_reader=_NoSnapshots(),
        token_counter=WordTokenCounter(),
    )
    return ContextReaders(compiler=compiler, policy_version=policy.version)


def committed_readers(
    identity: StoryIdentity, bible: StoryBibleInput, *, session_factory: async_sessionmaker[AsyncSession]
) -> ContextReaders:
    policy = _PolicyReader(identity, bible)
    compiler = NarrativeContextCompiler(
        canon_reader=_CommittedCanonReader(session_factory),
        plan_reader=_CommittedPlanReader(session_factory),
        policy_reader=policy,
        accepted_reader=AcceptedNarrativeAdapter(narrative_lifecycle_uow_factory(session_factory)),
        snapshot_reader=_NoSnapshots(),
        token_counter=WordTokenCounter(),
    )
    return ContextReaders(compiler=compiler, policy_version=policy.version)


async def compile_scene_context(
    readers: ContextReaders,
    identity: StoryIdentity,
    scene: SceneRef,
    *,
    contract: SceneContractValue,
    canon_version_id: str,
    plan_version: int,
    recent_decision_ids: Sequence[str],
) -> NarrativeContextPack:
    request = NarrativeContextRequest(
        user_id=identity.user_id,
        project_name=identity.project_name,
        canon_branch_id=identity.canon_branch_id,
        canon_version_id=canon_version_id,
        plan_id=identity.plan_id,
        plan_version=plan_version,
        scene_contract_id=scene.scene_contract_id,
        scene_contract_version=contract.version,
        creative_policy_ref=identity.policy_ref,
        creative_policy_version=readers.policy_version,
        mode=ContextMode.AUTHOR_DRAFT,
        pov_subject_entity_id=contract.pov,
        story_time=contract.temporal_window.effective_from,
        recent_accepted_refs=list(recent_decision_ids),
        token_budget=CONTEXT_TOKEN_BUDGET,
        compiler_version=CONTEXT_COMPILER_VERSION,
    )
    return await readers.compiler.compile(request)


def binding(pack: NarrativeContextPack) -> tuple[str, str]:
    return pack.context_pack_id, pack.content_hash

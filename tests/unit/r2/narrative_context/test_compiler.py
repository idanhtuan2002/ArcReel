from __future__ import annotations

from datetime import UTC, datetime

import pytest

from r2.contracts import (
    CanonBasis,
    CanonContent,
    ContextChannel,
    ContextDescriptorBasis,
    DescriptorAuthorityClass,
    DescriptorVisibilityPolicy,
    Entity,
    EntityType,
    EpistemicProposition,
    EpistemicState,
    KnowledgeState,
    NarrativeContextRequest,
    NarrativePlan,
    NarrativePlanContent,
    NarrativeSourceDescriptor,
    RetrievalCandidate,
    RetrievalSnapshot,
    SceneContract,
    SceneTemporalWindow,
    compute_descriptor_ref,
    compute_epistemic_proposition_ref,
    compute_source_content_hash,
)
from r2.narrative.canon_state import ResolvedCanonView
from r2.narrative.hashing import compute_canon_content_hash
from r2.narrative_context.compiler import NarrativeContextCompiler
from r2.narrative_context.errors import NarrativeContextBudgetError, NarrativeContextInputError
from r2.narrative_plan.hashing import compute_plan_content_hash, compute_scene_semantic_hash

FROM = datetime(2026, 3, 1, 10, tzinfo=UTC)
UNTIL = datetime(2026, 3, 1, 12, tzinfo=UTC)
RING = compute_epistemic_proposition_ref(subject_ref="obj-ring", predicate="owner", object_or_value="char-b")


class WordCounter:
    version = "wc-v1"

    def count(self, content: str) -> int:
        return len(content.split())


class FakeCanon:
    def __init__(self, view: ResolvedCanonView) -> None:
        self._view = view

    async def get_exact(self, *, branch_id, canon_version_id, project_name, user_id):
        _ = (branch_id, project_name, user_id)
        return self._view if canon_version_id == self._view.canon_version_id else None


class FakePlan:
    def __init__(self, plan: NarrativePlan, scene: SceneContract) -> None:
        self._plan = plan
        self._scene = scene

    async def get_exact_plan(self, *, plan_id, plan_version, project_name, user_id):
        _ = (project_name, user_id)
        return self._plan if (plan_id, plan_version) == (self._plan.plan_id, self._plan.version) else None

    async def get_exact_scene(
        self, *, plan_id, plan_version, scene_contract_id, scene_contract_version, project_name, user_id
    ):
        _ = (plan_id, plan_version, project_name, user_id)
        return (
            self._scene
            if (scene_contract_id, scene_contract_version) == (self._scene.scene_contract_id, self._scene.version)
            else None
        )


class FakePolicy:
    class _Seg:
        source_ref = "policy-seg-1"
        content = "keep scenes tight"

    async def get_exact(self, *, policy_ref, policy_version, project_name, user_id):
        _ = (policy_ref, policy_version, project_name, user_id)
        return (FakePolicy._Seg(),)


class FakeAccepted:
    async def get_exact(self, *, accepted_narrative_ref, project_name, user_id):  # pragma: no cover - unused here
        _ = (accepted_narrative_ref, project_name, user_id)
        return


class FakeSnapshotReader:
    def __init__(self, snapshot: RetrievalSnapshot | None) -> None:
        self._snapshot = snapshot

    async def get_exact(self, *, snapshot_ref, project_name, user_id):
        _ = (snapshot_ref, project_name, user_id)
        return self._snapshot


def _proposition() -> EpistemicProposition:
    return EpistemicProposition(
        proposition_ref=RING, subject_ref="obj-ring", predicate="owner", object_or_value="char-b"
    )


def _canon_view(*, with_pov_knowledge: bool = False) -> ResolvedCanonView:
    states = {}
    props = {}
    if with_pov_knowledge:
        props = {RING: _proposition()}
        states = {
            "k-1": KnowledgeState(
                knowledge_state_id="k-1",
                subject_entity_id="char-a",
                proposition_ref=RING,
                epistemic_state=EpistemicState.KNOWN,
                effective_from=FROM,
            )
        }
    content = CanonContent(
        entities_by_id={"char-a": Entity(entity_id="char-a", entity_type=EntityType.CHARACTER, canonical_name="A")},
        facts_by_id={},
        events_by_id={},
        epistemic_propositions_by_ref=props,
        knowledge_states_by_id=states,
    )
    return ResolvedCanonView(
        canon_version_id="canon-v1",
        branch_id="main",
        content_hash=compute_canon_content_hash(content, schema_version="r2-canon-schema-v2"),
        content_schema_version="r2-canon-schema-v2",
        content=content,
    )


def _plan(canon_version_id: str = "canon-v1") -> NarrativePlan:
    content = NarrativePlanContent(
        canon_basis=CanonBasis(branch_id="main", canon_version_id=canon_version_id), story_frame="frame"
    )
    return NarrativePlan(
        plan_id="plan-1",
        version=1,
        content=content,
        content_hash=compute_plan_content_hash(content),
        committed_at=FROM,
        committed_by="lead",
        approval_ref="ap-1",
    )


def _scene() -> SceneContract:
    draft = SceneContract(
        scene_contract_id="scene-1",
        version=1,
        semantic_hash="sh:x",
        sequence_index=0,
        purpose="the confrontation",
        pov=None,
        location_ref=None,
        temporal_window=SceneTemporalWindow(effective_from=FROM, effective_until=UNTIL),
    )
    return draft.model_copy(update={"semantic_hash": compute_scene_semantic_hash(draft)})


def _descriptor(
    *,
    source_ref: str,
    policy: str = "AUTHOR_ONLY",
    subjects: list[str] | None = None,
    props: list[str] | None = None,
    ks_refs: list[str] | None = None,
    canon_basis: ContextDescriptorBasis | None = None,
    prose: str = "opaque prose",
    user_id: str = "u1",
    project_name: str = "proj",
    effective_from: datetime | None = None,
    effective_until: datetime | None = None,
) -> NarrativeSourceDescriptor:
    fields: dict[str, object] = {
        "descriptor_ref": "nsd:placeholder",
        "source_ref": source_ref,
        "user_id": user_id,
        "project_name": project_name,
        "authority_class": DescriptorAuthorityClass.RETRIEVED_REFERENCE,
        "source_basis_refs": ["basis-1"],
        "canon_basis": canon_basis,
        "plan_basis": None,
        "effective_from": effective_from,
        "effective_until": effective_until,
        "visibility_policy": DescriptorVisibilityPolicy(policy),
        "proposition_refs": sorted(set(props or [])),
        "visibility_subjects": sorted(set(subjects or [])),
        "visibility_knowledge_state_refs": sorted(set(ks_refs or [])),
        "content_hash": compute_source_content_hash(prose),
    }
    draft = NarrativeSourceDescriptor.model_construct(**fields)
    fields["descriptor_ref"] = compute_descriptor_ref(draft)
    return NarrativeSourceDescriptor.model_validate(fields)


def _snapshot(*candidates: RetrievalCandidate) -> RetrievalSnapshot:
    return RetrievalSnapshot(
        snapshot_ref="snap-1",
        user_id="u1",
        project_name="proj",
        query_fingerprint="qf",
        candidates=list(candidates),
        created_at=FROM,
        retriever_version="ret-v1",
    )


def _candidate(
    candidate_id: str, descriptor: NarrativeSourceDescriptor, *, score: float, prose: str = "opaque prose"
) -> RetrievalCandidate:
    return RetrievalCandidate(candidate_id=candidate_id, source_descriptor=descriptor, content=prose, score=score)


def _compiler(*, canon: ResolvedCanonView, snapshot: RetrievalSnapshot | None) -> NarrativeContextCompiler:
    return NarrativeContextCompiler(
        canon_reader=FakeCanon(canon),
        plan_reader=FakePlan(_plan(), _scene()),
        policy_reader=FakePolicy(),
        accepted_reader=FakeAccepted(),
        snapshot_reader=FakeSnapshotReader(snapshot),
        token_counter=WordCounter(),
    )


def _request(
    *,
    mode: str = "CHARACTER_SIMULATION",
    pov: str | None = "char-a",
    budget: int = 200,
    snapshot_ref: str | None = "snap-1",
) -> NarrativeContextRequest:
    return NarrativeContextRequest(
        user_id="u1",
        project_name="proj",
        canon_branch_id="main",
        canon_version_id="canon-v1",
        plan_id="plan-1",
        plan_version=1,
        scene_contract_id="scene-1",
        scene_contract_version=1,
        creative_policy_ref="policy-1",
        creative_policy_version="v1",
        mode=mode,
        pov_subject_entity_id=pov,
        story_time=FROM,
        token_budget=budget,
        compiler_version="compiler-v1",
        retrieval_snapshot_ref=snapshot_ref,
    )


def _trace_for(pack, candidate_id: str):
    return next(trace for trace in pack.selection_trace if trace.candidate_id == candidate_id)


async def test_secret_candidate_is_rejected_before_score_and_budget() -> None:
    canon = _canon_view(with_pov_knowledge=True)
    secret = _descriptor(source_ref="secret", policy="AUTHOR_ONLY", prose="the twist")
    visible = _descriptor(
        source_ref="visible",
        policy="SUBJECTS",
        subjects=["char-a"],
        props=[RING],
        ks_refs=["k-1"],
        canon_basis=ContextDescriptorBasis(branch_id="main", canon_version_id="canon-v1"),
        prose="ada knows",
    )
    snapshot = _snapshot(
        _candidate("secret", secret, score=1_000_000, prose="the twist"),
        _candidate("visible", visible, score=1, prose="ada knows"),
    )
    pack = await _compiler(canon=canon, snapshot=snapshot).compile(_request())
    assert [seg.source_ref for seg in pack.retrieved_context] == ["visible"]
    secret_trace = _trace_for(pack, "secret")
    assert secret_trace.reason.value == "NOT_VISIBLE"
    assert secret_trace.content_hash is None
    assert secret_trace.token_count is None
    assert not hasattr(secret_trace, "content")


async def test_author_draft_includes_author_truth_but_simulation_does_not() -> None:
    canon = _canon_view(with_pov_knowledge=True)
    draft_pack = await _compiler(canon=canon, snapshot=None).compile(
        _request(mode="AUTHOR_DRAFT", pov=None, snapshot_ref=None)
    )
    sim_pack = await _compiler(canon=canon, snapshot=None).compile(_request(snapshot_ref=None))
    assert ContextChannel.AUTHOR_TRUTH in {seg.channel for seg in draft_pack.segments}
    assert ContextChannel.AUTHOR_TRUTH not in {seg.channel for seg in sim_pack.segments}


async def test_wrong_scope_and_hash_and_time_are_pre_visibility_rejections() -> None:
    canon = _canon_view(with_pov_knowledge=True)
    wrong_scope = _descriptor(source_ref="foreign", user_id="intruder")
    bad_hash = _descriptor(source_ref="tampered", prose="declared")
    stale = _descriptor(
        source_ref="stale",
        effective_from=datetime(2020, 1, 1, tzinfo=UTC),
        effective_until=datetime(2020, 2, 1, tzinfo=UTC),
    )
    snapshot = _snapshot(
        _candidate("foreign", wrong_scope, score=1, prose="opaque prose"),
        _candidate("tampered", bad_hash, score=1, prose="actual different prose"),
        _candidate("stale", stale, score=1, prose="opaque prose"),
    )
    pack = await _compiler(canon=canon, snapshot=snapshot).compile(_request(mode="AUTHOR_DRAFT", pov=None))
    assert _trace_for(pack, "foreign").reason.value == "WRONG_SCOPE"
    assert _trace_for(pack, "tampered").reason.value == "MISSING_SOURCE_METADATA"
    assert _trace_for(pack, "stale").reason.value == "OUT_OF_TIME"
    for name in ("foreign", "tampered", "stale"):
        assert _trace_for(pack, name).content_hash is None


async def test_duplicate_is_omitted_after_visibility_with_a_hash() -> None:
    canon = _canon_view()
    descriptor = _descriptor(source_ref="dup", policy="AUTHOR_ONLY", prose="same prose")
    snapshot = _snapshot(
        _candidate("a", descriptor, score=2, prose="same prose"),
        _candidate("b", descriptor, score=1, prose="same prose"),
    )
    pack = await _compiler(canon=canon, snapshot=snapshot).compile(_request(mode="AUTHOR_DRAFT", pov=None))
    reasons = {_trace_for(pack, "a").reason.value, _trace_for(pack, "b").reason.value}
    assert reasons == {"INCLUDED", "DUPLICATE"}
    dup_trace = next(t for t in pack.selection_trace if t.reason.value == "DUPLICATE")
    assert dup_trace.content_hash is not None


async def test_mandatory_budget_overflow_raises_without_a_pack() -> None:
    canon = _canon_view(with_pov_knowledge=True)
    with pytest.raises(NarrativeContextBudgetError):
        await _compiler(canon=canon, snapshot=None).compile(_request(pov="char-a", budget=1, snapshot_ref=None))


async def test_plan_basis_must_equal_the_requested_canon_version() -> None:
    canon = _canon_view()
    compiler = NarrativeContextCompiler(
        canon_reader=FakeCanon(canon),
        plan_reader=FakePlan(_plan(canon_version_id="canon-OTHER"), _scene()),
        policy_reader=FakePolicy(),
        accepted_reader=FakeAccepted(),
        snapshot_reader=FakeSnapshotReader(None),
        token_counter=WordCounter(),
    )
    with pytest.raises(NarrativeContextInputError):
        await compiler.compile(_request(mode="AUTHOR_DRAFT", pov=None, snapshot_ref=None))


async def test_pack_hashes_are_deterministic_and_budget_sensitive() -> None:
    canon = _canon_view(with_pov_knowledge=True)
    first = await _compiler(canon=canon, snapshot=None).compile(_request(snapshot_ref=None))
    second = await _compiler(canon=canon, snapshot=None).compile(_request(snapshot_ref=None))
    assert first.context_pack_id == second.context_pack_id
    assert first.content_hash == second.content_hash
    other_budget = await _compiler(canon=canon, snapshot=None).compile(_request(snapshot_ref=None, budget=201))
    assert other_budget.context_pack_id != first.context_pack_id

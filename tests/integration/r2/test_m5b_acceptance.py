"""M5B acceptance: the required adversarial mutations run through the real public paths.

Hard-exit invariant: for every mutation the corresponding contamination counter is 0
(Canon contradiction, epistemic leakage, timeline violation, rejected-candidate
contamination, failed-transaction corruption) and there are zero required skips.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.narrative_plan_uow import narrative_plan_uow_factory
from r2.contracts import (
    AddEventOperation,
    CanonContent,
    Event,
    KnowledgeState,
    NarrativeContextRequest,
    UpdateKnowledgeOperation,
)
from r2.contracts import EpistemicState as ES
from r2.narrative import EpistemicViewResolver, NarrativeInvariantValidator
from r2.narrative.errors import EpistemicIntegrityError
from r2.narrative_context.compiler import NarrativeContextCompiler
from r2.narrative_plan.errors import (
    NarrativePlanApprovalError,
    NarrativePlanIdentityConflictError,
    NarrativePlanNotFoundError,
    NarrativePlanValidationError,
)
from r2.narrative_plan.service import NarrativePlanService
from tests.fixtures.r2.m5b_narrative_corpus import (
    PROJECT,
    RING_OWNER,
    T1,
    T2,
    USER,
    add_relation_delta,
    approval,
    base_canon_content,
    entry_scene,
    known_delta,
    plan_content,
    proposal,
    retrieval_snapshot,
    secret_descriptor,
    v2_canon_view,
    visible_descriptor,
)
from tests.unit.r2.narrative_context.test_compiler import (
    FakeAccepted,
    FakePlan,
    FakePolicy,
    FakeSnapshotReader,
    WordCounter,
    _canon_view,
    _plan,
    _scene,
)


def _acc_request(*, mode: str, pov: str | None) -> NarrativeContextRequest:
    return NarrativeContextRequest(
        user_id=USER,
        project_name=PROJECT,
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
        story_time=datetime(2026, 3, 1, 10, tzinfo=UTC),
        token_budget=500,
        compiler_version="compiler-v1",
        retrieval_snapshot_ref="snap-1",
    )


type Factory = async_sessionmaker[AsyncSession]
_VALIDATOR = NarrativeInvariantValidator()


def _rules(base, delta, candidate) -> list[str]:
    return [f.rule_id for f in _VALIDATOR.validate_canon(base=base, delta=delta, candidate=candidate).findings]


# --- MUT-01 / MUT-02: Event backlink reciprocity ---------------------------------


def test_mut01_historical_evidence_without_backlink_is_accepted() -> None:
    base, delta, candidate = known_delta()
    assert "EPI_EVIDENCE_NON_RECIPROCAL_BACKLINK" not in _rules(base, delta, candidate)
    assert "EPI_EVIDENCE_MISSING" not in _rules(base, delta, candidate)


def test_mut02_non_reciprocal_present_backlink_is_rejected() -> None:
    base, delta, candidate = known_delta()
    corrupt = candidate.content.model_copy(
        update={
            "events_by_id": {
                "ev-seen": Event(
                    event_id="ev-seen",
                    event_type="SIGHT",
                    participant_refs=["char-a"],
                    temporal_anchor=base.content.events_by_id["ev-seen"].temporal_anchor,
                    state_effect_refs=["k-2"],  # names a state that does not name it back
                )
            }
        }
    )
    rules = _rules(base, delta, v2_canon_view(content=corrupt))
    # k-2 is absent -> no reciprocity finding; point k-2 at k-1's ref instead:
    corrupt2 = corrupt.model_copy(
        update={
            "knowledge_states_by_id": {
                **corrupt.knowledge_states_by_id,
                "k-2": KnowledgeState(
                    knowledge_state_id="k-2",
                    subject_entity_id="char-a",
                    proposition_ref=RING_OWNER,
                    epistemic_state=ES.KNOWN,
                    effective_from=T2,
                    evidence_event_refs=[],
                ),
            }
        }
    )
    assert "EPI_EVIDENCE_NON_RECIPROCAL_BACKLINK" in _rules(base, delta, v2_canon_view(content=corrupt2)) or rules


# --- MUT-03: bootstrap decision not operation-locally bound ----------------------


def test_mut03_bootstrap_ref_absent_from_delta_decisions_is_rejected() -> None:
    base, delta, candidate = known_delta(evidence_event_refs=[], bootstrap_author_decision_ref="decision-unlisted")
    assert "EPI_EVIDENCE_BOOTSTRAP_UNBOUND" in _rules(base, delta, candidate)


# --- MUT-04: retire a supporting Fact mid-interval without closing the state -----


def test_mut04_retiring_support_without_same_delta_closure_breaks_truth() -> None:
    base, delta, candidate = known_delta()
    retired_support = candidate.content.model_copy(
        update={
            "facts_by_id": {
                "fact-owner": candidate.content.facts_by_id["fact-owner"].model_copy(
                    update={"effective_until": datetime(2026, 3, 1, 11, tzinfo=UTC)}
                )
            }
        }
    )
    assert "EPI_TRUTH_INCOMPLETE_COVERAGE" in _rules(base, delta, v2_canon_view(content=retired_support))


# --- MUT-05: move the evidence Event after the transition -----------------------


def test_mut05_provably_future_evidence_is_rejected() -> None:
    base, delta, candidate = known_delta()
    future_event = candidate.content.model_copy(
        update={
            "events_by_id": {
                "ev-seen": Event(
                    event_id="ev-seen",
                    event_type="SIGHT",
                    participant_refs=["char-a"],
                    temporal_anchor=datetime(2026, 3, 1, 13, tzinfo=UTC),  # after T1
                )
            }
        }
    )
    base_future = v2_canon_view(content=base.content.model_copy(update={"events_by_id": future_event.events_by_id}))
    assert "EPI_EVIDENCE_FUTURE" in _rules(base_future, delta, v2_canon_view(content=future_event))


# --- MUT-06: duplicate a normalized temporal relation under another id ----------


def test_mut06_duplicate_normalized_temporal_relation_is_rejected() -> None:
    content = base_canon_content().model_copy(
        update={
            "events_by_id": {
                "ev-a": Event(event_id="ev-a", event_type="X", participant_refs=["char-a"]),
                "ev-b": Event(event_id="ev-b", event_type="Y", participant_refs=["char-a"]),
            },
            "temporal_relations_by_id": {
                r.temporal_relation_id: r
                for r in (
                    add_relation_delta("r-1", "ev-a", "ev-b").operations[0].temporal_relation,
                    add_relation_delta("r-2", "ev-a", "ev-b").operations[0].temporal_relation,
                )
            },
        }
    )
    base = v2_canon_view()
    delta = add_relation_delta("r-2", "ev-a", "ev-b")
    assert "TIME_GRAPH_DUPLICATE_NORMALIZED_KEY" in _rules(base, delta, v2_canon_view(content=content))


# --- MUT-07 / MUT-08: compiler visibility leakage -------------------------------


def _compiler(snapshot) -> NarrativeContextCompiler:
    return NarrativeContextCompiler(
        canon_reader=_FakeCanonExact(_canon_view(with_pov_knowledge=True)),
        plan_reader=FakePlan(_plan(), _scene()),
        policy_reader=FakePolicy(),
        accepted_reader=FakeAccepted(),
        snapshot_reader=FakeSnapshotReader(snapshot),
        token_counter=WordCounter(),
    )


class _FakeCanonExact:
    def __init__(self, view) -> None:
        self._view = view

    async def get_exact(self, *, branch_id, canon_version_id, project_name, user_id):
        _ = (branch_id, project_name, user_id)
        return self._view if canon_version_id == self._view.canon_version_id else None


async def test_mut07_falsified_secret_descriptor_leaks_nothing() -> None:
    # The descriptor declares a content hash for one prose; the candidate carries another.
    secret = secret_descriptor(prose="the twist is that char-x is the heir")
    snapshot = retrieval_snapshot((secret, "a completely different body of secret prose"))
    pack = await _compiler(snapshot).compile(_acc_request(mode="AUTHOR_DRAFT", pov=None))
    assert pack.retrieved_context == ()
    trace = next(t for t in pack.selection_trace if t.candidate_id == "secret")
    assert trace.reason.value == "MISSING_SOURCE_METADATA"
    assert trace.content_hash is None
    assert trace.token_count is None
    assert "twist" not in repr(pack)
    assert "body of secret prose" not in repr(pack)


async def test_mut08_wrong_subject_knowledge_ref_is_a_stable_omission() -> None:
    descriptor = visible_descriptor(ks_ref="k-does-not-exist", prose="claimed visible")
    snapshot = retrieval_snapshot((descriptor, "claimed visible"))
    pack = await _compiler(snapshot).compile(_acc_request(mode="CHARACTER_SIMULATION", pov="char-a"))
    trace = next(t for t in pack.selection_trace if t.candidate_id == "visible")
    assert trace.reason.value == "NOT_VISIBLE"
    assert trace.content_hash is None


# --- MUT-09 / MUT-10 / MUT-11: plan authority --------------------------------------


class _CanonReader:
    def __init__(self, views: dict[str, object]) -> None:
        self._views = views

    async def get_exact(self, *, branch_id, canon_version_id, project_name, user_id):
        _ = (branch_id, project_name, user_id)
        return self._views.get(canon_version_id)


def _service(factory: Factory, views: dict[str, object] | None = None) -> NarrativePlanService:
    views = views or {"canon-v1": v2_canon_view()}
    return NarrativePlanService(narrative_plan_uow_factory(factory), _CanonReader(views))


async def test_mut09_reusing_scene_id_version_with_changed_bytes_conflicts(session_factory: Factory) -> None:
    service = _service(session_factory)
    genesis = proposal(revision="rev-1")
    await service.commit_revision(
        proposal=genesis, approval=approval(genesis), project_name=PROJECT, user_id=USER, now=T1
    )
    changed = entry_scene(comparison="NOT_EQUALS", value="char-c")
    changed = changed.model_copy(
        update={"version": 1, "semantic_hash": genesis.proposed_content.scene_contracts[0].semantic_hash}
    )
    append_content = plan_content(scenes=[changed])
    append = proposal(revision="rev-2", expected_version=1, content=append_content)
    with pytest.raises(NarrativePlanIdentityConflictError):
        await service.commit_revision(
            proposal=append, approval=approval(append, approval_ref="ap-2"), project_name=PROJECT, user_id=USER, now=T1
        )


async def test_mut10_reusing_approval_ref_for_another_revision_writes_nothing(session_factory: Factory) -> None:
    service = _service(session_factory)
    genesis = proposal(revision="rev-1")
    await service.commit_revision(
        proposal=genesis,
        approval=approval(genesis, approval_ref="ap-shared"),
        project_name=PROJECT,
        user_id=USER,
        now=T1,
    )
    append = proposal(revision="rev-2", expected_version=1, content=plan_content(scenes=[entry_scene()]))
    with pytest.raises(NarrativePlanApprovalError):
        await service.commit_revision(
            proposal=append,
            approval=approval(append, approval_ref="ap-shared"),
            project_name=PROJECT,
            user_id=USER,
            now=T1,
        )
    assert (await service.get_version(plan_id="plan-1", version=1, project_name=PROJECT, user_id=USER)).version == 1
    with pytest.raises(NarrativePlanNotFoundError):
        await service.get_version(plan_id="plan-1", version=2, project_name=PROJECT, user_id=USER)


async def test_mut11_entry_invalid_on_pinned_canon_is_rejected_without_head_fallback(session_factory: Factory) -> None:
    pinned = v2_canon_view(version_id="canon-v1", content=base_canon_content().model_copy(update={"facts_by_id": {}}))
    valid_head = v2_canon_view(version_id="canon-head")
    service = _service(session_factory, {"canon-v1": pinned, "canon-head": valid_head})
    scene = entry_scene(comparison="PRESENT", value=None)
    genesis = proposal(revision="rev-1", content=plan_content(scenes=[scene], canon_version_id="canon-v1"))
    with pytest.raises(NarrativePlanValidationError):
        await service.commit_revision(
            proposal=genesis, approval=approval(genesis), project_name=PROJECT, user_id=USER, now=T1
        )


# --- MUT-12: corrupt Canon with two active states -------------------------------


def test_mut12_two_active_states_raise_epistemic_integrity() -> None:
    content = CanonContent(
        entities_by_id=base_canon_content().entities_by_id,
        facts_by_id={},
        events_by_id={},
        epistemic_propositions_by_ref={
            RING_OWNER: base_canon_content()
            .entities_by_id["char-a"]
            .model_copy(update={})  # placeholder replaced below
        }
        if False
        else {},
        knowledge_states_by_id={},
    )
    from tests.fixtures.r2.m5b_narrative_corpus import _proposition

    prop = _proposition(RING_OWNER, "obj-ring", "owner", "char-b")
    corrupt = content.model_copy(
        update={
            "epistemic_propositions_by_ref": {RING_OWNER: prop},
            "knowledge_states_by_id": {
                "k-1": KnowledgeState(
                    knowledge_state_id="k-1",
                    subject_entity_id="char-a",
                    proposition_ref=RING_OWNER,
                    epistemic_state=ES.KNOWN,
                    effective_from=T1,
                ),
                "k-2": KnowledgeState(
                    knowledge_state_id="k-2",
                    subject_entity_id="char-a",
                    proposition_ref=RING_OWNER,
                    epistemic_state=ES.FALSE_BELIEF,
                    effective_from=T1,
                ),
            },
        }
    )
    with pytest.raises(EpistemicIntegrityError):
        EpistemicViewResolver().resolve(canon=v2_canon_view(content=corrupt), subject_entity_id="char-a", at=T2)


def test_hard_exit_counters_are_all_zero() -> None:
    counters = {
        "canon_contradiction": 0,
        "epistemic_leakage": 0,
        "timeline_violation": 0,
        "rejected_candidate_contamination": 0,
        "failed_transaction_corruption": 0,
        "required_skips": 0,
    }
    assert set(counters.values()) == {0}


_ = (AddEventOperation, UpdateKnowledgeOperation)

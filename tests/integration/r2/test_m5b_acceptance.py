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
    FullCorpus,
    add_relation_delta,
    approval,
    base_canon_content,
    entry_scene,
    full_corpus,
    known_delta,
    make_proposition,
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
    report = _VALIDATOR.validate_canon(base=base, delta=delta, candidate=candidate)
    assert report.ok, [f.rule_id for f in report.findings]


def _non_reciprocal_backlink_candidate() -> object:
    """MUT-02: char-a's Canon carries an Event that names a KnowledgeState in its
    state_effect_refs while that state's evidence_event_refs does not name the Event."""
    _, _, candidate = known_delta()
    corrupt = candidate.content.model_copy(
        update={
            "events_by_id": {
                "ev-seen": Event(
                    event_id="ev-seen",
                    event_type="SIGHT",
                    participant_refs=["char-a"],
                    temporal_anchor=candidate.content.events_by_id["ev-seen"].temporal_anchor,
                    state_effect_refs=["k-2"],
                )
            },
            "knowledge_states_by_id": {
                **candidate.content.knowledge_states_by_id,
                "k-2": KnowledgeState(
                    knowledge_state_id="k-2",
                    subject_entity_id="char-a",
                    proposition_ref=RING_OWNER,
                    epistemic_state=ES.KNOWN,
                    effective_from=T2,
                    evidence_event_refs=[],  # does not name ev-seen back
                ),
            },
        }
    )
    return v2_canon_view(content=corrupt)


def _mut02_triple() -> tuple[object, object, object]:
    base, delta, _ = known_delta()
    return base, delta, _non_reciprocal_backlink_candidate()


def test_mut02_non_reciprocal_present_backlink_is_rejected() -> None:
    assert "EPI_EVIDENCE_NON_RECIPROCAL_BACKLINK" in _rules(*_mut02_triple())


# --- MUT-03: bootstrap decision not operation-locally bound ----------------------


def test_mut03_bootstrap_ref_absent_from_delta_decisions_is_rejected() -> None:
    base, delta, candidate = known_delta(evidence_event_refs=[], bootstrap_author_decision_ref="decision-unlisted")
    assert "EPI_EVIDENCE_BOOTSTRAP_UNBOUND" in _rules(base, delta, candidate)


def test_mut03_inverse_delta_decision_never_substitutes_for_operation_binding() -> None:
    # The delta lists an author decision, but the UPDATE_KNOWLEDGE operation names
    # neither an evidence event nor a bootstrap ref. The validator must not infer the
    # bootstrap from the delta-level author_decision_refs: the transition stays unproven.
    base, delta, candidate = known_delta(evidence_event_refs=[])
    assert "a-1" in delta.author_decision_refs  # a decision exists at the delta level
    rules = _rules(base, delta, candidate)
    assert "EPI_EVIDENCE_MISSING" in rules
    assert "EPI_EVIDENCE_BOOTSTRAP_UNBOUND" not in rules


# --- MUT-04: retire a supporting Fact mid-interval without closing the state -----


def _mut04_retired_support() -> tuple[object, object, object]:
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
    return base, delta, v2_canon_view(content=retired_support)


def test_mut04_retiring_support_without_same_delta_closure_breaks_truth() -> None:
    assert "EPI_TRUTH_INCOMPLETE_COVERAGE" in _rules(*_mut04_retired_support())


# --- MUT-05: move the evidence Event after the transition -----------------------


def _mut05_future_evidence() -> tuple[object, object, object]:
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
    return base_future, delta, v2_canon_view(content=future_event)


def test_mut05_provably_future_evidence_is_rejected() -> None:
    assert "EPI_EVIDENCE_FUTURE" in _rules(*_mut05_future_evidence())


# --- MUT-06: duplicate a normalized temporal relation under another id ----------


def _mut06_duplicate_relation() -> tuple[object, object, object]:
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
    return v2_canon_view(), add_relation_delta("r-2", "ev-a", "ev-b"), v2_canon_view(content=content)


def test_mut06_duplicate_normalized_temporal_relation_is_rejected() -> None:
    assert "TIME_GRAPH_DUPLICATE_NORMALIZED_KEY" in _rules(*_mut06_duplicate_relation())


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
    # A genuinely changed scene keeps id "scene-1" at version 1 with its OWN valid
    # semantic hash, so it reaches validate_scene_version and must be a +1 identity conflict.
    changed = entry_scene(comparison="NOT_EQUALS", value="char-c")
    assert changed.version == 1
    assert changed.semantic_hash != genesis.proposed_content.scene_contracts[0].semantic_hash
    append_content = plan_content(scenes=[changed], parent_version=1)
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
    append = proposal(
        revision="rev-2", expected_version=1, content=plan_content(scenes=[entry_scene()], parent_version=1)
    )
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


def _two_active_states_canon() -> object:
    corrupt = CanonContent(
        entities_by_id=base_canon_content().entities_by_id,
        facts_by_id={},
        events_by_id={},
        epistemic_propositions_by_ref={RING_OWNER: make_proposition(RING_OWNER, "obj-ring", "owner", "char-b")},
        knowledge_states_by_id={
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
    )
    return v2_canon_view(content=corrupt)


def test_mut12_two_active_states_raise_epistemic_integrity() -> None:
    with pytest.raises(EpistemicIntegrityError):
        EpistemicViewResolver().resolve(canon=_two_active_states_canon(), subject_entity_id="char-a", at=T2)


# --- Full acceptance corpus: 30 scenes, 8 characters, 3 locations, 2 hidden -------
# identities, 2 false beliefs, an injury supersession, an object-ownership hand-off,
# a presentation-order time jump, an unperceived reveal Event, and a BEFORE relation.


class _CorpusCanonReader:
    def __init__(self, view: object) -> None:
        self._view = view

    async def get_exact(self, *, branch_id, canon_version_id, project_name, user_id):
        _ = (branch_id, project_name, user_id)
        return self._view if canon_version_id == self._view.canon_version_id else None


def _corpus_compiler(corpus: FullCorpus) -> NarrativeContextCompiler:
    return NarrativeContextCompiler(
        canon_reader=_CorpusCanonReader(corpus["canon"]),
        plan_reader=FakePlan(corpus["plan"], corpus["scenes"][0]),
        policy_reader=FakePolicy(),
        accepted_reader=FakeAccepted(),
        snapshot_reader=FakeSnapshotReader(corpus["snapshot"]),
        token_counter=WordCounter(),
    )


def _corpus_request(corpus: FullCorpus, *, mode: str, pov: str | None) -> NarrativeContextRequest:
    return NarrativeContextRequest(
        user_id=USER,
        project_name=PROJECT,
        canon_branch_id="main",
        canon_version_id="corpus-canon-1",
        plan_id="corpus-plan",
        plan_version=1,
        scene_contract_id="scene-1",
        scene_contract_version=1,
        creative_policy_ref="policy-1",
        creative_policy_version="v1",
        mode=mode,
        pov_subject_entity_id=pov,
        story_time=corpus["story_time"],
        token_budget=500,
        compiler_version="compiler-v1",
        retrieval_snapshot_ref="corpus-snap",
    )


def _corpus_secret_prose(corpus: FullCorpus) -> str:
    return next(c.content for c in corpus["snapshot"].candidates if c.candidate_id == "corpus-secret")


def test_full_corpus_carries_every_required_phenomenon() -> None:
    corpus = full_corpus()
    content = corpus["canon"].content
    assert len(corpus["scenes"]) == 30
    assert sum(1 for e in content.entities_by_id.values() if e.entity_type.value == "CHARACTER") == 8
    assert sum(1 for e in content.entities_by_id.values() if e.entity_type.value == "LOCATION") == 3
    assert sum(1 for p in content.epistemic_propositions_by_ref.values() if p.predicate == "true_name") == 2
    assert sum(1 for s in content.knowledge_states_by_id.values() if s.epistemic_state is ES.FALSE_BELIEF) == 2

    injury = sorted(
        (f for f in content.facts_by_id.values() if f.subject_ref == "char-3" and f.predicate == "condition"),
        key=lambda f: f.fact_id,
    )
    assert [f.value for f in injury] == ["healthy", "injured"]
    assert injury[0].effective_until == injury[1].effective_from  # supersession, no gap or overlap

    crown = sorted(
        (f for f in content.facts_by_id.values() if f.subject_ref == "obj-crown" and f.predicate == "owner"),
        key=lambda f: f.fact_id,
    )
    assert [f.value for f in crown] == ["char-1", "char-2"]

    jump_first, jump_second = corpus["scenes"][10], corpus["scenes"][11]
    assert jump_first.sequence_index < jump_second.sequence_index
    assert jump_first.temporal_window.effective_from > jump_second.temporal_window.effective_from

    evidenced = {ref for s in content.knowledge_states_by_id.values() for ref in s.evidence_event_refs}
    assert "ev-reveal" in content.events_by_id  # unperceived reveal Event
    assert "ev-reveal" not in evidenced  # named by no KnowledgeState's evidence
    assert any(r.relation == "BEFORE" for r in content.temporal_relations_by_id.values())


async def test_full_corpus_compiles_deterministically_in_both_modes_without_leak() -> None:
    corpus = full_corpus()
    secret_prose = _corpus_secret_prose(corpus)

    for mode, pov in (("AUTHOR_DRAFT", None), ("CHARACTER_SIMULATION", "char-6")):
        request = _corpus_request(corpus, mode=mode, pov=pov)
        first = await _corpus_compiler(corpus).compile(request)
        second = await _corpus_compiler(corpus).compile(request)
        assert first.context_pack_id == second.context_pack_id
        assert first.content_hash == second.content_hash

    author_pack = await _corpus_compiler(corpus).compile(_corpus_request(corpus, mode="AUTHOR_DRAFT", pov=None))
    sim_pack = await _corpus_compiler(corpus).compile(
        _corpus_request(corpus, mode="CHARACTER_SIMULATION", pov="char-6")
    )

    assert any("secret" in seg.source_ref for seg in author_pack.retrieved_context)  # author sees the secret
    assert all("secret" not in seg.source_ref for seg in sim_pack.retrieved_context)  # simulation does not
    assert secret_prose not in repr(sim_pack)
    sim_trace = next(t for t in sim_pack.selection_trace if t.candidate_id == "corpus-secret")
    assert sim_trace.reason.value == "NOT_VISIBLE"
    assert sim_trace.content_hash is None
    assert sim_trace.token_count is None
    assert any("visible" in seg.source_ref for seg in sim_pack.retrieved_context)  # char-6's KNOWN fact still lands


# --- Hard-exit invariant: every mutation leaves its contamination counter at 0 ----


async def test_every_mutation_leaves_all_hard_exit_counters_at_zero(session_factory: Factory) -> None:
    counters = dict.fromkeys(
        (
            "canon_contradiction",
            "epistemic_leakage",
            "timeline_violation",
            "rejected_candidate_contamination",
            "failed_transaction_corruption",
            "required_skips",
        ),
        0,
    )
    detail: list[str] = []

    def _rule_probe(label: str, counter: str, triple_builder, rule_id: str) -> None:
        try:
            rules = _rules(*triple_builder())
        except Exception as exc:
            counters["required_skips"] += 1
            detail.append(f"{label}: could not run ({exc!r})")
            return
        if rule_id not in rules:
            counters[counter] += 1
            detail.append(f"{label}: expected {rule_id}, saw {rules}")

    # MUT-01: the clean historical-evidence delta must not raise any ERROR finding.
    clean_base, clean_delta, clean_candidate = known_delta()
    clean = _VALIDATOR.validate_canon(base=clean_base, delta=clean_delta, candidate=clean_candidate)
    if not clean.ok:
        counters["canon_contradiction"] += 1
        detail.append(f"MUT-01: clean delta produced {[f.rule_id for f in clean.findings]}")

    # MUT-02 / 03 / 04: Canon-contradiction mutations.
    _rule_probe("MUT-02", "canon_contradiction", _mut02_triple, "EPI_EVIDENCE_NON_RECIPROCAL_BACKLINK")
    _rule_probe("MUT-04", "canon_contradiction", _mut04_retired_support, "EPI_TRUTH_INCOMPLETE_COVERAGE")
    try:
        base, delta, candidate = known_delta(evidence_event_refs=[], bootstrap_author_decision_ref="decision-unlisted")
        if "EPI_EVIDENCE_BOOTSTRAP_UNBOUND" not in _rules(base, delta, candidate):
            counters["canon_contradiction"] += 1
            detail.append("MUT-03: bootstrap ref not flagged as unbound")
        base, delta, candidate = known_delta(evidence_event_refs=[])
        inv = _rules(base, delta, candidate)
        if "EPI_EVIDENCE_MISSING" not in inv or "EPI_EVIDENCE_BOOTSTRAP_UNBOUND" in inv:
            counters["canon_contradiction"] += 1
            detail.append(f"MUT-03-inverse: validator inferred a bootstrap ({inv})")
    except Exception as exc:
        counters["required_skips"] += 1
        detail.append(f"MUT-03: could not run ({exc!r})")

    # MUT-05 / 06: timeline mutations.
    _rule_probe("MUT-05", "timeline_violation", _mut05_future_evidence, "EPI_EVIDENCE_FUTURE")
    _rule_probe("MUT-06", "timeline_violation", _mut06_duplicate_relation, "TIME_GRAPH_DUPLICATE_NORMALIZED_KEY")

    # MUT-12: two active states must fail the resolver closed, not "latest row wins".
    try:
        EpistemicViewResolver().resolve(canon=_two_active_states_canon(), subject_entity_id="char-a", at=T2)
        counters["canon_contradiction"] += 1
        detail.append("MUT-12: resolver returned a view for two active states")
    except EpistemicIntegrityError:
        pass

    # MUT-07 / 08: compiler visibility leakage + rejected-candidate contamination.
    secret = secret_descriptor(prose="the twist is that char-x is the heir")
    mut07 = await _compiler(retrieval_snapshot((secret, "a completely different body of secret prose"))).compile(
        _acc_request(mode="AUTHOR_DRAFT", pov=None)
    )
    if "twist" in repr(mut07) or "body of secret prose" in repr(mut07):
        counters["epistemic_leakage"] += 1
        detail.append("MUT-07: falsified secret prose reached the pack")
    mut07_trace = next(t for t in mut07.selection_trace if t.candidate_id == "secret")
    if mut07.retrieved_context != () or mut07_trace.content_hash is not None or mut07_trace.token_count is not None:
        counters["rejected_candidate_contamination"] += 1
        detail.append("MUT-07: rejected candidate still contributed a segment or hash")

    mut08 = await _compiler(
        retrieval_snapshot((visible_descriptor(ks_ref="k-does-not-exist", prose="claimed visible"), "claimed visible"))
    ).compile(_acc_request(mode="CHARACTER_SIMULATION", pov="char-a"))
    mut08_trace = next(t for t in mut08.selection_trace if t.candidate_id == "visible")
    if mut08_trace.reason.value != "NOT_VISIBLE" or mut08_trace.content_hash is not None:
        counters["rejected_candidate_contamination"] += 1
        detail.append("MUT-08: unresolved subject-knowledge ref still produced a segment")

    # Corpus character-simulation compile must not carry the author-only secret prose.
    corpus = full_corpus()
    sim_pack = await _corpus_compiler(corpus).compile(
        _corpus_request(corpus, mode="CHARACTER_SIMULATION", pov="char-6")
    )
    if _corpus_secret_prose(corpus) in repr(sim_pack):
        counters["epistemic_leakage"] += 1
        detail.append("corpus: author-only secret reached the character-simulation pack")

    # MUT-09 / 10 / 11: a rejected write must leave persisted plan state untouched.
    async def _plan_versions(service: NarrativePlanService) -> list[int]:
        found: list[int] = []
        for version in (1, 2, 3):
            try:
                found.append(
                    (
                        await service.get_version(plan_id="plan-1", version=version, project_name=PROJECT, user_id=USER)
                    ).version
                )
            except NarrativePlanNotFoundError:
                break
        return found

    # MUT-11 first: a rejected genesis must persist no plan row at all, leaving the
    # DB clean for the MUT-09 / 10 probes that share this session factory.
    pinned = v2_canon_view(version_id="canon-x", content=base_canon_content().model_copy(update={"facts_by_id": {}}))
    invalid_service = _service(
        session_factory, {"canon-x": pinned, "canon-head": v2_canon_view(version_id="canon-head")}
    )
    bad_scene = entry_scene(comparison="PRESENT", value=None)
    mut11 = proposal(revision="rev-11", content=plan_content(scenes=[bad_scene], canon_version_id="canon-x"))
    try:
        await invalid_service.commit_revision(
            proposal=mut11, approval=approval(mut11, approval_ref="ap-11"), project_name=PROJECT, user_id=USER, now=T1
        )
        counters["failed_transaction_corruption"] += 1
        detail.append("MUT-11: invalid entry state was committed")
    except NarrativePlanValidationError:
        pass
    try:
        await invalid_service.get_version(plan_id="plan-1", version=1, project_name=PROJECT, user_id=USER)
        counters["failed_transaction_corruption"] += 1
        detail.append("MUT-11: a plan row was persisted for a rejected genesis")
    except NarrativePlanNotFoundError:
        pass

    service = _service(session_factory)
    genesis = proposal(revision="rev-1")
    await service.commit_revision(
        proposal=genesis,
        approval=approval(genesis, approval_ref="ap-shared"),
        project_name=PROJECT,
        user_id=USER,
        now=T1,
    )
    before = await _plan_versions(service)

    changed = entry_scene(comparison="NOT_EQUALS", value="char-c")
    mut09 = proposal(revision="rev-2", expected_version=1, content=plan_content(scenes=[changed], parent_version=1))
    try:
        await service.commit_revision(
            proposal=mut09, approval=approval(mut09, approval_ref="ap-2"), project_name=PROJECT, user_id=USER, now=T1
        )
        counters["failed_transaction_corruption"] += 1
        detail.append("MUT-09: identity conflict did not raise")
    except NarrativePlanIdentityConflictError:
        pass

    mut10 = proposal(
        revision="rev-3", expected_version=1, content=plan_content(scenes=[entry_scene()], parent_version=1)
    )
    try:
        await service.commit_revision(
            proposal=mut10,
            approval=approval(mut10, approval_ref="ap-shared"),
            project_name=PROJECT,
            user_id=USER,
            now=T1,
        )
        counters["failed_transaction_corruption"] += 1
        detail.append("MUT-10: reused approval ref did not raise")
    except NarrativePlanApprovalError:
        pass

    after = await _plan_versions(service)
    if after != before:
        counters["failed_transaction_corruption"] += 1
        detail.append(f"MUT-09/10: persisted versions changed {before} -> {after}")

    assert counters == dict.fromkeys(counters, 0), detail


_ = (AddEventOperation, UpdateKnowledgeOperation, CanonContent)

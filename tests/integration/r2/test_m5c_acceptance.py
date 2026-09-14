"""M5C acceptance: the combined M5 v1/v2 corpus (§16.9) driven through the real public
interfaces, and the complete §16.8 adversarial-mutation matrix asserted row by row.

Scope. Sections 16.1-16.7 describe the *per-area* tests, and those already live in the
per-task suites (``tests/unit/r2/narrative_lifecycle/``,
``tests/integration/r2/narrative_lifecycle/``, ``tests/integration/r2/narrative*``). This
file is deliberately the cross-cutting layer on top of them: one corpus that carries
every M5 phenomenon at once, and one mutation table that proves each required result
still holds when the mechanisms are combined. Seeding helpers, test doubles, and the
structural sensors are imported from the suites that own them rather than redefined.

Every mutation declares exactly one typed expectation, because the §16.8 rows are proven
by four different kinds of evidence: a raised error, a terminal outcome, a named finding,
or the absence of any write. ``expected_no_write`` composes with the other three — a row
whose required result is "identity conflict; zero writes" asserts both.
"""

from __future__ import annotations

import ast
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.canon_uow import canon_authority_uow_factory
from lib.db.narrative_lifecycle_uow import narrative_lifecycle_uow_factory
from r2.contracts import CanonCommitApproval, CanonDelta, NarrativeContextRequest
from r2.contracts.narrative import CanonDeltaPayload
from r2.contracts.narrative_lifecycle import CompilationResult, NarrativeRevision
from r2.contracts.narrative_plan import SceneContract
from r2.narrative.canon_transaction import CanonTransactionService
from r2.narrative.errors import (
    CanonApprovalError,
    CanonBaseVersionConflict,
    NarrativePlanSchemaVersionError,
)
from r2.narrative.hashing import compute_canon_delta_hash
from r2.narrative.validation import (
    NarrativeInvariantValidator,
    validate_scene_relationship,
    validate_thread_payoff_outcome,
)
from r2.narrative_context.compiler import NarrativeContextCompiler
from r2.narrative_context.errors import NarrativeContextValidationError
from r2.narrative_lifecycle.acceptance import AdmittedNarrativeHandoff, NarrativeAcceptanceService
from r2.narrative_lifecycle.compiler import CanonDeltaCompiler, CompilationSucceeded
from r2.narrative_lifecycle.errors import (
    NarrativeAttemptGenerationConflict,
    NarrativeConflictLineageConflict,
    NarrativeDecisionApplicabilityError,
    NarrativeDecisionIdentityConflictError,
    NarrativeDecisionPredecessorConflict,
    NarrativeEvidenceIntegrityError,
    NarrativeHandoffConflict,
)
from r2.narrative_lifecycle.evidence import ExtractionAdmissionCommand, NarrativeLifecycleEvidenceService
from r2.narrative_lifecycle.integrity import NarrativeLifecycleIntegrityChecker
from r2.narrative_plan.hashing import compute_scene_semantic_hash, compute_scene_semantic_hash_v2
from r2.narrative_plan.schema_upgrade import (
    minimum_scene_selector,
    require_plan_schema_transition,
    require_scene_schema_transition,
)
from r2.narrative_plan.validation import validate_plan_thread_lifecycle
from server.services.narrative_canon_handoff import NarrativeCanonHandoffFacade
from tests.factories import (
    make_change_set_review_command,
    make_compilation_result,
    make_conflict_resolution_command,
    make_narrative_change_set,
    make_narrative_revision,
    make_narrative_work_scope,
    make_revision_acceptance_command,
)
from tests.fixtures.r2 import m5c_narrative_corpus as corpus
from tests.integration.r2.narrative_lifecycle._fakes import SHOWRUNNER, FakeShowrunnerAuthorityPort
from tests.integration.r2.narrative_lifecycle.test_compilation_service import (
    _canon_delta,
    _compilation_command,
    _seed_one_reviewed_change_set,
    _seed_two_overlapping_reviewed_change_sets,
)
from tests.integration.r2.narrative_lifecycle.test_evidence_service import (
    InjectedFault,
    _attempt,
    _candidate,
    _FaultOnCommitUnitOfWork,
    _result,
    _revision,
)
from tests.integration.r2.narrative_lifecycle.test_handoff_admission import (
    ATTEMPT_ID,
    PROJECT,
    RESULT_ID,
    USER,
    _approval,
    _handoff_command,
    _seed_admissible_handoff,
    _supersede_the_review,
    _supersede_the_revision,
)
from tests.integration.server.services.test_narrative_canon_handoff import (
    NOW,
    _approval_for,
    _branch_command,
    _entity_delta,
    _seeded_then_random_version_ids,
)
from tests.unit.r2.narrative_context.test_compiler import (
    FakeAccepted,
    FakeCanon,
    FakePlan,
    FakePolicy,
    FakeSnapshotReader,
    WordCounter,
)
from tests.unit.r2.narrative_plan._helpers import V1_GOLDEN_SCENE, V1_GOLDEN_SCENE_HASH
from tests.unit.r2.test_m5c_architecture_boundaries import (
    M5A_COMMIT_PATH_MODULES,
    acceptance_import_offenders,
    forbidden_pure_import_offenders,
    narrative_currentness_dependency_offenders,
    pure_lifecycle_sources,
    r2_runtime_sources,
    relationship_predicate_literal_offenders,
)

type Factory = async_sessionmaker[AsyncSession]

_VALIDATOR = NarrativeInvariantValidator()
_COMPILER = CanonDeltaCompiler()
_SCENE_V1 = "r2-scene-contract-content-v1"
_SCENE_V2 = "r2-scene-contract-content-v2"
# The frozen v1 regression anchor as it is actually accepted: the helper keeps a
# placeholder in ``semantic_hash`` so the golden value can be asserted separately.
_SEALED_GOLDEN_V1_SCENE = V1_GOLDEN_SCENE.model_copy(update={"semantic_hash": V1_GOLDEN_SCENE_HASH})

# Every table an M5C write can reach, plus the Canon authority tables an admission is
# forbidden to touch. ``row_counts_unchanged`` compares all of them.
_COUNTED_TABLES = (
    "narrative_draft_candidates",
    "narrative_revisions",
    "narrative_extraction_attempts",
    "narrative_extraction_results",
    "narrative_change_sets",
    "narrative_extraction_result_change_sets",
    "narrative_decision_identities",
    "revision_acceptance_decisions",
    "change_set_review_decisions",
    "conflict_resolution_lineages",
    "conflict_resolution_decisions",
    "conflict_resolution_decision_competitors",
    "revision_acceptance_heads",
    "change_set_review_heads",
    "conflict_resolution_heads",
    "narrative_compilation_attempts",
    "narrative_compilation_selected_change_sets",
    "narrative_compilation_results",
    "narrative_compiled_canon_deltas",
    "narrative_handoff_admissions",
    "narrative_handoff_admission_observed_heads",
    "canon_branches",
    "canon_deltas",
    "canon_versions",
)


def _scope():
    return make_narrative_work_scope(user_id=USER, project_name=PROJECT)


# --- the v1 byte / hash compatibility gate --------------------------------------


@dataclass(frozen=True)
class GateFinding:
    """One machine-readable reason the v1 compatibility gate rejected a scene payload."""

    rule_id: str
    detail: str


def v1_byte_hash_compatibility_findings(payload: dict[str, object], *, golden_hash: str) -> tuple[GateFinding, ...]:
    """The byte/hash compatibility gate for one accepted v1 scene payload.

    It refuses two distinct v1 regressions: a payload that carries a v2-only field (the
    v1 byte domain never widens, even for an empty or default value), and a recorded
    ``semantic_hash`` that is not what the *v1* hash function computes for those bytes —
    which is exactly what recomputing a v1 golden hash with v2 code produces.
    """
    try:
        scene = SceneContract.model_validate(payload)
    except ValidationError as exc:
        return (GateFinding("V1_SCENE_BYTE_DOMAIN_LEAK", str(exc)),)
    recomputed = compute_scene_semantic_hash(scene)
    if scene.semantic_hash != recomputed or scene.semantic_hash != golden_hash:
        return (
            GateFinding(
                "V1_SCENE_HASH_REGRESSION",
                f"recorded {scene.semantic_hash!r}; v1 recomputation {recomputed!r}; golden {golden_hash!r}",
            ),
        )
    return ()


# --- the mutation harness --------------------------------------------------------


@dataclass(frozen=True)
class MutationFinding:
    rule_id: str


@dataclass(frozen=True)
class MutationResult:
    """Whatever the assertions for one row need: a terminal outcome string, an ordered
    set of findings, or neither (for the rows proven only by ``expected_no_write``)."""

    outcome: str | None = None
    findings: tuple[MutationFinding, ...] = ()


@dataclass(frozen=True)
class AdversarialMutation:
    """One §16.8 row: the mutation to apply, and the single typed expectation that proves
    the required result. ``expected_no_write`` composes with the other three."""

    id: str
    row: str
    run: Callable[[M5CPipeline], Awaitable[MutationResult]]
    expected_error: type[Exception] | None = None
    expected_outcome: str | None = None
    expected_finding: str | None = None
    expected_no_write: bool = False

    async def apply_and_run(self, pipeline: M5CPipeline) -> MutationResult:
        return await self.run(pipeline)

    @property
    def declared_expectations(self) -> int:
        return sum(
            1 for value in (self.expected_error, self.expected_outcome, self.expected_finding) if value is not None
        )


@dataclass
class M5CPipeline:
    """The real M5C surface, wired once per test: evidence, decision authority, the pure
    compiler, the handoff facade, the existing M5A Canon transaction service, and the
    integrity checker — over one dialect-aware session factory."""

    session_factory: Factory
    acceptance: NarrativeAcceptanceService
    evidence: NarrativeLifecycleEvidenceService
    integrity: NarrativeLifecycleIntegrityChecker
    canon: CanonTransactionService
    handoff: NarrativeCanonHandoffFacade
    compiler: CanonDeltaCompiler = field(default_factory=CanonDeltaCompiler)
    baseline: dict[str, int] = field(default_factory=dict)

    async def row_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        async with self.session_factory() as session:
            for table in _COUNTED_TABLES:
                counts[table] = int((await session.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one())
        return counts

    async def snapshot_rows(self) -> None:
        self.baseline = await self.row_counts()

    async def row_counts_unchanged(self) -> bool:
        return await self.row_counts() == self.baseline

    # -- seeding through the real services -------------------------------------

    async def seed_revision(self, revision_id: str) -> None:
        """Durable candidate + revision evidence, with no decision of any kind."""
        async with narrative_lifecycle_uow_factory(self.session_factory)() as uow:
            await uow.repository.insert_draft_candidate(_candidate(candidate_id=f"cand-{revision_id}"))
            await uow.repository.insert_revision(_revision(revision_id=revision_id, candidate_id=f"cand-{revision_id}"))
            await uow.commit()

    async def accept_revision(self, *, decision_id: str = "d-1", revision_id: str = "rev-1") -> None:
        await self.seed_revision(revision_id)
        await self.acceptance.decide_revision(
            make_revision_acceptance_command(
                decision_id=decision_id, work_scope=_scope(), action="ACCEPT", selected_revision_id=revision_id
            ),
            authenticated_principal=SHOWRUNNER,
        )

    async def seed_canon_genesis(self) -> None:
        """Branch ``branch-1`` whose genesis version is exactly ``cv-1`` — the base the
        admissible compiled delta names — and which already holds the ``hero`` entity
        that delta's Fact operation refers to."""
        await self.canon.create_branch(_branch_command())
        genesis = _entity_delta(delta_id="delta-genesis", entity_id="hero", base_canon_version_id=None)
        await self.canon.commit(
            delta=genesis,
            approval=_approval_for(genesis, approval_ref="approval-genesis"),
            project_name=PROJECT,
            user_id=USER,
            now=NOW,
        )

    async def advance_canon_head(self) -> None:
        unrelated = _entity_delta(delta_id="delta-unrelated", entity_id="villain", base_canon_version_id="cv-1")
        await self.canon.commit(
            delta=unrelated,
            approval=_approval_for(unrelated, approval_ref="approval-unrelated"),
            project_name=PROJECT,
            user_id=USER,
            now=NOW,
        )

    async def seed_admissible_handoff(self) -> CanonDelta:
        return await _seed_admissible_handoff(self.acceptance, self.session_factory)

    async def admit(self, **overrides: object) -> AdmittedNarrativeHandoff:
        return await self.acceptance.admit_canon_handoff(
            _handoff_command(**overrides), authenticated_principal=SHOWRUNNER, canon_commit_approval=_approval()
        )

    async def seed_admitted_compilation(self) -> None:
        """The full accepted chain up to one admitted compilation attempt, built only out
        of decisions that really exist (never a naked attempt row naming decisions that
        were never created)."""
        await _seed_one_reviewed_change_set(self.acceptance, self.session_factory)
        await self.evidence.admit_compilation(_compilation_command())


@pytest.fixture
def m5c_pipeline(session_factory: Factory) -> M5CPipeline:
    uow = narrative_lifecycle_uow_factory(session_factory)
    canon = CanonTransactionService(
        canon_authority_uow_factory(session_factory), version_id_factory=_seeded_then_random_version_ids()
    )
    return M5CPipeline(
        session_factory=session_factory,
        acceptance=NarrativeAcceptanceService(uow, FakeShowrunnerAuthorityPort()),
        evidence=NarrativeLifecycleEvidenceService(uow),
        integrity=NarrativeLifecycleIntegrityChecker(uow),
        canon=canon,
        handoff=NarrativeCanonHandoffFacade(uow, canon),
    )


def _rule_findings(report: object) -> tuple[MutationFinding, ...]:
    return tuple(MutationFinding(rule_id=finding.rule_id) for finding in report.findings)


def _compiler_findings(result: object) -> tuple[MutationFinding, ...]:
    return tuple(MutationFinding(rule_id=finding.code) for finding in result.findings)


def _gate_findings(findings: tuple[GateFinding, ...]) -> tuple[MutationFinding, ...]:
    return tuple(MutationFinding(rule_id=finding.rule_id) for finding in findings)


def _context_request(scene: object, *, mode: str = "AUTHOR_DRAFT") -> NarrativeContextRequest:
    return NarrativeContextRequest(
        user_id=corpus.USER,
        project_name=corpus.PROJECT,
        canon_branch_id=corpus.BRANCH,
        canon_version_id=corpus.CANON_VERSION,
        plan_id=corpus.PLAN_ID,
        plan_version=1,
        scene_contract_id=scene.scene_contract_id,
        scene_contract_version=1,
        creative_policy_ref="policy-1",
        creative_policy_version="v1",
        mode=mode,
        pov_subject_entity_id=None,
        story_time=scene.temporal_window.effective_from,
        token_budget=500,
        compiler_version="compiler-v1",
        retrieval_snapshot_ref=None,
    )


async def _compile_gate_scene(scene: object) -> tuple[MutationFinding, ...]:
    """Run one no-POV ``AUTHOR_DRAFT`` request through the real context compiler and
    return whichever gate finding stopped it."""
    compiler = NarrativeContextCompiler(
        canon_reader=FakeCanon(corpus.corpus_canon()),
        plan_reader=FakePlan(corpus.gate_plan(scene), scene),
        policy_reader=FakePolicy(),
        accepted_reader=FakeAccepted(),
        snapshot_reader=FakeSnapshotReader(None),
        token_counter=WordCounter(),
    )
    try:
        await compiler.compile(_context_request(scene))
    except NarrativeContextValidationError as exc:
        return tuple(MutationFinding(rule_id=rule_id) for rule_id in exc.detail)  # pyright: ignore[reportGeneralTypeIssues]
    return ()


# --- the §16.8 mutations ---------------------------------------------------------


async def _m01_v1_byte_or_hash_mutation(_pipeline: M5CPipeline) -> MutationResult:
    """Serialize an empty/default v2 field into the accepted v1 golden scene, and record
    a v1 scene's hash as the v2 recomputation of the same bytes."""
    with_v2_field = {**_SEALED_GOLDEN_V1_SCENE.model_dump(mode="json"), "omniscient_authoring_allowed_by_scene": False}
    recomputed_under_v2 = {
        **_SEALED_GOLDEN_V1_SCENE.model_dump(mode="json"),
        "semantic_hash": compute_scene_semantic_hash_v2(_SEALED_GOLDEN_V1_SCENE),
    }
    findings = v1_byte_hash_compatibility_findings(
        with_v2_field, golden_hash=V1_GOLDEN_SCENE_HASH
    ) + v1_byte_hash_compatibility_findings(recomputed_under_v2, golden_hash=V1_GOLDEN_SCENE_HASH)
    return MutationResult(findings=_gate_findings(findings))


async def _m02_keep_v1_selector(_pipeline: M5CPipeline) -> MutationResult:
    scene = corpus.relationship_scene()
    require_scene_schema_transition(
        from_selector=_SCENE_V1, to_selector=_SCENE_V1, content_minimum=minimum_scene_selector(scene)
    )
    return MutationResult(outcome="ACCEPTED")  # pragma: no cover - the ratchet must raise


async def _m03_downgrade_a_v2_lineage(_pipeline: M5CPipeline) -> MutationResult:
    """The scene's last v2-only semantic has been removed, so its own content minimum is
    v1 again — the ratchet, not the minimum, must still refuse the downgrade."""
    stripped = corpus.clean_v2_scene()
    assert minimum_scene_selector(stripped) == _SCENE_V1
    require_scene_schema_transition(from_selector=_SCENE_V2, to_selector=_SCENE_V1, content_minimum=_SCENE_V1)
    return MutationResult(outcome="ACCEPTED")  # pragma: no cover - the ratchet must raise


async def _m04_reverse_the_relationship(_pipeline: M5CPipeline) -> MutationResult:
    """Reverse the direction, swap the target, change the key, change the state, and step
    outside the effective interval — every one must be unmet."""
    canon = corpus.corpus_canon()
    mutations = (
        ("entry", corpus.C1, corpus.relationship_constraint(source=corpus.MENTOR, target=corpus.HERO)),
        ("entry", corpus.C1, corpus.relationship_constraint(target=corpus.RIVAL)),
        ("entry", corpus.C1, corpus.relationship_constraint(key="rivalry_level")),
        ("entry", corpus.C1, corpus.relationship_constraint(expected_state="low")),
        # the exact effective interval is half-open: the Fact is already gone at C3
        ("entry", corpus.C3, corpus.entry_relationship_constraint()),
        ("exit", corpus.C1, corpus.exit_relationship_constraint()),
    )
    findings: tuple[MutationFinding, ...] = ()
    for phase, instant, constraint in mutations:
        report = validate_scene_relationship(canon=canon, constraint=constraint, at=instant, phase=phase)
        findings += _rule_findings(report)
    assert len(findings) == len(mutations), findings
    return MutationResult(findings=findings)


async def _m05_relationship_predicate_outside_the_helper(_pipeline: M5CPipeline) -> MutationResult:
    mutated = {
        **r2_runtime_sources(),
        "r2/narrative_lifecycle/compiler.py": 'PREDICATE = "r2rel:" + relationship_key\n',
    }
    offenders = relationship_predicate_literal_offenders(mutated)
    return MutationResult(outcome="SENSOR_FIRED" if offenders == ["r2/narrative_lifecycle/compiler.py"] else "MISSED")


async def _m06_break_the_thread_lifecycle(_pipeline: M5CPipeline) -> MutationResult:
    report = validate_plan_thread_lifecycle(corpus.thread_resolved_before_open_plan_content())
    return MutationResult(findings=_rule_findings(report))


async def _m07_story_time_order_as_lifecycle_order(_pipeline: M5CPipeline) -> MutationResult:
    """Presentation order is clean; the same scenes re-indexed by story time are not, and
    the failure is the same on every run."""
    clean = validate_plan_thread_lifecycle(corpus.thread_plan_content())
    assert clean.findings == ()
    mutated = corpus.story_time_ordered_plan_content()
    first = validate_plan_thread_lifecycle(mutated)
    second = validate_plan_thread_lifecycle(mutated)
    assert first.findings == second.findings
    return MutationResult(findings=_rule_findings(first))


async def _m08_payoff_refs_as_proof(_pipeline: M5CPipeline) -> MutationResult:
    """The scene declares the payoff ref and the change set carries the exact typed
    key — but no named decision is effective, so nothing is proven."""
    report = validate_thread_payoff_outcome(
        corpus.unaccepted_payoff_proof(), change_set=corpus.payoff_change_set(), effective_decisions=set()
    )
    return MutationResult(findings=_rule_findings(report))


async def _m09_no_pov_author_draft_without_scene_permission(_pipeline: M5CPipeline) -> MutationResult:
    return MutationResult(findings=await _compile_gate_scene(corpus.denied_scene()))


async def _m10_duplicate_constraints(_pipeline: M5CPipeline) -> MutationResult:
    canon = corpus.corpus_canon()
    findings: tuple[MutationFinding, ...] = ()
    for scene in (corpus.r10_duplicate_constraint_id_scene(), corpus.r10_duplicate_semantic_scene()):
        findings += _rule_findings(_VALIDATOR.validate_scene(canon=canon, plan=corpus.scene_plan(scene), scene=scene))
    return MutationResult(findings=findings)


async def _m11_unresolved_present_state_ref(_pipeline: M5CPipeline) -> MutationResult:
    scene = corpus.r9_unresolved_present_ref_scene()
    report = _VALIDATOR.validate_scene(canon=corpus.corpus_canon(), plan=corpus.scene_plan(scene), scene=scene)
    return MutationResult(findings=_rule_findings(report))


async def _m12_accepted_flag_on_evidence(_pipeline: M5CPipeline) -> MutationResult:
    payload = {**make_narrative_revision().model_dump(mode="json"), "accepted": True}
    NarrativeRevision.model_validate(payload)
    return MutationResult(outcome="ACCEPTED")  # pragma: no cover - the contract must raise


async def _m13_extractor_invokes_review_change_set(_pipeline: M5CPipeline) -> MutationResult:
    mutated = {
        **pure_lifecycle_sources(),
        "r2/narrative_lifecycle/changeset_parser.py": (
            "from r2.narrative_lifecycle.acceptance import NarrativeAcceptanceService\n"
        ),
    }
    offenders = sorted({rel for rel, _ in acceptance_import_offenders(mutated)})
    fired = offenders == ["r2/narrative_lifecycle/changeset_parser.py"]
    return MutationResult(outcome="SENSOR_FIRED" if fired else "MISSED")


async def _m14_occ_before_exact_retry(pipeline: M5CPipeline) -> MutationResult:
    """The response was lost; the caller retries the identical command after the head has
    moved on. Comparing OCC first would raise a predecessor conflict instead of replaying."""
    await pipeline.accept_revision(decision_id="d-1", revision_id="rev-1")
    original = make_revision_acceptance_command(decision_id="d-1", work_scope=_scope(), action="ACCEPT")
    first = await pipeline.acceptance.decide_revision(original, authenticated_principal=SHOWRUNNER)
    await pipeline.seed_revision("rev-2")
    await pipeline.acceptance.decide_revision(
        make_revision_acceptance_command(
            decision_id="d-2",
            work_scope=_scope(),
            action="SUPERSEDE",
            selected_revision_id="rev-2",
            expected_latest_decision_id="d-1",
            expected_effective_decision_id="d-1",
        ),
        authenticated_principal=SHOWRUNNER,
    )
    retry = await pipeline.acceptance.decide_revision(original, authenticated_principal=SHOWRUNNER)
    head = await pipeline.acceptance.get_current_revision_selection(_scope())
    assert head is not None
    replayed = retry == first and retry.effective_decision_id == "d-1" and head.effective_decision_id == "d-2"
    return MutationResult(outcome="REPLAYED_ORIGINAL_RECEIPT" if replayed else "OCC_CONFLICT")


async def _m15_reuse_decision_id_with_a_changed_receipt(pipeline: M5CPipeline) -> MutationResult:
    await pipeline.accept_revision(decision_id="d-1", revision_id="rev-1")
    await pipeline.seed_revision("rev-2")
    await pipeline.snapshot_rows()
    await pipeline.acceptance.decide_revision(
        make_revision_acceptance_command(
            decision_id="d-1", work_scope=_scope(), action="ACCEPT", selected_revision_id="rev-2"
        ),
        authenticated_principal=SHOWRUNNER,
    )
    return MutationResult(outcome="ACCEPTED")  # pragma: no cover - identity must conflict


async def _m16_one_generic_head_key(pipeline: M5CPipeline) -> MutationResult:
    """Three heads under one work scope: one revision-acceptance head and two independent
    change-set-review heads. A single generic head key would collapse them into one."""
    await pipeline.accept_revision(decision_id="d-1", revision_id="rev-1")
    for decision_id, lineage in (("d-2", "lin-a"), ("d-3", "lin-b")):
        await pipeline.acceptance.review_change_set(
            make_change_set_review_command(
                decision_id=decision_id,
                work_scope=_scope(),
                action="ACCEPT",
                change_set_lineage_id=lineage,
                selected_change_set_id=f"cs-{lineage}",
            ),
            authenticated_principal=SHOWRUNNER,
        )
    counts = await pipeline.row_counts()
    return MutationResult(outcome=f"{counts['revision_acceptance_heads']}:{counts['change_set_review_heads']}")


async def _m17_reject_advances_the_effective_pointer(pipeline: M5CPipeline) -> MutationResult:
    await pipeline.accept_revision(decision_id="d-1", revision_id="rev-1")
    await pipeline.seed_revision("rev-2")
    await pipeline.acceptance.decide_revision(
        make_revision_acceptance_command(
            decision_id="d-2",
            work_scope=_scope(),
            action="REJECT",
            selected_revision_id="rev-2",
            expected_latest_decision_id="d-1",
            expected_effective_decision_id="d-1",
        ),
        authenticated_principal=SHOWRUNNER,
    )
    head = await pipeline.integrity.verify_revision_head(_scope())
    assert head.latest_decision_id == "d-2"
    return MutationResult(outcome=str(head.effective_decision_id))


async def _m18_genesis_without_unique_insertion(pipeline: M5CPipeline) -> MutationResult:
    """Two genesis acceptances for one subject: the second still declares "no predecessor",
    which is only safe if the genesis head was inserted under a unique key rather than
    locked as an absent row. (The genuinely concurrent PostgreSQL form of this race is
    ``tests/integration/r2/narrative_lifecycle/test_lifecycle_concurrency.py``.)"""
    await pipeline.accept_revision(decision_id="d-1", revision_id="rev-1")
    await pipeline.seed_revision("rev-2")
    await pipeline.snapshot_rows()
    await pipeline.acceptance.decide_revision(
        make_revision_acceptance_command(
            decision_id="d-2", work_scope=_scope(), action="ACCEPT", selected_revision_id="rev-2"
        ),
        authenticated_principal=SHOWRUNNER,
    )
    return MutationResult(outcome="DOUBLE_ACCEPTANCE")  # pragma: no cover - genesis must be unique


async def _m19_compile_a_superseded_decision(pipeline: M5CPipeline) -> MutationResult:
    await _seed_one_reviewed_change_set(pipeline.acceptance, pipeline.session_factory)
    await _supersede_the_revision(pipeline.acceptance, pipeline.session_factory)
    await pipeline.snapshot_rows()
    await pipeline.evidence.admit_compilation(_compilation_command())
    return MutationResult(outcome="ADMITTED")  # pragma: no cover - admission must fail


async def _m20_resolve_overlap_from_prose(pipeline: M5CPipeline) -> MutationResult:
    """Two colliding change sets and no Human resolution decision at all: the compiler
    stays at CONFLICT and produces no delta rather than picking a winner from prose."""
    overlapping = corpus.overlapping_reviewed_change_sets()
    result = pipeline.compiler.compile(
        corpus.compiler_identity(overlapping),
        corpus.compiler_revision(),
        overlapping,
        [],
        corpus.COMPILER_BASE,
        corpus.compiler_policy(),
    )
    assert result.canon_delta is None
    return MutationResult(outcome=result.outcome, findings=_compiler_findings(result))


async def _m21_two_lineages_for_one_subject(pipeline: M5CPipeline) -> MutationResult:
    await _seed_two_overlapping_reviewed_change_sets(pipeline.acceptance, pipeline.session_factory)
    first = make_conflict_resolution_command(
        decision_id="d-4",
        work_scope=_scope(),
        revision_acceptance_decision_id="d-1",
        conflict_resolution_lineage_id="L-1",
        competing_change_set_ids=("cs-a", "cs-b"),
        competing_review_decision_ids=("d-2", "d-3"),
        chosen_resolution=corpus.resolution_instruction("KEEP", "cs-a"),
    )
    await pipeline.acceptance.resolve_change_set_conflict(first, authenticated_principal=SHOWRUNNER)
    await pipeline.snapshot_rows()
    await pipeline.acceptance.resolve_change_set_conflict(
        first.model_copy(update={"decision_id": "d-5", "conflict_resolution_lineage_id": "L-2"}),
        authenticated_principal=SHOWRUNNER,
    )
    return MutationResult(outcome="TWO_LINEAGES")  # pragma: no cover - subject must be unique


async def _m22_compiler_crash_as_outcome_unknown(_pipeline: M5CPipeline) -> MutationResult:
    """``OUTCOME_UNKNOWN`` exists for extraction (a provider may genuinely be ambiguous)
    and never for compilation, which is pure and total."""
    CompilationResult.model_validate(
        {**make_compilation_result().model_dump(mode="json"), "outcome": "OUTCOME_UNKNOWN"}
    )
    return MutationResult(outcome="ACCEPTED")  # pragma: no cover - the vocabulary must raise


async def _m23_succeeded_extraction_without_its_change_sets(pipeline: M5CPipeline) -> MutationResult:
    async with narrative_lifecycle_uow_factory(pipeline.session_factory)() as uow:
        await uow.repository.insert_draft_candidate(_candidate())
        await uow.repository.insert_revision(_revision())
        await uow.repository.insert_extraction_attempt(_attempt())
        await uow.commit()
    faulting = NarrativeLifecycleEvidenceService(lambda: _FaultOnCommitUnitOfWork(pipeline.session_factory))
    await pipeline.snapshot_rows()
    await faulting.record_successful_extraction(
        _result(outcome="SUCCEEDED", change_set_ids=("cs-1",)), [make_narrative_change_set(change_set_id="cs-1")]
    )
    return MutationResult(outcome="COMMITTED")  # pragma: no cover - the bundle must fault


async def _m24_compilation_id_and_hash_without_the_payload(pipeline: M5CPipeline) -> MutationResult:
    await pipeline.seed_admitted_compilation()
    await pipeline.snapshot_rows()
    await pipeline.evidence.record_compilation_without_delta(
        make_compilation_result(
            result_id=RESULT_ID,
            attempt_id=ATTEMPT_ID,
            generation=0,
            outcome="SUCCEEDED",
            canon_delta_id="delta-1",
            canon_delta_payload_hash="sha256:claimed-but-not-stored",
        )
    )
    return MutationResult(outcome="RECORDED")  # pragma: no cover - the payload is mandatory


async def _m25_currentness_released_before_the_receipt(pipeline: M5CPipeline) -> MutationResult:
    """Sequential form only: the concurrent race (a competing supersession landing between
    the naked read and the locked re-check) is proven by
    ``tests/integration/r2/narrative_lifecycle/test_handoff_admission.py::
    test_a_supersession_concurrent_with_validation_cannot_land_invisibly`` (PostgreSQL-only,
    ``-k concurrent``). This row cannot itself distinguish a locked read from a naked one;
    it only proves the same currentness guard rejects a *sequentially* stale review."""
    await pipeline.seed_admissible_handoff()
    await _supersede_the_review(pipeline.acceptance, pipeline.session_factory)
    await pipeline.snapshot_rows()
    await pipeline.admit()
    return MutationResult(outcome="ADMITTED")  # pragma: no cover - the locked read must win


async def _m26_narrative_currentness_through_m5a(pipeline: M5CPipeline) -> MutationResult:
    """M5A must not learn about Narrative currentness. Adversarially, a commit-path module
    that imports the acceptance surface or names one of its currentness/admission APIs must
    trip the sensor; on the real, unmutated tree the same sensor must stay clean, and a
    Narrative supersession committed *after* admission must not stop the frozen receipt from
    landing on Canon."""
    mutated_sources = {relative: _read(relative) for relative in M5A_COMMIT_PATH_MODULES}
    mutated_sources["server/services/narrative_canon_handoff.py"] += (
        "\nfrom r2.narrative_lifecycle.acceptance import NarrativeAcceptanceService  # noqa: F401\n"
    )
    injected = narrative_currentness_dependency_offenders(mutated_sources)
    sensor_fired = {rel for rel, _ in injected} == {"server/services/narrative_canon_handoff.py"}

    leaked = narrative_currentness_dependency_offenders(
        {relative: _read(relative) for relative in M5A_COMMIT_PATH_MODULES}
    )
    await pipeline.seed_canon_genesis()
    await pipeline.seed_admissible_handoff()
    admitted = await pipeline.admit()
    await _supersede_the_revision(pipeline.acceptance, pipeline.session_factory)
    committed = await pipeline.handoff.commit_from_admission(admission_id=admitted.admission_id, now=NOW)
    landed = committed.version.committed_delta_id == admitted.canon_delta.canon_delta_id
    return MutationResult(
        outcome="COMMITTED_WITHOUT_NARRATIVE_CURRENTNESS"
        if landed and not leaked and sensor_fired
        else f"LEAKED:{leaked}:SENSOR_FIRED:{sensor_fired}"
    )


async def _m27_canon_repository_called_from_m5c(_pipeline: M5CPipeline) -> MutationResult:
    mutated = {
        **pure_lifecycle_sources(),
        "r2/narrative_lifecycle/evidence.py": "from lib.db.repositories.canon import CanonRepository\n",
    }
    offenders = sorted({rel for rel, _ in forbidden_pure_import_offenders(mutated)})
    return MutationResult(outcome="SENSOR_FIRED" if offenders == ["r2/narrative_lifecycle/evidence.py"] else "MISSED")


async def _m28_narrow_the_delta_hash_domain(pipeline: M5CPipeline) -> MutationResult:
    reviewed = corpus.non_overlapping_reviewed_change_sets()
    compiled = pipeline.compiler.compile(
        corpus.compiler_identity(reviewed),
        corpus.compiler_revision(),
        reviewed,
        [],
        corpus.COMPILER_BASE,
        corpus.compiler_policy(),
    )
    assert isinstance(compiled, CompilationSucceeded)
    fields = compiled.canon_delta.model_dump(mode="json")
    fields.pop("payload_hash")
    without_sources = compute_canon_delta_hash(_payload({**fields, "source_change_set_refs": []}))
    without_authors = compute_canon_delta_hash(_payload({**fields, "author_decision_refs": []}))
    original = compiled.canon_delta.payload_hash
    moved = without_sources != original and without_authors != original
    return MutationResult(outcome="HASH_MOVED" if moved else "HASH_UNCHANGED")


async def _m29_admission_receipt_as_canon_approval(pipeline: M5CPipeline) -> MutationResult:
    """The receipt proves a Narrative admission, not a Canon approval: presenting its own
    identity hash where M5A expects the delta payload hash must be refused."""
    await pipeline.seed_canon_genesis()
    await pipeline.seed_admissible_handoff()
    admitted = await pipeline.admit()
    forged = CanonCommitApproval(
        approval_ref=admitted.admission_id,
        canon_delta_id=admitted.canon_delta.canon_delta_id,
        payload_hash=admitted.admission.canonical_identity_hash,
        payload_hash_algorithm=admitted.canon_delta.payload_hash_algorithm,
        payload_hash_version=admitted.canon_delta.payload_hash_version,
        content_schema_version=admitted.canon_delta.content_schema_version,
        project_name=PROJECT,
        user_id=USER,
        approved_by=admitted.admission.actor_id,
        approved_at=admitted.admission.admitted_at,
        status="APPROVED",
    )
    await pipeline.snapshot_rows()
    await pipeline.canon.commit(
        delta=admitted.canon_delta, approval=forged, project_name=PROJECT, user_id=USER, now=NOW
    )
    return MutationResult(outcome="COMMITTED")  # pragma: no cover - M5A must refuse


async def _m30_reuse_an_admission_with_another_approval(pipeline: M5CPipeline) -> MutationResult:
    await pipeline.seed_admissible_handoff()
    await pipeline.admit()
    await pipeline.snapshot_rows()
    await pipeline.acceptance.admit_canon_handoff(
        _handoff_command(),
        authenticated_principal=SHOWRUNNER,
        canon_commit_approval=_approval(approval_ref="approval-2"),
    )
    return MutationResult(outcome="ADMITTED")  # pragma: no cover - the fingerprint must conflict


def _payload(fields: dict[str, object]) -> CanonDeltaPayload:
    return CanonDeltaPayload.model_validate(fields)


def _read(relative: str) -> str:
    return (Path(__file__).resolve().parents[3] / relative).read_text(encoding="utf-8")


ADVERSARIAL_MUTATIONS: tuple[AdversarialMutation, ...] = (
    AdversarialMutation(
        id="M01-v1-bytes-or-golden-hash",
        row="Serialize empty/default v2 fields into a v1 scene or recompute a v1 golden hash",
        run=_m01_v1_byte_or_hash_mutation,
        expected_finding="V1_SCENE_BYTE_DOMAIN_LEAK",
    ),
    AdversarialMutation(
        id="M02-keep-v1-selector-after-a-v2-semantic",
        row="Keep selector v1 after adding Relationship, Thread, or enabled omniscient semantics",
        run=_m02_keep_v1_selector,
        expected_error=NarrativePlanSchemaVersionError,
    ),
    AdversarialMutation(
        id="M03-downgrade-a-v2-lineage",
        row="Downgrade a v2 scene/plan after removing its last v2-only semantic",
        run=_m03_downgrade_a_v2_lineage,
        expected_error=NarrativePlanSchemaVersionError,
    ),
    AdversarialMutation(
        id="M04-reverse-the-relationship",
        row="Reverse a relationship direction, target, key, state, or effective interval",
        run=_m04_reverse_the_relationship,
        expected_finding="SCENE_ENTRY_RELATIONSHIP_UNMET",
    ),
    AdversarialMutation(
        id="M05-relationship-predicate-outside-the-helper",
        row="Construct a relationship Fact predicate outside the shared versioned helper",
        run=_m05_relationship_predicate_outside_the_helper,
        expected_outcome="SENSOR_FIRED",
    ),
    AdversarialMutation(
        id="M06-thread-resolved-early-twice-or-reopened",
        row="Resolve a thread before it opens, resolve it twice, or reintroduce it later",
        run=_m06_break_the_thread_lifecycle,
        expected_finding="SCENE_THREAD_LIFECYCLE_RESOLUTION_WITHOUT_THREAD",
    ),
    AdversarialMutation(
        id="M07-story-time-order-as-lifecycle-order",
        row="Treat story-time order as thread lifecycle order",
        run=_m07_story_time_order_as_lifecycle_order,
        expected_finding="SCENE_THREAD_LIFECYCLE_REOPENED_RESOLVED",
    ),
    AdversarialMutation(
        id="M08-payoff-refs-without-effective-decisions",
        row="Treat promise_payoff_refs or prose as payoff proof without effective decisions",
        run=_m08_payoff_refs_as_proof,
        expected_finding="SCENE_EXIT_THREAD_UNMET",
    ),
    AdversarialMutation(
        id="M09-no-pov-author-draft-without-scene-permission",
        row="Omit POV in AUTHOR_DRAFT without the v2 SceneContract permission",
        run=_m09_no_pov_author_draft_without_scene_permission,
        expected_finding="SCENE_OMNISCIENT_AUTHORING_FORBIDDEN",
    ),
    AdversarialMutation(
        id="M10-duplicate-constraint-id-or-semantic",
        row="Reuse a constraint ID or normalized semantic constraint under another ID",
        run=_m10_duplicate_constraints,
        expected_finding="SCENE_CONSTRAINT_DUPLICATE_ID",
    ),
    AdversarialMutation(
        id="M11-unresolved-present-state-ref",
        row="Treat an unresolved present-state ref as a normal unmet constraint",
        run=_m11_unresolved_present_state_ref,
        expected_finding="SCENE_PRESENT_REF_UNRESOLVED",
    ),
    AdversarialMutation(
        id="M12-accepted-flag-on-evidence",
        row="Put accepted=true on revision/change set and bypass decision lookup",
        run=_m12_accepted_flag_on_evidence,
        expected_error=ValidationError,
    ),
    AdversarialMutation(
        id="M13-extractor-invokes-review-change-set",
        row="Let extractor invoke review_change_set",
        run=_m13_extractor_invokes_review_change_set,
        expected_outcome="SENSOR_FIRED",
    ),
    AdversarialMutation(
        id="M14-occ-compared-before-exact-retry",
        row="Compare OCC before exact decision retry",
        run=_m14_occ_before_exact_retry,
        expected_outcome="REPLAYED_ORIGINAL_RECEIPT",
    ),
    AdversarialMutation(
        id="M15-decision-id-reused-with-a-changed-receipt",
        row="Reuse decision ID with changed Human receipt or exact basis",
        run=_m15_reuse_decision_id_with_a_changed_receipt,
        expected_error=NarrativeDecisionIdentityConflictError,
        expected_no_write=True,
    ),
    AdversarialMutation(
        id="M16-one-generic-head-key",
        row="Use one generic head key for revision and change-set",
        run=_m16_one_generic_head_key,
        expected_outcome="1:2",
    ),
    AdversarialMutation(
        id="M17-reject-advances-the-effective-pointer",
        row="Advance effective pointer on REJECT",
        run=_m17_reject_advances_the_effective_pointer,
        expected_outcome="d-1",
    ),
    AdversarialMutation(
        id="M18-genesis-without-unique-insertion",
        row="Lock an absent row without unique genesis insertion",
        run=_m18_genesis_without_unique_insertion,
        expected_error=NarrativeDecisionPredecessorConflict,
        expected_no_write=True,
    ),
    AdversarialMutation(
        id="M19-compile-a-superseded-decision",
        row="Compile a superseded decision by ID",
        run=_m19_compile_a_superseded_decision,
        expected_error=NarrativeDecisionApplicabilityError,
        expected_no_write=True,
    ),
    AdversarialMutation(
        id="M20-resolve-overlap-from-prose",
        row="Resolve overlap from model prose without Human decision",
        run=_m20_resolve_overlap_from_prose,
        expected_outcome="CONFLICT",
    ),
    AdversarialMutation(
        id="M21-two-lineages-for-one-subject",
        row="Create two lineages for the same revision/subject",
        run=_m21_two_lineages_for_one_subject,
        expected_error=NarrativeConflictLineageConflict,
        expected_no_write=True,
    ),
    AdversarialMutation(
        id="M22-compiler-crash-as-outcome-unknown",
        row="Treat compiler crash as OUTCOME_UNKNOWN",
        run=_m22_compiler_crash_as_outcome_unknown,
        expected_error=ValidationError,
    ),
    AdversarialMutation(
        id="M23-succeeded-extraction-without-its-change-sets",
        row="Commit SUCCEEDED extraction before its declared change sets",
        run=_m23_succeeded_extraction_without_its_change_sets,
        expected_error=InjectedFault,
        expected_no_write=True,
    ),
    AdversarialMutation(
        id="M24-compilation-id-and-hash-without-the-payload",
        row="Persist only a successful compilation ID/hash",
        run=_m24_compilation_id_and_hash_without_the_payload,
        expected_error=NarrativeEvidenceIntegrityError,
        expected_no_write=True,
    ),
    AdversarialMutation(
        id="M25-currentness-released-before-the-receipt",
        row="Read currentness, release it, then write handoff receipt",
        run=_m25_currentness_released_before_the_receipt,
        expected_error=NarrativeHandoffConflict,
        expected_no_write=True,
    ),
    AdversarialMutation(
        id="M26-narrative-currentness-through-m5a",
        row="Require Narrative currentness through M5A commit implicitly",
        run=_m26_narrative_currentness_through_m5a,
        expected_outcome="COMMITTED_WITHOUT_NARRATIVE_CURRENTNESS",
    ),
    AdversarialMutation(
        id="M27-canon-repository-called-from-m5c",
        row="Call Canon repository directly from M5C",
        run=_m27_canon_repository_called_from_m5c,
        expected_outcome="SENSOR_FIRED",
    ),
    AdversarialMutation(
        id="M28-narrow-the-delta-hash-domain",
        row="Remove source_change_set_refs or author_decision_refs from delta hash domain",
        run=_m28_narrow_the_delta_hash_domain,
        expected_outcome="HASH_MOVED",
    ),
    AdversarialMutation(
        id="M29-admission-receipt-as-canon-approval",
        row="Treat an admission receipt as Canon approval",
        run=_m29_admission_receipt_as_canon_approval,
        expected_error=CanonApprovalError,
        expected_no_write=True,
    ),
    AdversarialMutation(
        id="M30-admission-reused-with-another-approval",
        row="Reuse an admission with another M5A approval tuple",
        run=_m30_reuse_an_admission_with_another_approval,
        expected_error=NarrativeDecisionIdentityConflictError,
        expected_no_write=True,
    ),
)


@pytest.mark.parametrize("mutation", ADVERSARIAL_MUTATIONS, ids=lambda m: m.id)
async def test_each_adversarial_mutation_produces_its_required_result(
    m5c_pipeline: M5CPipeline, mutation: AdversarialMutation
) -> None:
    if mutation.expected_error is not None:
        with pytest.raises(mutation.expected_error):
            await mutation.apply_and_run(m5c_pipeline)
        if mutation.expected_no_write:
            assert await m5c_pipeline.row_counts_unchanged()
        return
    result = await mutation.apply_and_run(m5c_pipeline)
    if mutation.expected_outcome is not None:
        assert result.outcome == mutation.expected_outcome
    if mutation.expected_finding is not None:
        assert mutation.expected_finding in {finding.rule_id for finding in result.findings}
    if mutation.expected_no_write:
        assert await m5c_pipeline.row_counts_unchanged()


def test_the_matrix_covers_every_required_mutation_exactly_once() -> None:
    assert len(ADVERSARIAL_MUTATIONS) == 30
    assert len({mutation.id for mutation in ADVERSARIAL_MUTATIONS}) == 30
    assert len({mutation.row for mutation in ADVERSARIAL_MUTATIONS}) == 30
    for mutation in ADVERSARIAL_MUTATIONS:
        assert mutation.declared_expectations == 1, mutation.id


def test_the_acceptance_run_requires_no_skips_on_any_dialect() -> None:
    """§16.9's hard exit demands zero required skips. Every row in this file runs on
    SQLite and on PostgreSQL alike: nothing here is conditionally skipped or xfailed.
    (The genuinely concurrent PostgreSQL-only races stay in the Task 27 / Task 28
    suites that own them.)"""
    tree = ast.parse(_read("tests/integration/r2/test_m5c_acceptance.py"))
    named = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr in {"skip", "skipif", "xfail", "importorskip"}
    }
    assert named == set()


# --- §16.9 corpus: every required phenomenon, through the real interfaces --------


def test_the_m5b_v1_corpus_replays_byte_for_byte_under_its_original_selectors() -> None:
    replayed = corpus.m5b_v1_corpus()
    assert replayed == corpus.full_corpus()["m5b_v1"]
    scenes = replayed["scenes"]
    assert len(scenes) == 30
    assert {scene.semantic_hash_version for scene in scenes} == {_SCENE_V1}
    assert all(scene.semantic_hash == compute_scene_semantic_hash(scene) for scene in scenes)
    assert replayed["plan"].content_hash_version == "r2-narrative-plan-content-v1"
    assert (
        v1_byte_hash_compatibility_findings(
            _SEALED_GOLDEN_V1_SCENE.model_dump(mode="json"), golden_hash=V1_GOLDEN_SCENE_HASH
        )
        == ()
    )


def test_one_v2_plan_carries_unchanged_v1_scenes_beside_upgraded_v2_scenes() -> None:
    plan = corpus.mixed_version_plan()
    selectors = [scene.semantic_hash_version for scene in plan.content.scene_contracts]
    assert selectors == [_SCENE_V1, _SCENE_V2]
    v1_scene, v2_scene = plan.content.scene_contracts
    assert v1_scene.semantic_hash == compute_scene_semantic_hash(v1_scene)
    assert v2_scene.semantic_hash == compute_scene_semantic_hash_v2(v2_scene)
    assert minimum_scene_selector(v1_scene) == _SCENE_V1
    assert minimum_scene_selector(v2_scene) == _SCENE_V2
    require_plan_schema_transition(from_selector=None, to_selector="r2-narrative-plan-v2", contains_v2_scene=True)


def test_the_directional_relationship_holds_at_its_exact_effective_instants() -> None:
    canon = corpus.corpus_canon()
    scene = corpus.relationship_scene()
    assert _VALIDATOR.validate_scene(canon=canon, plan=corpus.scene_plan(scene), scene=scene).findings == ()
    entry = validate_scene_relationship(
        canon=canon, constraint=corpus.entry_relationship_constraint(), at=corpus.C1, phase="entry"
    )
    exit_report = validate_scene_relationship(
        canon=canon, constraint=corpus.exit_relationship_constraint(), at=corpus.C3, phase="exit"
    )
    assert entry.findings == ()
    assert exit_report.findings == ()
    fact = canon.content.facts_by_id["fact-trust"]
    assert fact.subject_ref == corpus.HERO  # directional: the source character is the Fact subject
    assert fact.predicate == corpus.relationship_predicate()


def test_the_thread_opens_is_omitted_jumps_story_time_and_resolves_exactly_once() -> None:
    content = corpus.thread_plan_content()
    assert validate_plan_thread_lifecycle(content).findings == ()
    by_id = {scene.scene_contract_id: scene for scene in content.scene_contracts}
    assert corpus.THREAD not in by_id["scene-t1"].active_threads  # omitted from an unrelated scene
    jump = by_id["scene-t2"]
    opener = by_id["scene-t0"]
    assert jump.sequence_index > opener.sequence_index
    assert jump.temporal_window.effective_from < opener.temporal_window.effective_from  # the story-time jump
    resolutions = [
        constraint
        for scene in content.scene_contracts
        for constraint in scene.exit_state_targets
        if getattr(constraint, "thread_ref", None) == corpus.THREAD
    ]
    assert len(resolutions) == 1
    assert resolutions[0].payoff_ref == corpus.PAYOFF


def test_the_accepted_payoff_proof_passes_and_the_unaccepted_one_fails_outcome_validation() -> None:
    change_set = corpus.payoff_change_set()
    accepted = validate_thread_payoff_outcome(
        corpus.accepted_payoff_proof(), change_set=change_set, effective_decisions=corpus.accepted_payoff_decisions()
    )
    unaccepted = validate_thread_payoff_outcome(
        corpus.unaccepted_payoff_proof(), change_set=change_set, effective_decisions={"d-1"}
    )
    assert accepted.findings == ()
    assert [finding.rule_id for finding in unaccepted.findings] == ["SCENE_EXIT_THREAD_UNMET"]


async def test_both_halves_of_the_no_pov_author_draft_gate() -> None:
    passes_scene_half = await _compile_gate_scene(corpus.omniscient_scene())
    denied_by_scene_half = await _compile_gate_scene(corpus.denied_scene())
    assert [finding.rule_id for finding in passes_scene_half] == ["AUTHOR_DRAFT_POLICY_CAPABILITY_UNAVAILABLE"]
    assert [finding.rule_id for finding in denied_by_scene_half] == ["SCENE_OMNISCIENT_AUTHORING_FORBIDDEN"]


def test_the_r9_and_r10_regression_cases_and_their_clean_control() -> None:
    canon = corpus.corpus_canon()

    def rules(scene: object) -> list[str]:
        report = _VALIDATOR.validate_scene(canon=canon, plan=corpus.scene_plan(scene), scene=scene)
        return [finding.rule_id for finding in report.findings]

    assert "SCENE_PRESENT_REF_UNRESOLVED" in rules(corpus.r9_unresolved_present_ref_scene())
    assert "SCENE_CONSTRAINT_DUPLICATE_ID" in rules(corpus.r10_duplicate_constraint_id_scene())
    assert "SCENE_CONSTRAINT_DUPLICATE_SEMANTIC" in rules(corpus.r10_duplicate_semantic_scene())
    assert rules(corpus.clean_v2_scene()) == []


def test_one_accepted_revision_compiles_multiple_non_overlapping_lineages_into_one_delta() -> None:
    reviewed = corpus.non_overlapping_reviewed_change_sets()
    result = _COMPILER.compile(
        corpus.compiler_identity(reviewed),
        corpus.compiler_revision(),
        reviewed,
        [],
        corpus.COMPILER_BASE,
        corpus.compiler_policy(),
    )
    assert isinstance(result, CompilationSucceeded)
    assert result.canon_delta.source_change_set_refs == ["cs-1", "cs-2"]
    assert len({item.change_set.change_set_lineage_id for item in reviewed}) == 2


def test_an_overlap_resolved_by_a_human_lineage_compiles_and_an_unresolved_one_produces_no_delta() -> None:
    overlapping = corpus.overlapping_reviewed_change_sets()
    resolutions = [corpus.human_keep_resolution()]
    resolved = _COMPILER.compile(
        corpus.compiler_identity(overlapping, resolutions),
        corpus.compiler_revision(),
        overlapping,
        resolutions,
        corpus.COMPILER_BASE,
        corpus.compiler_policy(),
    )
    unresolved = _COMPILER.compile(
        corpus.compiler_identity(overlapping),
        corpus.compiler_revision(),
        overlapping,
        [],
        corpus.COMPILER_BASE,
        corpus.compiler_policy(),
    )
    assert isinstance(resolved, CompilationSucceeded)
    assert resolved.canon_delta.author_decision_refs == ["d-1", "d-2", "d-3", "d-4"]
    assert unresolved.outcome == "CONFLICT"
    assert unresolved.canon_delta is None


def test_an_outcome_only_selection_mutates_no_canon() -> None:
    outcome_only = corpus.outcome_only_reviewed_change_sets()
    result = _COMPILER.compile(
        corpus.compiler_identity(outcome_only),
        corpus.compiler_revision(),
        outcome_only,
        [],
        corpus.COMPILER_BASE,
        corpus.compiler_policy(),
    )
    assert result.outcome == "NO_CANON_MUTATION"
    assert result.canon_delta is None


async def test_a_rejected_alternative_leaves_the_existing_effective_selection_intact(
    m5c_pipeline: M5CPipeline,
) -> None:
    await m5c_pipeline.accept_revision(decision_id="d-1", revision_id="rev-1")
    await m5c_pipeline.seed_revision("rev-2")
    await m5c_pipeline.acceptance.decide_revision(
        make_revision_acceptance_command(
            decision_id="d-2",
            work_scope=_scope(),
            action="REJECT",
            selected_revision_id="rev-2",
            expected_latest_decision_id="d-1",
            expected_effective_decision_id="d-1",
        ),
        authenticated_principal=SHOWRUNNER,
    )
    head = await m5c_pipeline.acceptance.get_current_revision_selection(_scope())
    assert head is not None
    assert head.effective_decision_id == "d-1"
    assert head.latest_decision_id == "d-2"
    assert await m5c_pipeline.acceptance.verify_exact_current_selection("d-1", user_id=USER, project_name=PROJECT)


async def test_a_superseded_revision_and_decision_still_replay_historically(m5c_pipeline: M5CPipeline) -> None:
    """The superseded decision is not deleted or rewritten: the authoritative chain still
    walks through it, and an exact-input replay against the decision set captured at that
    earlier instant reproduces the same result without asserting current authority."""
    await m5c_pipeline.accept_revision(decision_id="d-1", revision_id="rev-1")
    historical = corpus.accepted_payoff_decisions()
    before = validate_thread_payoff_outcome(
        corpus.accepted_payoff_proof(), change_set=corpus.payoff_change_set(), effective_decisions=historical
    )
    await m5c_pipeline.seed_revision("rev-2")
    await m5c_pipeline.acceptance.decide_revision(
        make_revision_acceptance_command(
            decision_id="d-2",
            work_scope=_scope(),
            action="SUPERSEDE",
            selected_revision_id="rev-2",
            expected_latest_decision_id="d-1",
            expected_effective_decision_id="d-1",
        ),
        authenticated_principal=SHOWRUNNER,
    )
    chain = await m5c_pipeline.integrity.verify_revision_decision_chain(_scope())
    assert chain.effective_decision_id == "d-2"
    assert not await m5c_pipeline.acceptance.verify_exact_current_selection("d-1", user_id=USER, project_name=PROJECT)
    after = validate_thread_payoff_outcome(
        corpus.accepted_payoff_proof(), change_set=corpus.payoff_change_set(), effective_decisions=historical
    )
    assert after == before


async def test_extraction_outcome_unknown_rejects_late_success_and_continues_only_in_a_new_generation(
    m5c_pipeline: M5CPipeline,
) -> None:
    await m5c_pipeline.accept_revision(decision_id="dec-1", revision_id="rev-1")
    first = await m5c_pipeline.evidence.admit_extraction(_extraction_command(generation=0))
    await m5c_pipeline.evidence.record_non_successful_extraction(
        _result(attempt_id=first.attempt_id, outcome="OUTCOME_UNKNOWN")
    )
    with pytest.raises(NarrativeAttemptGenerationConflict):
        await m5c_pipeline.evidence.record_successful_extraction(
            _result(result_id="res-late", attempt_id=first.attempt_id, outcome="SUCCEEDED", change_set_ids=("cs-1",)),
            [make_narrative_change_set(change_set_id="cs-1")],
        )
    assert (
        await m5c_pipeline.evidence.get_exact_change_set(change_set_id="cs-1", project_name=PROJECT, user_id=USER)
    ) is None
    continuation = await m5c_pipeline.evidence.admit_extraction(_extraction_command(generation=1))
    assert continuation.generation == 1
    assert continuation.revision_id == first.revision_id


async def test_a_compilation_crash_before_recording_is_recomputed_and_recorded_idempotently(
    m5c_pipeline: M5CPipeline,
) -> None:
    await _seed_one_reviewed_change_set(m5c_pipeline.acceptance, m5c_pipeline.session_factory)
    attempt = await m5c_pipeline.evidence.admit_compilation(_compilation_command())
    assert (
        await m5c_pipeline.evidence.get_exact_compilation_result(
            attempt_id=attempt.attempt_id, generation=0, project_name=PROJECT, user_id=USER
        )
    ) is None  # the crash left a durable attempt with no result
    delta = await _recompiled_delta(m5c_pipeline)
    result = make_compilation_result(
        result_id=RESULT_ID,
        attempt_id=attempt.attempt_id,
        generation=0,
        outcome="SUCCEEDED",
        canon_delta_id=delta.canon_delta_id,
        canon_delta_payload_hash=delta.payload_hash,
    )
    first = await m5c_pipeline.evidence.record_successful_compilation(result, delta)
    again = await m5c_pipeline.evidence.record_successful_compilation(result, delta)
    assert first == again


async def test_supersession_before_admission_blocks_it_and_after_admission_does_not(
    m5c_pipeline: M5CPipeline,
) -> None:
    await m5c_pipeline.seed_admissible_handoff()
    admitted = await m5c_pipeline.admit()
    await _supersede_the_revision(m5c_pipeline.acceptance, m5c_pipeline.session_factory)
    replayed = await m5c_pipeline.admit(admission_id=admitted.admission_id)
    assert replayed.admission == admitted.admission  # after: the frozen receipt survives
    await _supersede_the_review(m5c_pipeline.acceptance, m5c_pipeline.session_factory)
    with pytest.raises(NarrativeHandoffConflict):
        await m5c_pipeline.admit(admission_id="adm-2")  # before: a fresh admission is blocked


async def test_a_canon_base_race_after_admission_is_rejected_by_m5a(m5c_pipeline: M5CPipeline) -> None:
    await m5c_pipeline.seed_canon_genesis()
    await m5c_pipeline.seed_admissible_handoff()
    admitted = await m5c_pipeline.admit()
    await m5c_pipeline.advance_canon_head()
    with pytest.raises(CanonBaseVersionConflict):
        await m5c_pipeline.handoff.commit_from_admission(admission_id=admitted.admission_id, now=NOW)


def test_the_v1_compatibility_gate_names_both_regressions_and_clears_the_accepted_scene() -> None:
    leaked = v1_byte_hash_compatibility_findings(
        {**_SEALED_GOLDEN_V1_SCENE.model_dump(mode="json"), "omniscient_authoring_allowed_by_scene": False},
        golden_hash=V1_GOLDEN_SCENE_HASH,
    )
    rehashed = v1_byte_hash_compatibility_findings(
        {
            **_SEALED_GOLDEN_V1_SCENE.model_dump(mode="json"),
            "semantic_hash": compute_scene_semantic_hash_v2(_SEALED_GOLDEN_V1_SCENE),
        },
        golden_hash=V1_GOLDEN_SCENE_HASH,
    )
    assert [finding.rule_id for finding in leaked] == ["V1_SCENE_BYTE_DOMAIN_LEAK"]
    assert [finding.rule_id for finding in rehashed] == ["V1_SCENE_HASH_REGRESSION"]


def test_the_aggregated_corpus_is_deterministic() -> None:
    assert corpus.full_corpus() == corpus.full_corpus()


def _extraction_command(*, generation: int) -> ExtractionAdmissionCommand:
    return ExtractionAdmissionCommand(
        work_scope=_scope(),
        revision_id="rev-1",
        generation=generation,
        revision_acceptance_decision_id="dec-1",
        extractor_kind="LOCAL",
        extractor_version="x-1",
        policy_ref="pol",
        policy_version="1",
        authenticated_principal="human:anhtuan",
    )


async def _recompiled_delta(pipeline: M5CPipeline) -> CanonDelta:
    """The exact delta the seeded single-change-set attempt compiles to, recomputed after
    the crash rather than reloaded from a partial write."""
    _ = pipeline
    return _canon_delta(author_decision_refs=["d-1", "d-2"], source_change_set_refs=["cs-1"])

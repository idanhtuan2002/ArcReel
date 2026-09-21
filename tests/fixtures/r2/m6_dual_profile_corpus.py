"""Golden B — the shared-Canon dual-profile acceptance corpus (plan Task 15).

``build_golden_b_canon`` is a plain data builder — no service wiring, no database —
mirroring ``tests.fixtures.r2.m5c_narrative_corpus``'s own ``corpus_canon_content``/
``corpus_canon``. M6's own branch persistence never cross-checks a Canon ref against a
real Canon table (``AdaptationEvidenceService.create_branch`` only verifies
``parent_branch_id``, never ``parent_canon_version``), so "one pinned Canon fixture"
here is narrative source material both profile slices adapt from, plus a stable
``ArtifactVersionRef`` both branches declare as their exact common parent — not a
persisted M5A Canon commit.

``run_profile_slice`` is the real orchestration: it drives every public M6 service
built across Tasks 6-13 (``AdaptationEvidenceService``, ``AdaptationAuthorityService``,
``ProfileEvaluationService``, ``ApprovedScreenplayReader``, ``TakeDirectorAdapter``)
plus the M3 local-execution primitives (``GoldenAHostIntegration``,
``GoldenALocalProducer``, ``GoldenAComposer``) to produce one complete,
zero-provider-cost 60-120s slice for one profile. Despite their names, none of those
three M3 classes are Golden-A-specific — ``GoldenAHostIntegration`` and
``GoldenAComposer`` take an arbitrary ``target_ref``/shot list, and
``GoldenALocalProducer.produce`` accepts any ``GoldenAPreparedShot`` — so this reuses
them as-is rather than duplicating a parallel "M6 host integration".

The corpus deliberately triggers no ``PROFILE_BLOCK``/``INTEGRITY_BLOCK`` finding
(clean scenes for both profiles): Tasks 11/12 already have dedicated tests proving the
waiver mechanism itself; Task 15's job is proving the whole dual-profile pipeline
integrates end-to-end, not re-proving waiver semantics. The Shuangwen slice uses
chapter 9 (post chapter-1-8 applicability), which needs no 【】-tagged evidence at all
(``evaluate_shuangwen`` treats it as not-applicable with zero required fields) — this
sidesteps the risk of a subtly malformed tagged outline producing an unintended
finding. Task 15 itself says not to assert cultural representativeness; a
structurally-valid-but-minimal Shuangwen text is exactly what that clause licenses.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from r2.adaptation.authority import AdaptationAuthorityService
from r2.adaptation.evaluation import ProfileEvaluationService, report_ref_of
from r2.adaptation.evidence import AdaptationEvidenceService
from r2.adaptation.hashing import compute_adaptation_hash
from r2.adaptation.ports import AdaptationUnitOfWorkFactory
from r2.adaptation.screenplay_reader import ApprovedScreenplayReader
from r2.adaptation.shuangwen_profile import ShuangwenSourceScope
from r2.contracts import (
    ContentBasis,
    ContentBasisType,
    CreativeApprovalStatus,
    Entity,
    EntityType,
    EpistemicState,
    ProductionMethod,
    ResolvedIdentityStatus,
    ResolvedVisualIdentity,
    ShotSpecV2,
)
from r2.contracts.adaptation import (
    AdaptationBranchV2,
    AdaptationDecisionAction,
    AdaptationMapEntry,
    AdaptationMapV2,
    AdaptationOperation,
    AdaptationPolicy,
    AdaptationProfileId,
    AdaptationProfileRef,
    AdmittedScreenplayRef,
    ArtifactVersionRef,
    DecisionRef,
    MapApprovalCommand,
    ProfileWaiverCommand,
    ScreenplayAdmissionCommand,
    ScreenplayArtifactV2,
    ScreenplayScene,
)
from r2.contracts.narrative import (
    CanonContent,
    EpistemicProposition,
    Fact,
    KnowledgeState,
    compute_epistemic_proposition_ref,
)
from r2.m3.composition import GoldenAComposer, GoldenACompositeAsset
from r2.m3.host_integration import GoldenAHostIntegration, compute_content_fingerprint
from r2.m3.local_production import GoldenALocalProducer
from r2.m3.preparation import GoldenAMethodAssignment, GoldenAPreparedShot
from r2.narrative.hashing import compute_canon_content_hash
from r2.production_intelligence.director import DirectorRouteUnavailable
from r2.production_intelligence.readiness import ProductionReadinessEvaluator
from r2.production_intelligence.take_director import TakeDirectionResult, TakeDirectorAdapter

_PRINCIPAL = "human:golden-b"
_HERO = "char-hero"
_ALLY = "char-ally"
_WAREHOUSE = "loc-warehouse"
_SAFEHOUSE = "loc-safehouse"
_LEDGER = "obj-ledger"
_T0 = datetime(2026, 1, 1, 8, tzinfo=UTC)
_T1 = datetime(2026, 1, 1, 20, tzinfo=UTC)


class _FakeAuthority:
    async def authorize(self, *, authenticated_principal, action, command_identity_hash):
        from r2.contracts.adaptation import AdaptationDecisionAuthorization

        return AdaptationDecisionAuthorization(
            authenticated_principal=authenticated_principal,
            authority_role="HUMAN_SHOWRUNNER",
            action=action,
            command_identity_hash=command_identity_hash,
            approval_receipt=f"receipt:{command_identity_hash}",
            authorized_at=datetime.now(UTC),
        )


@dataclass(frozen=True)
class CanonFixture:
    canon_ref: ArtifactVersionRef
    content: CanonContent


def build_golden_b_canon() -> CanonFixture:
    """Two characters, a location change, a prop/state change and an asymmetric
    secret: the Hero knows where the ledger is hidden; the Ally does not."""
    secret_proposition = EpistemicProposition(
        proposition_ref=compute_epistemic_proposition_ref(
            subject_ref=_LEDGER, predicate="hidden_at", object_or_value=_SAFEHOUSE
        ),
        subject_ref=_LEDGER,
        predicate="hidden_at",
        object_or_value=_SAFEHOUSE,
    )
    content = CanonContent(
        entities_by_id={
            _HERO: Entity(entity_id=_HERO, entity_type=EntityType.CHARACTER, canonical_name="Hero"),
            _ALLY: Entity(entity_id=_ALLY, entity_type=EntityType.CHARACTER, canonical_name="Ally"),
            _WAREHOUSE: Entity(entity_id=_WAREHOUSE, entity_type=EntityType.LOCATION, canonical_name="Old Warehouse"),
            _SAFEHOUSE: Entity(entity_id=_SAFEHOUSE, entity_type=EntityType.LOCATION, canonical_name="Safehouse"),
            _LEDGER: Entity(entity_id=_LEDGER, entity_type=EntityType.OBJECT, canonical_name="Old Ledger"),
        },
        facts_by_id={
            "fact-hero-location-1": Fact(
                fact_id="fact-hero-location-1",
                subject_ref=_HERO,
                predicate="location",
                value=_WAREHOUSE,
                effective_from=_T0,
                effective_until=_T1,
            ),
            "fact-hero-location-2": Fact(
                fact_id="fact-hero-location-2",
                subject_ref=_HERO,
                predicate="location",
                value=_SAFEHOUSE,
                effective_from=_T1,
                effective_until=None,
            ),
            "fact-ledger-state-1": Fact(
                fact_id="fact-ledger-state-1",
                subject_ref=_LEDGER,
                predicate="state",
                value="hidden",
                effective_from=_T0,
                effective_until=_T1,
            ),
            "fact-ledger-state-2": Fact(
                fact_id="fact-ledger-state-2",
                subject_ref=_LEDGER,
                predicate="state",
                value="revealed",
                effective_from=_T1,
                effective_until=None,
            ),
        },
        events_by_id={},
        epistemic_propositions_by_ref={secret_proposition.proposition_ref: secret_proposition},
        knowledge_states_by_id={
            "ks-hero-knows": KnowledgeState(
                knowledge_state_id="ks-hero-knows",
                subject_entity_id=_HERO,
                proposition_ref=secret_proposition.proposition_ref,
                epistemic_state=EpistemicState.KNOWN,
                effective_from=_T0,
            ),
            "ks-ally-unaware": KnowledgeState(
                knowledge_state_id="ks-ally-unaware",
                subject_entity_id=_ALLY,
                proposition_ref=secret_proposition.proposition_ref,
                epistemic_state=EpistemicState.UNKNOWN,
                effective_from=_T0,
            ),
        },
        temporal_relations_by_id={},
    )
    content_hash = "sha256:" + compute_canon_content_hash(content, schema_version="r2-canon-schema-v2")
    return CanonFixture(
        canon_ref=ArtifactVersionRef(artifact_id="canon-golden-b", version=1, content_hash=content_hash),
        content=content,
    )


_WESTERN_SCENES = [
    ("w-scene-1", "INT. OLD WAREHOUSE - NIGHT\nHero crouches beside a crate.\nHero listens for footsteps outside."),
    ("w-scene-2", "INT. OLD WAREHOUSE - NIGHT\nHero pries the crate open.\nThe ledger is inside, wrapped in cloth."),
    ("w-scene-3", "EXT. STREET - NIGHT\nHero slips out the back door.\nAlly waits by the car, engine running."),
    ("w-scene-4", "INT. CAR - NIGHT\nAlly asks what Hero found.\nHero says nothing, holding the ledger close."),
    ("w-scene-5", "INT. SAFEHOUSE - DAY\nHero sets the ledger on the table.\nAlly reads the first page aloud."),
    ("w-scene-6", "INT. SAFEHOUSE - DAY\nAlly realizes what the ledger proves.\nHero nods, the secret finally shared."),
]

_SHUANGWEN_CHAPTER = "第9章"
_SHUANGWEN_SCENES = [
    ("s-scene-1", f"{_SHUANGWEN_CHAPTER}\n阿May蹲在旧仓库的木箱旁，听着外面的脚步声。"),
    ("s-scene-2", f"{_SHUANGWEN_CHAPTER}\n阿May撬开木箱，账本用布包着放在里面。"),
    ("s-scene-3", f"{_SHUANGWEN_CHAPTER}\n阿May从后门溜出，阿强在车旁等着，引擎还开着。"),
    ("s-scene-4", f"{_SHUANGWEN_CHAPTER}\n阿强问阿May找到了什么，阿May没说话，把账本抱得更紧。"),
    ("s-scene-5", f"{_SHUANGWEN_CHAPTER}\n阿May把账本放在桌上，阿强大声念出第一页。"),
    ("s-scene-6", f"{_SHUANGWEN_CHAPTER}\n阿强终于明白账本证明了什么，阿May点头，秘密终于说开。"),
]

_SHOT_DURATION_S = 15.0


def _content_basis() -> ContentBasis:
    return ContentBasis(basis_type=ContentBasisType.NARRATIVE, basis_version="canon-golden-b", refs=["canon-golden-b"])


def _screenplay_scenes(profile_id: AdaptationProfileId) -> list[ScreenplayScene]:
    pairs = _WESTERN_SCENES if profile_id == AdaptationProfileId.WESTERN_GENERIC else _SHUANGWEN_SCENES
    return [
        ScreenplayScene(
            scene_id=scene_id,
            purpose="advance the ledger reveal",
            duration_target=_SHOT_DURATION_S,
            location_ref=None,
            character_refs=[_HERO, _ALLY],
            source_mapping_refs=["entry-1"],
            dramatic_text=text,
        )
        for scene_id, text in pairs
    ]


@dataclass(frozen=True)
class GoldenBSliceEvidence:
    profile_ref: AdaptationProfileRef
    branch_id: str
    parent_canon_ref: ArtifactVersionRef
    map_approval_ref: DecisionRef
    report_digest: str
    waiver_ref: DecisionRef | None
    admission_ref: DecisionRef
    admitted_screenplay_ref: ArtifactVersionRef
    scenes: tuple
    shots: tuple[ShotSpecV2, ...]
    approved_target_refs: tuple[str, ...]
    multi_candidate_shot_id: str
    multi_candidate_count: int
    final: GoldenACompositeAsset


async def run_profile_slice(
    profile_ref: AdaptationProfileRef,
    *,
    canon: CanonFixture,
    uow_factory: AdaptationUnitOfWorkFactory,
    user_id: str,
    project_name: str,
    work_dir: Path,
) -> GoldenBSliceEvidence:
    branch_id = f"golden-b-{profile_ref.profile_id.value.lower()}"
    map_id = f"{branch_id}-map"
    screenplay_id = f"{branch_id}-sp"

    evidence = AdaptationEvidenceService(uow_factory)
    authority = AdaptationAuthorityService(uow_factory, _FakeAuthority())
    evaluation = ProfileEvaluationService(uow_factory)
    reader = ApprovedScreenplayReader(uow_factory)

    branch = await evidence.create_branch(
        AdaptationBranchV2(
            branch_id=branch_id,
            schema_version="r2-adaptation-branch-v2",
            version=1,
            parent_branch_id=None,
            parent_canon_version=canon.canon_ref,
            medium="SHORT_FORM_VIDEO",
            adaptation_policy=AdaptationPolicy.FAITHFUL,
            overlay_version=1,
            profile_ref=profile_ref,
            created_at=datetime.now(UTC),
            created_by=_PRINCIPAL,
        ),
        user_id=user_id,
        project_name=project_name,
    )
    branch_ref = ArtifactVersionRef(
        artifact_id=branch.branch_id, version=branch.version, content_hash="sha256:" + "b0" * 32
    )

    map_entry = AdaptationMapEntry(
        entry_id="entry-1",
        source_refs=["canon-golden-b"],
        target_refs=["screenplay:scenes"],
        operation=AdaptationOperation.PRESERVE,
        rationale="carry the ledger reveal forward",
        fidelity_risk="low",
        approval_status=CreativeApprovalStatus.APPROVED,
    )
    map_draft = AdaptationMapV2(
        adaptation_map_id=map_id,
        schema_version="r2-adaptation-map-v2",
        version=1,
        adaptation_branch_ref=branch_ref,
        entries=[map_entry],
        profile_analysis_refs=[],
        content_hash="pending",
    )
    map_ = await evidence.append_map(
        map_draft.model_copy(update={"content_hash": compute_adaptation_hash(map_draft)}),
        user_id=user_id,
        project_name=project_name,
    )
    map_ref = ArtifactVersionRef(
        artifact_id=map_.adaptation_map_id, version=map_.version, content_hash=map_.content_hash
    )

    map_approve = MapApprovalCommand(
        user_id=user_id,
        project_name=project_name,
        decision_id=f"d-map-{branch_id}",
        branch_id=branch_id,
        map_ref=map_ref,
        profile_ref=profile_ref,
        relied_report_refs=[],
        expected_predecessor_id=None,
        action=AdaptationDecisionAction.APPROVE,
    )
    map_receipt = await authority.decide_map(map_approve, authenticated_principal=_PRINCIPAL)

    screenplay_draft = ScreenplayArtifactV2(
        screenplay_id=screenplay_id,
        schema_version="r2-screenplay-artifact-v2",
        version=1,
        adaptation_branch_ref=branch_ref,
        content_basis=_content_basis(),
        scenes=_screenplay_scenes(profile_ref.profile_id),
        characters=[_HERO, _ALLY],
        source_mapping_refs=["entry-1"],
        approval_status=CreativeApprovalStatus.DRAFT,
        locked_for_direction=False,
        content_hash="pending",
        adaptation_map_ref=map_ref,
        profile_analysis_refs=[],
    )
    proposal = await evidence.append_screenplay(
        screenplay_draft.model_copy(update={"content_hash": compute_adaptation_hash(screenplay_draft)}),
        user_id=user_id,
        project_name=project_name,
    )
    proposal_ref = ArtifactVersionRef(
        artifact_id=proposal.screenplay_id, version=proposal.version, content_hash=proposal.content_hash
    )

    source_scope = None
    if profile_ref.profile_id == AdaptationProfileId.CN_SHORT_DRAMA_SHUANGWEN:
        source_scope = ShuangwenSourceScope(chapter_start=9, chapter_end=9, source_refs=["canon-golden-b"])
    report = await evaluation.evaluate(
        artifact_ref=proposal_ref,
        profile_ref=profile_ref,
        user_id=user_id,
        project_name=project_name,
        source_scope=source_scope,
    )

    waiver_ref: DecisionRef | None = None
    blocking = [f for f in report.findings if f.disposition.value in ("INTEGRITY_BLOCK", "PROFILE_BLOCK")]
    if blocking:
        waive = ProfileWaiverCommand(
            user_id=user_id,
            project_name=project_name,
            decision_id=f"d-waive-{branch_id}",
            branch_id=branch_id,
            artifact_ref=proposal_ref,
            profile_ref=profile_ref,
            report_ref=report_ref_of(report),
            finding_ids=[f.finding_id for f in blocking],
            rule_versions=[f.rule_version for f in blocking],
            rationale="accepted for the Golden B acceptance slice",
            expected_predecessor_id=None,
            action=AdaptationDecisionAction.WAIVE,
        )
        waiver_receipt = await authority.decide_waiver(waive, authenticated_principal=_PRINCIPAL)
        waiver_ref = waiver_receipt.decision_ref

    admitted_draft = proposal.model_copy(
        update={
            "version": proposal.version + 1,
            "approval_status": CreativeApprovalStatus.APPROVED,
            "locked_for_direction": True,
            "content_hash": "pending",
        }
    )
    admitted_screenplay = admitted_draft.model_copy(update={"content_hash": compute_adaptation_hash(admitted_draft)})
    admit = ScreenplayAdmissionCommand(
        user_id=user_id,
        project_name=project_name,
        decision_id=f"d-admit-{branch_id}",
        branch_id=branch_id,
        proposal_ref=proposal_ref,
        admitted_screenplay=admitted_screenplay,
        profile_ref=profile_ref,
        effective_map_approval_ref=map_receipt.decision_ref,
        report_refs=[report_ref_of(report)],
        waiver_refs=[waiver_ref] if waiver_ref is not None else [],
        expected_predecessor_id=None,
        action=AdaptationDecisionAction.ADMIT,
    )
    admission_receipt = await authority.admit_screenplay_for_direction(admit, authenticated_principal=_PRINCIPAL)
    admitted_ref = ArtifactVersionRef(
        artifact_id=admitted_screenplay.screenplay_id,
        version=admitted_screenplay.version,
        content_hash=admitted_screenplay.content_hash,
    )

    take = TakeDirectorAdapter(reader, user_id=user_id, project_name=project_name)
    direction = await take.direct(
        AdmittedScreenplayRef(
            screenplay_ref=admitted_ref, admission_ref=admission_receipt.decision_ref, profile_ref=profile_ref
        )
    )
    if not isinstance(direction, TakeDirectionResult):
        raise DirectorRouteUnavailable(f"unexpected TakeDirectorAdapter result: {direction!r}")

    host = GoldenAHostIntegration(work_dir, resource_type="videos", episode=1)
    local_producer = GoldenALocalProducer()
    resolved_identity = ResolvedVisualIdentity(
        target_ref="golden-b", status=ResolvedIdentityStatus.RESOLVED, resolution_policy_version="identity-v1"
    )
    now = datetime.now(UTC)
    approved_target_refs: list[str] = []
    multi_candidate_shot_id = direction.shots[0].id
    multi_candidate_count = 0
    scenes_by_id = {scene.scene_id: scene for scene in admitted_screenplay.scenes}

    for index, shot in enumerate(direction.shots):
        readiness = ProductionReadinessEvaluator().evaluate(
            shot=shot,
            bindings=[],
            resolved_identity=resolved_identity,
            observed_target_version=f"{shot.id}@1",
            binding_snapshot_ref="golden-b-snapshot@1",
        )
        # M3's real-media closure (docs/superpowers/specs/2026-09-21-r2-m3-real-media-closure-design.md):
        # GENERATED_VIDEO has no real content source in this closure (no paid
        # provider is qualified) -- DETERMINISTIC renders the scene's own real
        # dramatic_text on screen instead of a "TAKE local stand-in" label.
        prepared = GoldenAPreparedShot(
            shot=shot,
            bindings=(),
            readiness=readiness,
            method=GoldenAMethodAssignment(
                target_ref=shot.id, method=ProductionMethod.DETERMINISTIC, rationale="Golden B dramatic text"
            ),
        )
        dramatic_text = scenes_by_id[shot.scene_id].dramatic_text
        variants = ["default", "b"] if index == 0 else ["default"]
        registered = None
        for variant in variants:
            if index == 0:
                multi_candidate_count += 1
            display_text = dramatic_text if variant == "default" else f"{dramatic_text} ({variant})"
            produced = local_producer.produce(prepared, work_dir=work_dir / "produced", display_text=display_text)
            fingerprint = compute_content_fingerprint(shot, [])
            registered = host.stage_candidate(
                target_ref=shot.id,
                content_fingerprint=fingerprint,
                produced=produced,
                content_basis=_content_basis(),
                direct_dependencies=[],
                contract_version=shot.version,
                contract_schema_version=shot.schema_version,
            )
        assert registered is not None
        approved_master = host.approve(
            registered, approval_record=f"approval:{shot.id}", selected_by=_PRINCIPAL, selected_at=now
        )
        assert approved_master.selected_candidate_id == registered.candidate.id
        approved_target_refs.append(shot.id)

    final = GoldenAComposer().compose(host, [shot.id for shot in direction.shots], output_path=work_dir / "final.mp4")

    return GoldenBSliceEvidence(
        profile_ref=profile_ref,
        branch_id=branch_id,
        parent_canon_ref=canon.canon_ref,
        map_approval_ref=map_receipt.decision_ref,
        report_digest=report.report_digest,
        waiver_ref=waiver_ref,
        admission_ref=admission_receipt.decision_ref,
        admitted_screenplay_ref=admitted_ref,
        scenes=tuple(direction.scenes),
        shots=tuple(direction.shots),
        approved_target_refs=tuple(approved_target_refs),
        multi_candidate_shot_id=multi_candidate_shot_id,
        multi_candidate_count=multi_candidate_count,
        final=final,
    )


__all__ = [
    "CanonFixture",
    "GoldenBSliceEvidence",
    "build_golden_b_canon",
    "run_profile_slice",
]

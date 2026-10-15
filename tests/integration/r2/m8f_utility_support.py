"""The M8-F integrated cohort run (plan F2): every M8 workflow for one M6 profile cohort, through the
host routes and services on one database.

``run_cohort`` builds the cohort's creative project from the locked corpus, admits its screenplay
under the cohort's M6 profile, approves two shot masters through Gate C, measures the host-only
baseline, then runs Canvas, Spatial, Format and Learning and returns the measured deliverables and
digests. Only the vision model is a double (the pinned spatial fixture response); renders, probes,
promotions and learning rules are the real services. Semantic format reviews here come from a test
reviewer with a showrunner grant: they exercise the mechanism and are not the protocol's blind reviews.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.models.advanced_creative import M8CandidateRevisionModel
from lib.db.models.spatial_pair import SpatialConstraintSetModel
from lib.db.repositories.formats import FormatRepository
from lib.db.repositories.host_hardening import MasterAuthorityRepository
from lib.db.repositories.spatial_review import SpatialReviewRepository
from lib.db.repositories.spatial_source import _receipt_digest
from lib.project_manager import ProjectManager
from r2.advanced_creative.digests import digest_canonical, digest_payload
from r2.advanced_creative.formats import (
    Box,
    ReframeKind,
    build_plan,
    format_slot_key,
    reframe_decision,
    source_master_id,
)
from r2.advanced_creative.lineage import resolve_episode_lineage
from r2.contracts.adaptation import AdaptationProfileId, AdmittedScreenplayRef
from r2.contracts.advanced_creative import (
    CanonicalJsonObject,
    CanvasCandidate,
    CanvasEdge,
    CanvasNode,
    ExplorationKind,
    ExplorationRevision,
    LearningObservation,
    LineageBinding,
    PromotionAuthorization,
    PromotionTarget,
    PromotionTargetKind,
)
from r2.contracts.production_binding_authority import BindingCreateCommandV1
from r2.contracts.spatial_pair import PairDecisionCommandV2
from r2.learning.adapters import ADAPTER_VERSION, YOUTUBE_FAMILY, observe_youtube_days, youtube_rows
from r2.learning.cohorts import CohortKey, RuleParams
from r2.learning.replay import Protocol, ReplayReport, replay, split_holdout
from r2.m3.host_integration import GoldenAHostIntegration
from r2.production_binding.spatial_promotion import spatial_preview_v2_digest
from r2.production_intelligence.take_director import TakeDirectorAdapter
from r2.target_registry.service import RegisterTakeTargetsCommand, TakeTargetRegistrationService
from server.auth import CurrentUserInfo, get_current_interactive_user, get_current_user
from server.error_handlers import register_error_handlers
from server.routers import advanced_creative, gates, learning, spatial
from server.services import advanced_creative as composition
from server.services.format_candidate import prepare_format_candidate
from server.services.format_render import file_digest
from server.services.format_review import FormatReviewService
from server.services.format_validation import FormatValidationService
from server.services.location_binding import LocationBindingCreationService
from server.services.spatial_pair_decision_v2 import SpatialPairDecisionServiceV2
from server.services.spatial_promotion import SpatialPreviewCommand, SpatialPromotionService
from server.services.spatial_review_session import SpatialReviewSessionService
from server.services.spatial_source import FrameDerivationService
from tests.auth_deps import AUTH_DEPENDENCIES
from tests.fixtures.r2 import m8f_corpus as corpus
from tests.fixtures.r2.m8f_profiles import AdmittedProfile, admit_profile
from tests.integration.server.routers.spatial_approval_support import PAIR_V2_VECTOR, showrunner_grants
from tests.integration.server.routers.test_gates_export import _body
from tests.integration.server.routers.test_spatial_execution import ROUTE
from tests.integration.server.services.test_format_render import render_service
from tests.unit.r2.advanced_creative.test_formats import overlay, profile
from tests.unit.r2.production_binding.spatial_constraint_fixture import raw_response

type Factory = async_sessionmaker[AsyncSession]

USER = CurrentUserInfo(id="default", sub="operator-1", role="admin")
REVIEWER = "m8f-test-reviewer"
SOURCE_SIZE = (1280, 720)
# Stylized rooms drawn to match the pinned spatial fixture: boxes sit where its visible assertions'
# spans put them (x as a fraction of the width, y 0.2-0.8), so a reviewer can check each assertion.
SHOT_PATTERNS = {
    "SH01": (("red", 0.70, 0.82), ("yellow", 0.00, 0.12)),
    "SH02": (("blue", 0.65, 0.79), ("yellow", 0.88, 1.00)),
}
VIEWS_DEFINITION = f"{YOUTUBE_FAMILY}/views@{ADAPTER_VERSION}"
FORMAT_TARGETS = (("vertical-9x16@1", 1080, 1920), ("square@1", 1080, 1080))


@dataclass
class CohortResult:
    profile_id: str
    project: str
    baseline: dict[str, int] = field(default_factory=dict)
    deliverables: dict[str, int] = field(default_factory=dict)
    digests: dict[str, Any] = field(default_factory=dict)
    lineage_profiles: dict[str, str] = field(default_factory=dict)
    master_heads_before: dict[str, str] = field(default_factory=dict)
    master_heads_after: dict[str, str] = field(default_factory=dict)
    replay: dict[str, Any] = field(default_factory=dict)
    probes: dict[str, Any] = field(default_factory=dict)


class _FixtureVision:
    """The pinned spatial fixture response in place of a vision model; counts its calls."""

    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self, *, prompt: str, master_png: bytes, reverse_png: bytes, execution_id: str) -> bytes:
        self.calls += 1
        return json.dumps(raw_response()).encode()


def app_client(monkeypatch: pytest.MonkeyPatch, factory: Factory, root: Path, vision: _FixtureVision) -> AsyncClient:
    projects = ProjectManager(root)
    for module in (gates, advanced_creative, spatial, learning):
        monkeypatch.setattr(module, "async_session_factory", factory)
        monkeypatch.setattr(module, "get_project_manager", lambda: projects)
    app = FastAPI()
    app.dependency_overrides[get_current_user] = lambda: USER
    app.dependency_overrides[get_current_interactive_user] = lambda: USER
    app.dependency_overrides[spatial.spatial_vision] = lambda: spatial.SpatialVision(route=ROUTE, call=vision)
    for module in (gates, advanced_creative, spatial, learning):
        app.include_router(module.router, prefix="/api/v1", dependencies=AUTH_DEPENDENCIES)
    register_error_handlers(app)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def write_project(root: Path, project: str, script: bytes) -> Path:
    project_dir = root / project
    (project_dir / "scripts").mkdir(parents=True, exist_ok=True)
    (project_dir / "production").mkdir(exist_ok=True)
    (project_dir / "project.json").write_text(
        json.dumps({"title": project, "episodes": [{"episode": 1, "script_file": "scripts/episode_1.json"}]}),
        encoding="utf-8",
    )
    (project_dir / "scripts" / "episode_1.json").write_bytes(script)
    return project_dir


def _shot_media(path: Path, boxes: tuple[tuple[str, float, float], ...], project: str) -> bytes:
    """Deterministic media; the tone frequency differs per project, so masters never share bytes."""
    width, height = SOURCE_SIZE
    frequency = 300 + int(hashlib.sha256(project.encode()).hexdigest()[:4], 16) % 500
    draw = ",".join(
        f"drawbox=x={round(x0 * width)}:y={round(0.2 * height)}:w={round((x1 - x0) * width)}"
        f":h={round(0.6 * height)}:color={color}:t=fill"
        for color, x0, x1 in boxes
    )
    subprocess.run(
        [
            *("ffmpeg", "-nostdin", "-y", "-v", "error"),
            *("-f", "lavfi", "-i", f"color=c=gray:s={width}x{height}:d=2:r=30"),
            *("-f", "lavfi", "-i", f"sine=frequency={frequency}:duration=2"),
            *("-vf", draw),
            *("-c:v", "libx264", "-pix_fmt", "yuv420p", "-threads", "1", "-c:a", "aac", "-shortest"),
            *("-fflags", "+bitexact", "-flags:v", "+bitexact", "-flags:a", "+bitexact", "-map_metadata", "-1"),
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    return path.read_bytes()


async def _master_heads(factory: Factory, project: str, keys: list[str]) -> dict[str, str]:
    heads = {}
    async with factory() as session:
        for key in keys:
            head = await MasterAuthorityRepository(session).get_current(
                user_id=USER.id, project_name=project, artifact_key=key
            )
            heads[key] = "absent" if head is None else f"{head.master_version}:{head.content_digest}"
    return heads


async def _count(factory: Factory, model: Any, project: str) -> int:
    async with factory() as session:
        return await session.scalar(select(func.count()).select_from(model).where(model.project_name == project)) or 0


async def _approve_masters(client: AsyncClient, project: str, project_dir: Path) -> dict[str, str]:
    keys = {}
    for shot, pattern in SHOT_PATTERNS.items():
        data = _shot_media(project_dir / "production" / f"{shot}.mp4", pattern, project)
        response = await client.post(f"/api/v1/projects/{project}/gates/final-cut", json=_body(shot, data))
        assert response.status_code == 200, (project, shot, response.text)
        keys[shot] = GoldenAHostIntegration(project_dir, resource_type="videos", episode=1).artifact_key_for(shot)
    return keys


async def _canvas(client: AsyncClient, project: str, result: CohortResult) -> None:
    base = f"/api/v1/projects/{project}/m8/exploration"
    context = (await client.get(f"{base}/context", params={"episode": 1})).json()
    result.lineage_profiles["canvas"] = context["lineage"]["creative_profile_id"]
    nodes = (
        CanvasNode(node_id="scene", node_type="scene", body=CanonicalJsonObject.model_validate({"label": "reveal"})),
        CanvasNode(node_id="alt-a", node_type="shot", body=CanonicalJsonObject.model_validate({"take": "close"})),
        CanvasNode(node_id="alt-b", node_type="shot", body=CanonicalJsonObject.model_validate({"take": "wide"})),
    )
    edges = tuple(
        CanvasEdge(
            edge_id=f"e-{child}",
            source_node_id="scene",
            target_node_id=child,
            edge_type="alternative",
            body=CanonicalJsonObject.model_validate({}),
        )
        for child in ("alt-a", "alt-b")
    )
    revisions = []
    for number, (kept_nodes, kept_edges) in enumerate(((nodes[:2], edges[:1]), (nodes, edges)), start=1):
        payload = CanvasCandidate(
            kind=ExplorationKind.CANVAS,
            graph_schema_version="1",
            nodes=kept_nodes,
            edges=kept_edges,
            groups=(),
            storyboard_order=tuple(node.node_id for node in kept_nodes),
            viewport_bookmarks=(),
        )
        lineage = context["lineage"]
        revision = ExplorationRevision.model_validate(
            {
                "candidate_id": "m8f-canvas",
                "revision": number,
                "kind": "CANVAS",
                "parent_revision": None if number == 1 else number - 1,
                "payload": payload.model_dump(mode="json"),
                "payload_digest": digest_payload(payload, LineageBinding.model_validate(lineage)),
                "lineage": lineage,
                "created_by": context["created_by"],
                "created_at": datetime(2026, 10, 15, 12, number, tzinfo=UTC).isoformat(),
            }
        )
        response = await client.post(
            f"{base}/revisions",
            json={
                "candidate": revision.model_dump(mode="json"),
                "expected_head_version": None if number == 1 else number - 1,
                "command_id": f"m8f-canvas-{number}",
            },
        )
        assert response.status_code == 200, response.text
        revisions.append(revision.model_dump(mode="json"))
    history = (await client.get(f"{base}/candidates/m8f-canvas/revisions")).json()
    reloaded = [(await client.get(f"{base}/candidates/m8f-canvas/revisions/{number}")).json() for number in (1, 2)]
    head = (await client.get(f"{base}/candidates/m8f-canvas")).json()
    siblings = sum(1 for edge in reloaded[-1]["payload"]["edges"] if edge["source_node_id"] == "scene")
    intact = reloaded == revisions and head["current_revision"] == 2
    result.probes["canvas_history"] = history if isinstance(history, list) else history.get("items", history)
    result.deliverables["CANVAS"] = 1 if intact and siblings >= 2 else 0
    # The graph is the artifact and is deterministic; the payload digest also binds the lineage, whose
    # content basis names this run's admission decision.
    result.digests["canvas"] = [digest_canonical(item["payload"]) for item in reloaded]
    result.digests["canvas_payload_digests"] = [item["payload_digest"] for item in reloaded]


async def _spatial(
    client: AsyncClient,
    factory: Factory,
    project: str,
    project_dir: Path,
    admitted: AdmittedProfile,
    keys: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    result: CohortResult,
) -> None:
    original_direct = TakeDirectorAdapter.direct

    async def direct_with_location(self, ref):
        directed = await original_direct(self, ref)
        return replace(
            directed,
            scenes=tuple(scene.model_copy(update={"location_ref": "location:room-1"}) for scene in directed.scenes),
            shots=tuple(shot.model_copy(update={"target_duration": 5.0}) for shot in directed.shots),
        )

    monkeypatch.setattr(TakeDirectorAdapter, "direct", direct_with_location)
    registered = await TakeTargetRegistrationService(factory).register(
        RegisterTakeTargetsCommand(
            user_id=USER.id,
            project_name=project,
            principal=USER.sub,
            command_id="m8f-register",
            admitted_screenplay_ref=admitted.ref,
        )
    )
    monkeypatch.setattr(TakeDirectorAdapter, "direct", original_direct)
    target = registered.shot_targets[0]
    receipts = {}
    for shot, key in keys.items():
        receipt = await FrameDerivationService(session_factory=factory, project_dir=project_dir).derive(
            user_id=USER.id,
            project_name=project,
            parent_artifact_key=key,
            expected_master_version=1,
            decoded_frame_index=0,
            command_id=f"m8f-frame-{shot}",
        )
        receipts[receipt.frame_candidate_id] = {
            "receipt_id": receipt.frame_candidate_id,
            "receipt_digest": _receipt_digest(receipt),
        }
    created = await LocationBindingCreationService(session_factory=factory, project_dir=project_dir).create(
        BindingCreateCommandV1.model_validate(
            {
                "user_id": USER.id,
                "project_name": project,
                "principal": USER.sub,
                "command_id": "m8f-binding",
                "expected_target_ref": target.model_dump(mode="json"),
                "ordered_frame_receipts": [receipts[name] for name in sorted(receipts)],
            }
        )
    )
    grants = await showrunner_grants(factory, user_id=USER.id, project_name=project, principal=USER.sub)
    review = SpatialReviewSessionService(session_factory=factory, project_dir=project_dir, grants=grants)
    snapshot = await review.create(
        user_id=USER.id, project_name=project, principal=USER.sub, target_id=target.target_id
    )
    scope = {"user_id": USER.id, "project_name": project, "principal": USER.sub, "session_id": snapshot.session_id}
    for frame in snapshot.frames:
        _served, delivery = await review.fetch_frame(**scope, role=frame.role)
        await review.acknowledge_frame(
            **scope, attempt_id=delivery.attempt_id, role=frame.role, png_digest=frame.png_digest, decoded=True
        )
    async with factory() as session, session.begin():
        _evidence, evidence_digest = await SpatialReviewRepository(session).read_complete(**scope)
    approval = await SpatialPairDecisionServiceV2(
        session_factory=factory, project_dir=project_dir, grants=grants
    ).decide(
        PairDecisionCommandV2.model_validate(
            PAIR_V2_VECTOR["body"]["command"]
            | {
                "user_id": USER.id,
                "project_name": project,
                "principal": USER.sub,
                "command_id": "m8f-pair-approve",
                "expected_scene_ref": snapshot.scene_ref.model_dump(mode="json"),
                "expected_target_ref": snapshot.target_ref.model_dump(mode="json"),
                "binding_id": snapshot.binding_id,
                "expected_binding_version": snapshot.binding_version,
                "expected_envelope_digest": snapshot.envelope_digest,
                "expected_core_digest": snapshot.core_digest,
                "views": [
                    {"role": frame.role, "receipt_id": frame.receipt_id, "receipt_digest": frame.receipt_digest}
                    for frame in snapshot.frames
                ],
                "review_session_id": snapshot.session_id,
                "review_evidence_digest": evidence_digest,
                "decision": "APPROVE",
            }
        ),
        authenticated_user=CurrentUserInfo(id=USER.id, sub=USER.sub, role="user"),
    )
    roles = {frame.role: receipts[frame.receipt_id] for frame in snapshot.frames}
    executed = await client.post(
        f"/api/v1/projects/{project}/m8/spatial/executions",
        json={
            "command_id": "m8f-spatial-1",
            "candidate_id": "m8f-spatial",
            "expected_head_version": None,
            "episode": 1,
            "scene_name": "Ledger room",
            "master": roles["MASTER"],
            "reverse": roles["REVERSE"],
        },
    )
    assert executed.status_code == 200, executed.text
    async with factory() as session:
        revision = await composition.exploration_service(session).get_exact(
            user_id=USER.id, project_name=project, candidate_id="m8f-spatial", revision=1
        )
    result.lineage_profiles["spatial"] = revision.lineage.creative_profile_id
    visible = tuple(a.assertion_id for a in revision.payload.spatial.assertions if a.evidence_class.value == "VISIBLE")
    service = SpatialPromotionService(session_factory=factory, project_dir=project_dir, grants=grants)
    preview = await service.create_preview(
        SpatialPreviewCommand(
            user_id=USER.id,
            project_name=project,
            candidate_id="m8f-spatial",
            candidate_revision=1,
            target_id=target.target_id,
            expected_binding_version=1,
            selected_assertion_ids=visible,
            command_id="m8f-spatial-preview",
        )
    )
    receipt = await service.promote(
        user_id=USER.id,
        project_name=project,
        authorization=PromotionAuthorization(
            command_id="m8f-spatial-promote",
            project_name=project,
            preview_id=preview.base_preview.preview_id,
            preview_digest=spatial_preview_v2_digest(preview.model_dump(mode="json")),
            actor_id=USER.id,
            actor_scope=USER.id,
            decision="APPROVE",
            authorized_at=datetime.now(UTC),
        ),
        expected_candidate_head_version=1,
    )
    result.deliverables["SPATIAL"] = 1 if receipt.result.binding_version == 2 else 0
    result.digests["spatial"] = {
        "receipt": receipt.model_dump(mode="json"),
        "revision_payload": revision.payload.model_dump(mode="json"),
        "binding_id": created.result.binding_id,
        "pair_decision": approval.decision_digest,
        "constraint_set": preview.binding.proposal.model_dump(mode="json"),
        "visible_assertions": len(visible),
        "assertions": [
            {
                "assertion_id": a.assertion_id,
                "evidence_class": a.evidence_class.value,
                "subjects": list(a.subject_refs),
                "relation": a.relation,
                "confidence": a.confidence,
                "spans": [span.model_dump(mode="json") for span in a.source_spans],
            }
            for a in revision.payload.spatial.assertions
        ],
    }


async def _format(factory: Factory, project: str, project_dir: Path, source_key: str, result: CohortResult) -> None:
    source = project_dir / "production" / "SH01.mp4"
    grants = await showrunner_grants(factory, user_id=USER.id, project_name=project, principal=REVIEWER)
    promoted = 0
    renders = {}
    for profile_ref, width, height in FORMAT_TARGETS:
        target = profile(width, height, profile_ref=profile_ref)
        decision = reframe_decision(
            decision_id=f"pad-{profile_ref}",
            kind=ReframeKind.PAD,
            source_size=SOURCE_SIZE,
            profile=target,
            focal=None,
            subject=Box(Fraction(2, 5), Fraction(1, 4), Fraction(3, 5), Fraction(3, 4)),
            rationale="keep the whole frame",
        )
        plan = build_plan(
            plan_id=f"m8f-{profile_ref.split('@', 1)[0]}",
            source_master_id=source_master_id(source_key, 1),
            source_master_digest=file_digest(source),
            profile=target,
            overlay=overlay(),
            decisions=(decision,),
        )
        async with factory() as session:
            repository = FormatRepository(session)
            await repository.put_profile(user_id=USER.id, project_name=project, profile=target)
            await repository.put_overlay(user_id=USER.id, project_name=project, overlay=overlay())
            await repository.create_plan(user_id=USER.id, project_name=project, plan=plan)
            await session.commit()
        rendered = await render_service(factory).render(
            user_id=USER.id,
            project_name=project,
            project_dir=project_dir,
            plan_id=plan.plan_id,
            source=source,
            command_id=f"m8f-render-{plan.plan_id}",
        )
        technical = await FormatValidationService(factory).validate(
            user_id=USER.id,
            project_name=project,
            project_dir=project_dir,
            execution_id=rendered.execution_id,
            source=source,
        )
        reviews = FormatReviewService(factory, grants=grants)
        packet = await reviews.open_packet(
            user_id=USER.id,
            project_name=project,
            project_dir=project_dir,
            execution_id=rendered.execution_id,
            source_ref=source.relative_to(project_dir).as_posix(),
            reviewer_id=REVIEWER,
        )
        semantic = await reviews.submit(
            user_id=USER.id,
            project_name=project,
            packet_id=packet.packet_id,
            reviewer_id=REVIEWER,
            items=dict.fromkeys(
                ("focal_subject", "action", "shot_intent", "on_screen_text", "captions", "timing", "audio"), "PASS"
            ),
            note="automated mechanism review",
        )
        prepared = await prepare_format_candidate(
            factory,
            user_id=USER.id,
            project_name=project,
            project_dir=project_dir,
            execution_id=rendered.execution_id,
            author=USER.id,
        )
        async with factory() as session:
            revision = await composition.exploration_service(session).get_exact(
                user_id=USER.id, project_name=project, candidate_id=prepared.candidate_id, revision=prepared.revision
            )
            preview = await composition.exploration_service(session).create_preview(
                user_id=USER.id,
                project_name=project,
                candidate_id=prepared.candidate_id,
                revision=prepared.revision,
                target=PromotionTarget(
                    kind=PromotionTargetKind.ARTIFACT_SLOT,
                    target_ref=prepared.slot_key,
                    expected_target_version=prepared.expected_target_version,
                ),
                command_id=f"m8f-preview-{plan.plan_id}",
            )
        result.lineage_profiles[f"format:{profile_ref}"] = revision.lineage.creative_profile_id
        async with factory() as session:
            receipt = await composition.exploration_promotion(session).promote(
                user_id=USER.id,
                project_name=project,
                authorization=PromotionAuthorization(
                    command_id=f"m8f-promote-{plan.plan_id}",
                    project_name=project,
                    preview_id=preview.preview_id,
                    preview_digest=digest_canonical(preview),
                    actor_id=USER.id,
                    actor_scope=USER.id,
                    decision="APPROVE",
                    authorized_at=datetime.now(UTC),
                ),
                expected_candidate_head_version=prepared.head_version,
            )
        if technical.passed and semantic.passed and receipt.result_digest == rendered.artifact_digest:
            promoted += 1
        renders[profile_ref] = {
            "receipt": receipt.model_dump(mode="json"),
            "technical_report": technical.model_dump(mode="json"),
            "semantic_report": semantic.model_dump(mode="json"),
            "artifact_digest": rendered.artifact_digest,
            "technical_passed": technical.passed,
            "semantic_passed": semantic.passed,
            "slot": prepared.slot_key,
            "artifact_ref": rendered.artifact_path.relative_to(project_dir).as_posix(),
        }
    result.deliverables["FORMAT"] = promoted
    result.digests["format"] = renders


def observations_for(profile: AdaptationProfileId, project: str, script: bytes, admission: AdmittedScreenplayRef):
    """The corpus observations of one learning project under its server-resolved lineage."""
    lineage = resolve_episode_lineage(project, 1, script, admissions=(admission,))
    observations = []
    for arm in corpus.ARMS:
        records = observe_youtube_days(
            video_id=corpus.video_id(project, arm),
            query=corpus.youtube_query(project, arm),
            requested_days=corpus.requested_days(profile, project),
            rows=youtube_rows(corpus.youtube_table(profile, project, arm)),
            status="PUBLIC",
            lineage=lineage,
            format_profile_ref=arm,
        )
        observations.extend(item for record in records for item in record.observations)
    return observations


async def _learning(
    client: AsyncClient,
    factory: Factory,
    root: Path,
    profile: AdaptationProfileId,
    registered_at: datetime,
    result: CohortResult,
) -> None:
    stored: list[LearningObservation] = []
    script = corpus.episode_script(profile)
    for project in corpus.learning_projects(profile):
        write_project(root, project, script)
        admitted = await admit_profile(factory, user_id=USER.id, project_name=project, profile_id=profile)
        for index, observation in enumerate(observations_for(profile, project, script, admitted.ref)):
            response = await client.post(
                f"/api/v1/projects/{project}/m8/learning/observations",
                json={
                    "episode": 1,
                    "observation": observation.model_dump(mode="json"),
                    "command_id": f"m8f-obs-{index}",
                },
            )
            assert response.status_code == 200, response.text
            stored.append(LearningObservation.model_validate(response.json()))
    train_project, _holdout_project = corpus.learning_projects(profile)
    evaluation = await client.post(
        f"/api/v1/projects/{train_project}/m8/learning/recommendations/evaluate",
        json={
            "source_family": YOUTUBE_FAMILY,
            "metric_name": "views",
            "metric_definition_version": VIEWS_DEFINITION,
            "aggregation": "sum_day",
            "creative_profile_id": profile.value,
            "creative_profile_version": "v1",
            "arm_a": corpus.BASELINE_ARM,
            "arm_b": corpus.TREATMENT_ARM,
            "min_per_arm": 7,
            "min_relative_lift": "0.10",
            "expires_in_days": 30,
            "command_id": "m8f-evaluate",
        },
    )
    assert evaluation.status_code == 200, evaluation.text
    body = evaluation.json()
    recommendation = (body.get("recommendation") or {}).get("recommendation")
    views = tuple(item for item in stored if item.metric_name == "views")
    params = RuleParams(
        arm_a=corpus.BASELINE_ARM, arm_b=corpus.TREATMENT_ARM, min_per_arm=7, min_relative_lift=Decimal("0.10")
    )
    cohort = CohortKey(
        creative_profile_id=profile.value,
        creative_profile_version="v1",
        source_family=YOUTUBE_FAMILY,
        metric_name="views",
        metric_definition_version=VIEWS_DEFINITION,
        aggregation="sum_day",
    )
    protocol = Protocol(
        cohort=cohort,
        params=params,
        baseline_arm=corpus.BASELINE_ARM,
        window_starts_at=min(item.window.starts_at for item in views if item.window.starts_at > corpus.TRAIN_CUTOFF),
        window_ends_at=max(item.window.ends_at for item in views),
        exclusions=(),
        registered_at=registered_at,
    )
    train_protocol = replace(protocol, window_starts_at=min(item.window.starts_at for item in views))
    holdout = split_holdout(
        views,
        evaluation_share=Decimal(corpus.EVALUATION_SHARE),
        train_cutoff=corpus.TRAIN_CUTOFF,
        salt=corpus.HOLDOUT_SALT,
    )
    report: ReplayReport = replay(train_protocol, holdout)
    result.lineage_profiles["learning"] = recommendation["lineage"]["creative_profile_id"] if recommendation else "none"
    held = bool(body["fired"]) and report.direction_held and recommendation is not None
    result.deliverables["LEARNING"] = 1 if held else 0
    result.replay = {
        "train_fired": report.train_fired,
        "train_lift": str(report.train_lift),
        "evaluation_lift": str(report.evaluation_lift),
        "direction_held": report.direction_held,
        "train_projects": list(holdout.train_projects),
        "evaluation_projects": list(holdout.evaluation_projects),
        "language": body["recommendation"]["language"] if recommendation else None,
        "hypothesis": recommendation["hypothesis"] if recommendation else None,
    }
    result.digests["learning"] = {
        "evaluation_ids": list(report.evaluation_ids),
        "train_ids": list(report.train_ids),
        "recommendation_id": recommendation["recommendation_id"] if recommendation else None,
        "recommendation": recommendation,
    }


async def run_cohort(
    client: AsyncClient,
    factory: Factory,
    root: Path,
    profile: AdaptationProfileId,
    monkeypatch: pytest.MonkeyPatch,
    *,
    registered_at: datetime,
) -> CohortResult:
    project = corpus.creative_project(profile)
    result = CohortResult(profile_id=profile.value, project=project)
    project_dir = write_project(root, project, corpus.episode_script(profile))
    admitted = await admit_profile(factory, user_id=USER.id, project_name=project, profile_id=profile)
    keys = await _approve_masters(client, project, project_dir)
    result.master_heads_before = await _master_heads(factory, project, list(keys.values()))
    result.baseline = {
        "CANVAS": await _count(factory, M8CandidateRevisionModel, project),
        "SPATIAL": await _count(factory, SpatialConstraintSetModel, project),
        "LEARNING": 0,
        "FORMAT": sum(
            1
            for head in (
                await _master_heads(
                    factory, project, [format_slot_key(keys["SH01"], ref) for ref, _w, _h in FORMAT_TARGETS]
                )
            ).values()
            if head != "absent"
        ),
    }
    await _canvas(client, project, result)
    await _spatial(client, factory, project, project_dir, admitted, keys, monkeypatch, result)
    await _format(factory, project, project_dir, keys["SH01"], result)
    await _learning(client, factory, root, profile, registered_at, result)
    result.master_heads_after = await _master_heads(factory, project, list(keys.values()))
    result.digests["masters"] = result.master_heads_after
    result.digests["source_sha256"] = {
        shot: "sha256:" + hashlib.sha256((project_dir / "production" / f"{shot}.mp4").read_bytes()).hexdigest()
        for shot in SHOT_PATTERNS
    }
    return result

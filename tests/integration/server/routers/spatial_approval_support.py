"""A current LOCATION binding with a current V2 pair APPROVE, built through the real grant, review and decision services."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.content_digest import canonical_json_bytes
from lib.db.repositories.spatial_review import SpatialReviewRepository
from r2.contracts.spatial_pair import PairDecisionCommandV2, PairDecisionResultV2
from r2.governance.grant_transition import GrantScopeV1
from server.auth import CurrentUserInfo
from server.services.governance_grants import CurrentShowrunnerGrantReader, GovernanceGrantImporter
from server.services.spatial_pair_decision_v2 import SpatialPairDecisionServiceV2
from server.services.spatial_review_session import SpatialReviewSessionService
from tests.integration.server.routers.test_gates_export import PROJECT, USER
from tests.integration.server.routers.test_spatial_constraint_snapshot import _current_binding

type Factory = async_sessionmaker[AsyncSession]

PAIR_V2_VECTOR = json.loads(
    (Path(__file__).resolve().parents[3] / "fixtures/r2/m8c_pair_v2_decision_vector.json").read_text(encoding="utf-8")
)
KEY_ID = "test-promotion-key"


@dataclass(frozen=True)
class ApprovedLocation:
    binding_id: str
    target_id: str
    grants: CurrentShowrunnerGrantReader
    approval: PairDecisionResultV2


async def showrunner_grants(factory: Factory) -> CurrentShowrunnerGrantReader:
    """Import one signed, current HUMAN_SHOWRUNNER grant for the test user and return its reader."""
    private = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    grants = CurrentShowrunnerGrantReader(key_id=KEY_ID, public_key=public)
    issued_at = (datetime.now(UTC) - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    body = {
        "schema": "governance.showrunner_grant_event.v1",
        "event_type": "ISSUE",
        "user_id": USER.id,
        "project_name": PROJECT,
        "principal": USER.sub,
        "role": "HUMAN_SHOWRUNNER",
        "sequence": 1,
        "previous_event_digest": None,
        "issued_at": issued_at,
        "not_before": issued_at,
        "expires_at": (datetime.now(UTC) + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "signer_key_id": KEY_ID,
    }
    signature = base64.urlsafe_b64encode(private.sign(canonical_json_bytes(body, allow_nan=False))).decode().rstrip("=")
    await GovernanceGrantImporter(factory, key_id=KEY_ID, public_key=public).import_event(
        canonical_json_bytes({"body": body, "signature": signature}, allow_nan=False),
        scope=GrantScopeV1(USER.id, PROJECT, USER.sub),
    )
    return grants


async def approved_location(
    client: AsyncClient,
    project_dir: Path,
    factory: Factory,
    monkeypatch: pytest.MonkeyPatch,
    *,
    shot_duration: float | None = None,
) -> ApprovedLocation:
    binding_id, target_id = await _current_binding(
        client, project_dir, factory, monkeypatch, shot_duration=shot_duration
    )
    grants = await showrunner_grants(factory)

    review = SpatialReviewSessionService(session_factory=factory, project_dir=project_dir, grants=grants)
    snapshot = await review.create(user_id=USER.id, project_name=PROJECT, principal=USER.sub, target_id=target_id)
    scope = {"user_id": USER.id, "project_name": PROJECT, "principal": USER.sub, "session_id": snapshot.session_id}
    for frame in snapshot.frames:
        _served, delivery = await review.fetch_frame(**scope, role=frame.role)
        await review.acknowledge_frame(
            **scope, attempt_id=delivery.attempt_id, role=frame.role, png_digest=frame.png_digest, decoded=True
        )
    async with factory() as session, session.begin():
        _evidence, evidence_digest = await SpatialReviewRepository(session).read_complete(**scope)
    command = PairDecisionCommandV2.model_validate(
        PAIR_V2_VECTOR["body"]["command"]
        | {
            "user_id": USER.id,
            "project_name": PROJECT,
            "principal": USER.sub,
            "command_id": "promotion-pair-approve-1",
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
    )
    approval = await SpatialPairDecisionServiceV2(
        session_factory=factory, project_dir=project_dir, grants=grants
    ).decide(command, authenticated_user=CurrentUserInfo(id=USER.id, sub=USER.sub, role="user"))
    return ApprovedLocation(binding_id=binding_id, target_id=target_id, grants=grants, approval=approval)


async def promoted_target(
    client: AsyncClient,
    project_dir: Path,
    factory: Factory,
    monkeypatch: pytest.MonkeyPatch,
    *,
    shot_duration: float | None = None,
) -> str:
    """A Shot whose LOCATION binding was approved as a pair and promoted with every VISIBLE fixture assertion."""
    from server.services.advanced_creative import exploration_service
    from server.services.spatial_promotion import SpatialPreviewCommand, SpatialPromotionService
    from tests.integration.server.routers.test_spatial_promotion import _authorization
    from tests.integration.server.routers.test_spatial_promotion_preview import spatial_candidate

    approved = await approved_location(client, project_dir, factory, monkeypatch, shot_duration=shot_duration)
    await spatial_candidate(factory, project_dir, approved)
    async with factory() as session:
        revision = await exploration_service(session).get_exact(
            user_id=USER.id, project_name=PROJECT, candidate_id="spatial-candidate-1", revision=1
        )
    visible = tuple(a.assertion_id for a in revision.payload.spatial.assertions if a.evidence_class.value == "VISIBLE")
    service = SpatialPromotionService(session_factory=factory, project_dir=project_dir, grants=approved.grants)
    preview = await service.create_preview(
        SpatialPreviewCommand(
            user_id=USER.id,
            project_name=PROJECT,
            candidate_id="spatial-candidate-1",
            candidate_revision=1,
            target_id=approved.target_id,
            expected_binding_version=1,
            selected_assertion_ids=visible,
            command_id="spatial-preview-1",
        )
    )
    await service.promote(
        user_id=USER.id, project_name=PROJECT, authorization=_authorization(preview), expected_candidate_head_version=1
    )
    return approved.target_id

"""Promotion domain rules over in-memory ports: lock order, replay first, scope (ADR-0097)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from r2.advanced_creative.digests import digest_canonical, digest_command, digest_payload
from r2.advanced_creative.errors import (
    CommandConflictError,
    ExplorationNotFoundError,
    PromotionBindingStaleError,
    PromotionTargetUnavailableError,
)
from r2.advanced_creative.promotion import PROMOTE_OPERATION, ExplorationPromotion
from r2.contracts.advanced_creative import (
    CandidateHead,
    ExplorationKind,
    ExplorationRevision,
    FormatCandidate,
    LineageBinding,
    PromotionAuthorization,
    PromotionPreview,
    PromotionReceipt,
    PromotionTarget,
    PromotionTargetKind,
)
from r2.contracts.host_hardening import MasterHeadSnapshot, VerifiedCandidateObject

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
DIGEST = "sha256:" + "a" * 64
OBJECT_DIGEST = "sha256:" + "b" * 64


@dataclass(frozen=True)
class _Receipt:
    command_digest: str
    result_ref: str
    result_digest: str


def _revision() -> ExplorationRevision:
    lineage = LineageBinding(
        project_name="demo",
        content_basis_digest=DIGEST,
        approved_master_id=None,
        approved_master_digest=None,
        creative_profile_id="p",
        creative_profile_version="1",
        policy_digest=DIGEST,
    )
    payload = FormatCandidate(
        kind=ExplorationKind.FORMAT,
        plan_digest=DIGEST,
        rendered_artifact_ref="obj-b",
        rendered_artifact_digest=OBJECT_DIGEST,
        technical_report_id="t",
        technical_report_digest=DIGEST,
        semantic_report_id="s",
        semantic_report_digest=DIGEST,
        execution_id="e",
    )
    return ExplorationRevision(
        candidate_id="c1",
        revision=1,
        kind=ExplorationKind.FORMAT,
        parent_revision=None,
        payload=payload,
        payload_digest=digest_payload(payload, lineage),
        lineage=lineage,
        created_by="u1",
        created_at=NOW,
    )


def _preview(target_ref: str = "m8-slot:x") -> PromotionPreview:
    return PromotionPreview(
        preview_id="pv1",
        preview_command_id="pc1",
        project_name="demo",
        candidate_id="c1",
        candidate_revision=1,
        candidate_payload_digest=_revision().payload_digest,
        target=PromotionTarget(
            kind=PromotionTargetKind.ARTIFACT_SLOT, target_ref=target_ref, expected_target_version=1
        ),
        expected_master_id="obj-a",
        expected_master_digest=DIGEST,
        impact={},
        impact_digest=DIGEST,
        authorization_scope="u1",
        issued_at=NOW,
        expires_at=NOW + timedelta(seconds=900),
    )


class _World:
    """In-memory store and slot authority that record the order locks are taken in."""

    def __init__(self, preview: PromotionPreview) -> None:
        self.events: list[str] = []
        self.preview = preview
        self.receipts: dict[str, _Receipt] = {}
        self.promotion_receipts: dict[str, PromotionReceipt] = {}
        self.master = MasterHeadSnapshot(
            artifact_key=preview.target.target_ref,
            master_version=1,
            candidate_id="obj-a",
            object_ref="/a",
            content_digest=DIGEST,
            approval_record="seed",
        )

    # store
    async def lock_command_key(self, **_: str) -> None:
        self.events.append("command")

    async def get_command_receipt(self, *, command_id: str, **_: str) -> _Receipt | None:
        return self.receipts.get(command_id)

    async def record_command(
        self, *, command_id: str, command_digest: str, result_ref: str, result_digest: str, **_: object
    ) -> None:
        self.receipts[command_id] = _Receipt(command_digest, result_ref, result_digest)

    async def get_preview(self, *, for_update: bool = False, **_: str) -> tuple[PromotionPreview, str]:
        if for_update:
            self.events.append("preview")
        return self.preview, digest_canonical(self.preview)

    async def get_head(self, *, for_update: bool = False, **_: object) -> CandidateHead:
        if for_update:
            self.events.append("head")
        return CandidateHead(candidate_id="c1", current_revision=1, head_version=1)

    async def get_exact(self, **_: object) -> ExplorationRevision:
        return _revision()

    async def stage_authorization(self, **_: object) -> str:
        self.events.append("authorization")
        return DIGEST

    async def stage_promotion_receipt(self, *, receipt: PromotionReceipt, **_: object) -> None:
        self.promotion_receipts[receipt.command_id] = receipt

    async def get_promotion_receipt(self, *, command_id: str, **_: str) -> PromotionReceipt | None:
        return self.promotion_receipts.get(command_id)

    # slots
    def is_manifest_key(self, target_ref: str) -> bool:
        return target_ref.startswith("artifact-key-v1:")

    async def lock_slot(self, **_: str) -> None:
        self.events.append("slot")

    async def current_head(self, **_: str) -> MasterHeadSnapshot:
        return self.master

    async def candidate_object(self, **_: str) -> VerifiedCandidateObject:
        return VerifiedCandidateObject(
            candidate_id="obj-b",
            project_name="demo",
            artifact_key=self.preview.target.target_ref,
            object_ref="/b",
            byte_size=1,
            content_digest=OBJECT_DIGEST,
            media_probe_digest=DIGEST,
        )

    async def promote(self, *, candidate_id: str, **_: object) -> MasterHeadSnapshot:
        self.events.append("promote")
        self.master = self.master.model_copy(
            update={"master_version": 2, "candidate_id": candidate_id, "content_digest": OBJECT_DIGEST}
        )
        return self.master


def _service(world: _World, now: datetime = NOW) -> ExplorationPromotion:
    async def commit() -> None:
        world.events.append("commit")

    return ExplorationPromotion(store=world, slots=world, commit=commit, clock=lambda: now, new_id=lambda: "r1")


def _authorization(preview: PromotionPreview, **overrides: object) -> PromotionAuthorization:
    fields: dict[str, object] = {
        "command_id": "cmd",
        "project_name": "demo",
        "preview_id": preview.preview_id,
        "preview_digest": digest_canonical(preview),
        "actor_id": "u1",
        "actor_scope": "u1",
        "decision": "APPROVE",
        "authorized_at": NOW,
    }
    return PromotionAuthorization(**(fields | overrides))


async def _promote(world: _World, authorization: PromotionAuthorization, now: datetime = NOW) -> PromotionReceipt:
    return await _service(world, now).promote(
        user_id="u1", project_name="demo", authorization=authorization, expected_candidate_head_version=1
    )


async def test_locks_are_taken_in_the_adr_order_and_the_promotion_commits_once() -> None:
    world = _World(_preview())

    receipt = await _promote(world, _authorization(world.preview))

    assert world.events == ["command", "head", "preview", "slot", "authorization", "promote", "commit"]
    assert (receipt.result_master_id, receipt.result_digest) == ("obj-b", OBJECT_DIGEST)


async def test_an_exact_replay_returns_the_receipt_before_any_currentness_check() -> None:
    world = _World(_preview())
    authorization = _authorization(world.preview)
    first = await _promote(world, authorization)
    world.events.clear()

    # Even long after expiry, the exact replay returns the stored receipt without new locks.
    again = await _promote(world, authorization, now=NOW + timedelta(days=1))

    assert again == first
    assert world.events == []


async def test_a_reused_command_with_another_request_conflicts() -> None:
    world = _World(_preview())
    await _promote(world, _authorization(world.preview))
    world.receipts["cmd"] = _Receipt(
        digest_command(PROMOTE_OPERATION, "u1", "demo", "u1", {"other": True}), "r1", DIGEST
    )

    with pytest.raises(CommandConflictError):
        await _promote(world, _authorization(world.preview))


@pytest.mark.parametrize("field", ["project_name", "actor_id"])
async def test_an_authorization_outside_the_callers_scope_is_not_found(field: str) -> None:
    world = _World(_preview())

    with pytest.raises(ExplorationNotFoundError):
        await _promote(world, _authorization(world.preview, **{field: "other"}))
    assert world.events == []


async def test_an_expired_preview_is_stale_and_writes_nothing() -> None:
    world = _World(_preview())

    with pytest.raises(PromotionBindingStaleError):
        await _promote(world, _authorization(world.preview), now=NOW + timedelta(seconds=900))
    assert "authorization" not in world.events


async def test_a_master_moved_after_the_preview_is_stale() -> None:
    world = _World(_preview())
    world.master = world.master.model_copy(update={"master_version": 2})

    with pytest.raises(PromotionBindingStaleError):
        await _promote(world, _authorization(world.preview))
    assert "promote" not in world.events


async def test_a_manifest_slot_is_unavailable() -> None:
    world = _World(_preview(target_ref="artifact-key-v1:abc"))

    with pytest.raises(PromotionTargetUnavailableError):
        await _promote(world, _authorization(world.preview))
    assert "slot" not in world.events

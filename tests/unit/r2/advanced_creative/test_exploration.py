"""Exploration domain rules over in-memory ports: preview lock order, replay, targets, scope."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest

from r2.advanced_creative.digests import digest_canonical, digest_payload
from r2.advanced_creative.errors import (
    CandidateConflictError,
    CommandConflictError,
    ExplorationNotFoundError,
    PromotionBindingStaleError,
    PromotionTargetUnavailableError,
)
from r2.advanced_creative.exploration import PREVIEW_TTL, ExplorationService, uuid7
from r2.contracts.advanced_creative import (
    CandidateHead,
    CanvasCandidate,
    ExplorationKind,
    ExplorationRevision,
    FormatCandidate,
    LineageBinding,
    PromotionPreview,
    PromotionTarget,
    PromotionTargetKind,
    SpatialCandidate,
    SpatialPayload,
)
from r2.contracts.host_hardening import MasterHeadSnapshot

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
DIGEST = "sha256:" + "a" * 64
LINEAGE = LineageBinding(
    project_name="demo",
    content_basis_digest=DIGEST,
    approved_master_id=None,
    approved_master_digest=None,
    creative_profile_id="p",
    creative_profile_version="1",
    policy_digest=DIGEST,
)


@dataclass(frozen=True)
class _Receipt:
    command_digest: str
    result_ref: str
    result_digest: str


class _AcceptFormatEvidence:
    """Tests of the M8-A flow itself; the format evidence gate has its own tests."""

    async def verify(self, **_kwargs: object) -> None:
        return None


def _revision(kind: ExplorationKind = ExplorationKind.FORMAT) -> ExplorationRevision:
    payload = (
        FormatCandidate(
            kind=ExplorationKind.FORMAT,
            plan_digest=DIGEST,
            rendered_artifact_ref="obj-b",
            rendered_artifact_digest=DIGEST,
            technical_report_id="t",
            technical_report_digest=DIGEST,
            semantic_report_id="s",
            semantic_report_digest=DIGEST,
            execution_id="e",
        )
        if kind is ExplorationKind.FORMAT
        else CanvasCandidate(
            kind=ExplorationKind.CANVAS,
            graph_schema_version="1",
            nodes=(),
            edges=(),
            groups=(),
            storyboard_order=(),
            viewport_bookmarks=(),
        )
    )
    return ExplorationRevision(
        candidate_id="c1",
        revision=1,
        kind=kind,
        parent_revision=None,
        payload=payload,
        payload_digest=digest_payload(payload, LINEAGE),
        lineage=LINEAGE,
        created_by="u1",
        created_at=NOW,
    )


class _World:
    def __init__(self, revision: ExplorationRevision) -> None:
        self.events: list[str] = []
        self.revision = revision
        self.receipts: dict[str, _Receipt] = {}
        self.previews: dict[str, PromotionPreview] = {}
        self.master = MasterHeadSnapshot(
            artifact_key="m8-slot:x",
            master_version=1,
            candidate_id="obj-a",
            object_ref="/a",
            content_digest=DIGEST,
            approval_record="seed",
        )

    async def append_revision(self, **_: object) -> CandidateHead:
        self.events.append("append")
        return CandidateHead(candidate_id="c1", current_revision=1, head_version=1)

    async def lock_command_key(self, **_: str) -> None:
        self.events.append("command")

    async def get_command_receipt(self, *, command_id: str, **_: str) -> _Receipt | None:
        return self.receipts.get(command_id)

    async def record_command(
        self, *, command_id: str, command_digest: str, result_ref: str, result_digest: str, **_: object
    ) -> None:
        self.receipts[command_id] = _Receipt(command_digest, result_ref, result_digest)

    async def get_head(self, *, for_update: bool = False, **_: object) -> CandidateHead:
        if for_update:
            self.events.append("head")
        return CandidateHead(candidate_id="c1", current_revision=1, head_version=1)

    async def get_exact(self, **_: object) -> ExplorationRevision:
        return self.revision

    async def stage_preview(self, *, preview: PromotionPreview, **_: object) -> str:
        self.previews[preview.preview_id] = preview
        return digest_canonical(preview)

    async def get_preview(self, *, preview_id: str, **_: object) -> tuple[PromotionPreview, str] | None:
        preview = self.previews.get(preview_id)
        return None if preview is None else (preview, digest_canonical(preview))

    def is_manifest_key(self, target_ref: str) -> bool:
        return target_ref.startswith("artifact-key-v1:")

    async def current_head(self, **_: str) -> MasterHeadSnapshot:
        self.events.append("read-master")
        return self.master


def _service(world: _World) -> ExplorationService:
    async def commit() -> None:
        world.events.append("commit")

    return ExplorationService(
        store=world,
        slots=world,
        commit=commit,
        clock=lambda: NOW,
        new_id=lambda: "pv1",
        format_evidence=_AcceptFormatEvidence(),
    )


def _target(**overrides: object) -> PromotionTarget:
    fields: dict[str, object] = {
        "kind": PromotionTargetKind.ARTIFACT_SLOT,
        "target_ref": "m8-slot:x",
        "expected_target_version": 1,
    }
    return PromotionTarget(**(fields | overrides))


async def _preview(world: _World, target: PromotionTarget | None = None, command: str = "pc1") -> PromotionPreview:
    return await _service(world).create_preview(
        user_id="u1", project_name="demo", candidate_id="c1", revision=1, target=target or _target(), command_id=command
    )


async def test_a_preview_locks_the_command_then_the_head_and_binds_the_current_master() -> None:
    world = _World(_revision())

    preview = await _preview(world)

    assert world.events == ["command", "head", "read-master", "commit"]
    assert (preview.expected_master_id, preview.expected_master_digest) == ("obj-a", DIGEST)
    assert preview.expires_at - preview.issued_at == PREVIEW_TTL


async def test_an_exact_preview_replay_returns_the_stored_preview_without_locks() -> None:
    world = _World(_revision())
    first = await _preview(world)
    world.events.clear()
    world.master = world.master.model_copy(update={"master_version": 9})

    assert await _preview(world) == first
    assert world.events == []


async def test_a_reused_preview_command_with_another_target_conflicts() -> None:
    world = _World(_revision())
    await _preview(world)

    with pytest.raises(CommandConflictError):
        await _preview(world, _target(expected_target_version=2))


@pytest.mark.parametrize(
    ("revision", "target"),
    [
        (_revision(ExplorationKind.CANVAS), _target()),
        (_revision(), _target(target_ref="artifact-key-v1:abc")),
        (_revision(), _target(kind=PromotionTargetKind.PRODUCTION_BINDING, expected_target_version=0)),
    ],
)
async def test_unavailable_targets_write_nothing(revision: ExplorationRevision, target: PromotionTarget) -> None:
    world = _World(revision)

    with pytest.raises(PromotionTargetUnavailableError):
        await _preview(world, target)
    assert "commit" not in world.events


async def test_a_moved_master_version_is_stale() -> None:
    world = _World(_revision())

    with pytest.raises(PromotionBindingStaleError):
        await _preview(world, _target(expected_target_version=2))


@pytest.mark.parametrize("field", ["project_name", "created_by"])
async def test_an_append_outside_the_callers_scope_is_not_found(field: str) -> None:
    world = _World(_revision())
    revision = _revision()
    foreign = (
        revision.model_copy(update={"created_by": "other"})
        if field == "created_by"
        else revision.model_copy(update={"lineage": LINEAGE.model_copy(update={"project_name": "other"})})
    )

    with pytest.raises(ExplorationNotFoundError):
        await _service(world).append_revision(
            user_id="u1", project_name="demo", candidate=foreign, expected_head_version=None, command_id="a1"
        )
    assert world.events == []


async def test_public_append_rejects_unverified_spatial_revision_before_write() -> None:
    spatial = SpatialCandidate(
        kind=ExplorationKind.SPATIAL,
        spatial=SpatialPayload(
            assertions=(),
            seam_locks=(),
            direction_locks=(),
            duplicate_warnings=(),
            execution_id="caller-claimed-execution",
            normalizer_version="spatial-r2-v1",
        ),
    )
    base = _revision()
    revision = ExplorationRevision(
        **(
            base.model_dump(mode="python")
            | {"kind": ExplorationKind.SPATIAL, "payload": spatial, "payload_digest": digest_payload(spatial, LINEAGE)}
        )
    )
    world = _World(revision)

    with pytest.raises(CandidateConflictError, match="server-owned spatial execution"):
        await _service(world).append_revision(
            user_id="u1", project_name="demo", candidate=revision, expected_head_version=None, command_id="spatial-1"
        )
    assert world.events == []


async def test_public_append_rejects_packaging_revisions_before_write() -> None:
    from r2.contracts.advanced_creative import PackagingCandidate
    from tests.unit.r2.contracts.test_packaging import candidate_data

    packaging = PackagingCandidate.model_validate(candidate_data())
    base = _revision()
    revision = ExplorationRevision(
        **(
            base.model_dump(mode="python")
            | {
                "kind": ExplorationKind.PACKAGING,
                "payload": packaging,
                "payload_digest": digest_payload(packaging, LINEAGE),
            }
        )
    )
    world = _World(revision)

    with pytest.raises(CandidateConflictError, match="M10 packaging service"):
        await _service(world).append_revision(
            user_id="u1", project_name="demo", candidate=revision, expected_head_version=None, command_id="package-1"
        )
    assert world.events == []


def _packaging_revision() -> ExplorationRevision:
    from r2.contracts.advanced_creative import PackagingCandidate
    from tests.unit.r2.contracts.test_packaging import candidate_data

    packaging = PackagingCandidate.model_validate(candidate_data())
    return ExplorationRevision(
        **(
            _revision().model_dump(mode="python")
            | {
                "kind": ExplorationKind.PACKAGING,
                "payload": packaging,
                "payload_digest": digest_payload(packaging, LINEAGE),
            }
        )
    )


@pytest.mark.parametrize("target_ref", ["m8-slot:x", "m8-format:abc:square@1"])
async def test_packaging_revisions_never_reach_a_promotion_preview(target_ref: str) -> None:
    from r2.advanced_creative.exploration import promotable_format

    revision = _packaging_revision()
    world = _World(revision)
    with pytest.raises(PromotionTargetUnavailableError, match="PACKAGING candidates have no promotable artifact"):
        await _preview(world, _target(target_ref=target_ref))
    assert world.previews == {}
    with pytest.raises(PromotionTargetUnavailableError):
        promotable_format(revision)


def test_uuid7_ids_are_version_7_and_time_ordered() -> None:
    first, second = uuid7(), uuid7()

    assert first[14] == "7"
    assert first[19] in "89ab"
    assert first[:8] <= second[:8]


async def test_format_previews_fail_closed_without_wired_evidence() -> None:
    world = _World(_revision())
    service = ExplorationService(
        store=world, slots=world, commit=lambda: _noop(), clock=lambda: NOW, new_id=lambda: "pv1"
    )

    with pytest.raises(PromotionBindingStaleError, match="format evidence"):
        await service.create_preview(
            user_id="u1", project_name="demo", candidate_id="c1", revision=1, target=_target(), command_id="pc1"
        )
    assert world.previews == {}


async def _noop() -> None:
    return None


async def test_only_a_format_slot_at_version_zero_may_start_without_a_master() -> None:
    world = _World(_revision())
    world.master = None

    genesis = await _preview(world, _target(target_ref="m8-format:abc:square@1", expected_target_version=0))
    assert (genesis.expected_master_id, genesis.expected_master_digest) == (None, None)
    assert genesis.impact.model_dump()["from"] is None

    with pytest.raises(PromotionTargetUnavailableError, match="no master"):
        await _preview(_World_without_master(), _target(expected_target_version=0), command="pc2")
    with pytest.raises(PromotionTargetUnavailableError, match="no master"):
        await _preview(
            _World_without_master(),
            _target(target_ref="m8-format:abc:square@1", expected_target_version=1),
            command="pc3",
        )


def _World_without_master() -> _World:
    world = _World(_revision())
    world.master = None
    return world


@pytest.mark.parametrize(
    ("target_ref", "version", "allowed"),
    [("m8-format:abc:square@1", 0, True), ("m8-slot:x", 0, False), ("m8-format:abc:square@1", 1, False)],
)
def test_the_preview_contract_admits_no_master_only_for_format_genesis(
    target_ref: str, version: int, allowed: bool
) -> None:
    from pydantic import ValidationError

    fields = {
        "preview_id": "p",
        "preview_command_id": "c",
        "project_name": "demo",
        "candidate_id": "c1",
        "candidate_revision": 1,
        "candidate_payload_digest": DIGEST,
        "target": _target(target_ref=target_ref, expected_target_version=version),
        "expected_master_id": None,
        "expected_master_digest": None,
        "impact": {},
        "impact_digest": DIGEST,
        "authorization_scope": "u1",
        "issued_at": NOW,
        "expires_at": NOW + PREVIEW_TTL,
    }
    if allowed:
        PromotionPreview(**fields)
    else:
        with pytest.raises(ValidationError, match="exact master identity"):
            PromotionPreview(**fields)

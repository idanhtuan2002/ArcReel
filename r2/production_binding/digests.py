"""Preparation-canonical digests for the first LOCATION binding authority packet."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from typing import Any

from r2.contracts.common import ensure_json_value
from r2.contracts.enums import ProductionBindingRole, ProductionBindingTarget
from r2.contracts.fingerprints import canonical_json_bytes
from r2.contracts.preparation import ProductionBinding
from r2.contracts.production_binding_authority import (
    BindingCreateCommandV1,
    BindingCreateResultV1,
    BindingEnvelopeV1,
    BindingSnapshotV1,
    FrameSourceClaimV1,
)

_FRAME_ID = re.compile(r"m8f:[0-9a-f]{64}\Z")
_BINDING_ID = re.compile(r"m8b:[0-9a-f]{64}\Z")
_GROUP_REF = re.compile(r"m8g:[0-9a-f]{64}\Z")
_DIGEST_DOMAINS = {
    "binding_identity": "r2.m8.spatial.binding.identity.v1",
    "source_group": "r2.m8.spatial.binding.source_group.v1",
    "binding_body": "r2.m8.spatial.binding.body.v1",
    "binding_core": "r2.m8.spatial.binding.core.v1",
    "frame_claim": "r2.m8.spatial.binding.frame_claim.v1",
    "binding_envelope": "r2.m8.spatial.binding.envelope.v1",
    "binding_create_command": "r2.m8.spatial.binding.create.command.v1",
    "binding_create_result": "r2.m8.spatial.binding.create.result.v1",
    "binding_snapshot": "r2.m8.spatial.binding.snapshot.v1",
}


def _digest(kind: str, body: Mapping[str, Any]) -> str:
    envelope = ensure_json_value({"domain": _DIGEST_DOMAINS[kind], "canonical_version": "1", "body": dict(body)})
    return "sha256:" + hashlib.sha256(canonical_json_bytes(envelope)).hexdigest()


def _nonblank_scope(*values: str) -> None:
    if any(not value or value != value.strip() for value in values):
        raise ValueError("binding scope and target IDs must be nonblank and unpadded")


def scoped_location_binding_id(*, user_id: str, project_name: str, target_id: str) -> str:
    _nonblank_scope(user_id, project_name, target_id)
    digest = _digest(
        "binding_identity",
        {
            "user_id": user_id,
            "project_name": project_name,
            "target_type": ProductionBindingTarget.SHOT.value,
            "target_id": target_id,
            "role": ProductionBindingRole.LOCATION.value,
        },
    )
    return "m8b:" + digest.removeprefix("sha256:")


def source_group_ref(*, user_id: str, project_name: str, frame_candidate_ids: Sequence[str]) -> str:
    _nonblank_scope(user_id, project_name)
    frame_ids = list(frame_candidate_ids)
    if len(frame_ids) != 2 or len(set(frame_ids)) != 2 or any(_FRAME_ID.fullmatch(item) is None for item in frame_ids):
        raise ValueError("source group requires two distinct m8f frame candidate IDs")
    if frame_ids != sorted(frame_ids):
        raise ValueError("source group frame candidate IDs must be sorted")
    digest = _digest(
        "source_group", {"user_id": user_id, "project_name": project_name, "frame_candidate_ids": frame_ids}
    )
    return "m8g:" + digest.removeprefix("sha256:")


def binding_body_digest(body: ProductionBinding) -> str:
    frame_ids = body.asset_refs
    if (
        body.schema_version != "1"
        or body.target_type != ProductionBindingTarget.SHOT
        or body.role != ProductionBindingRole.LOCATION
        or body.variant_ref is not None
        or body.state_ref is not None
        or len(frame_ids) != 2
        or len(set(frame_ids)) != 2
        or frame_ids != sorted(frame_ids)
        or any(_FRAME_ID.fullmatch(item) is None for item in frame_ids)
        or _BINDING_ID.fullmatch(body.id) is None
        or _GROUP_REF.fullmatch(body.production_ref) is None
    ):
        raise ValueError("binding body is outside the LOCATION frame-source contract")
    return _digest("binding_body", body.model_dump(mode="json"))


def frame_source_claim_digest(body: Mapping[str, Any]) -> str:
    claim = FrameSourceClaimV1.model_validate(body)
    return _digest("frame_claim", claim.model_dump(mode="json"))


def binding_envelope_digest(body: Mapping[str, Any]) -> str:
    envelope = BindingEnvelopeV1.model_validate(body)
    for claim in envelope.ordered_claims:
        claim_body = claim.model_dump(mode="json", exclude={"claim_digest"})
        if frame_source_claim_digest(claim_body) != claim.claim_digest:
            raise ValueError("binding envelope frame claim digest does not match its body")
    return _digest("binding_envelope", envelope.model_dump(mode="json"))


def binding_core_digest(*, body: ProductionBinding, envelope: BindingEnvelopeV1) -> str:
    if envelope.binding_body_digest != binding_body_digest(body):
        raise ValueError("binding core body digest does not match envelope")
    binding_envelope_digest(envelope.model_dump(mode="json"))
    frame_ids = [claim.frame_candidate_id for claim in envelope.ordered_claims]
    if (
        envelope.binding_id != body.id
        or envelope.binding_version != body.version
        or envelope.target_ref.target_id != body.target_id
        or frame_ids != body.asset_refs
        or source_group_ref(user_id=envelope.user_id, project_name=envelope.project_name, frame_candidate_ids=frame_ids)
        != body.production_ref
        or scoped_location_binding_id(
            user_id=envelope.user_id, project_name=envelope.project_name, target_id=body.target_id
        )
        != body.id
    ):
        raise ValueError("binding core identity differs from the verified body and envelope")
    stable_body = body.model_dump(mode="json", exclude={"version"})
    return _digest(
        "binding_core",
        {
            "user_id": envelope.user_id,
            "project_name": envelope.project_name,
            "binding": stable_body,
            "scene_ref": envelope.scene_ref.model_dump(mode="json"),
            "target_ref": envelope.target_ref.model_dump(mode="json"),
            "ordered_source_claim_digests": [claim.claim_digest for claim in envelope.ordered_claims],
        },
    )


def binding_create_command_digest(body: Mapping[str, Any]) -> str:
    command = BindingCreateCommandV1.model_validate(body)
    return _digest("binding_create_command", command.model_dump(mode="json"))


def binding_create_result_digest(body: Mapping[str, Any]) -> str:
    result = BindingCreateResultV1.model_validate(body)
    return _digest("binding_create_result", result.model_dump(mode="json"))


def binding_snapshot_digest(body: Mapping[str, Any]) -> str:
    snapshot = BindingSnapshotV1.model_validate(body)
    return _digest("binding_snapshot", snapshot.model_dump(mode="json"))


__all__ = [
    "binding_body_digest",
    "binding_core_digest",
    "binding_create_command_digest",
    "binding_create_result_digest",
    "binding_envelope_digest",
    "binding_snapshot_digest",
    "frame_source_claim_digest",
    "scoped_location_binding_id",
    "source_group_ref",
]

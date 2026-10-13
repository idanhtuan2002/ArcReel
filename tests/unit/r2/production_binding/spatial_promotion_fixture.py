"""One binding-target V2 preview and receipt built on the frozen constraint set vector."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from r2.advanced_creative.digests import digest_canonical
from r2.contracts.advanced_creative import CanonicalJsonObject
from r2.contracts.spatial_promotion import binding_version_ref
from r2.production_binding.spatial_set import spatial_constraint_set_digest, spatial_constraint_set_id

SET_VECTOR = json.loads(
    (Path(__file__).resolve().parents[3] / "fixtures" / "r2" / "m8c_spatial_constraint_set_vector.json").read_text(
        encoding="utf-8"
    )
)
SET = SET_VECTOR["body"]
ISSUED = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
ENVELOPE_V1 = "sha256:" + "e" * 64
ENVELOPE_V2 = "sha256:" + "f" * 64


def preview_body() -> dict[str, Any]:
    impact = CanonicalJsonObject.model_validate(
        {"binding_version": {"from": 1, "to": 2}, "constraint_set_id": spatial_constraint_set_id(SET_VECTOR["digest"])}
    )
    selected = [constraint["assertion_id"] for constraint in SET["constraints"]]
    return {
        "schema_version": "2",
        "base_preview": {
            "preview_id": "preview-1",
            "preview_command_id": "preview-cmd-1",
            "project_name": SET["project_name"],
            "candidate_id": SET["candidate_id"],
            "candidate_revision": SET["candidate_revision"],
            "candidate_payload_digest": SET["candidate_payload_digest"],
            "target": {"kind": "PRODUCTION_BINDING", "target_ref": SET["binding_id"], "expected_target_version": 1},
            "expected_master_id": None,
            "expected_master_digest": None,
            "impact": impact.model_dump(mode="json"),
            "impact_digest": digest_canonical(impact),
            "authorization_scope": SET["user_id"],
            "issued_at": ISSUED.isoformat(),
            "expires_at": (ISSUED + timedelta(minutes=30)).isoformat(),
        },
        "binding": {
            "schema_version": "2",
            "binding_id": SET["binding_id"],
            "expected_binding_version": 1,
            "binding_envelope_digest": ENVELOPE_V1,
            "target_ref": {
                "target_type": "SHOT",
                "target_id": "take:shot-1",
                "registry_version": 1,
                "version_digest": "sha256:" + "7" * 64,
            },
            "selected_assertion_ids": selected,
            "proposal": SET,
            "proposal_digest": spatial_constraint_set_digest(SET),
            "pair_id": SET["pair_id"],
            "pair_version": SET["pair_version"],
            "pair_decision_digest": SET["pair_decision_digest"],
        },
    }


def receipt_body() -> dict[str, Any]:
    return {
        "schema_version": "2",
        "base_receipt": {
            "receipt_id": "receipt-1",
            "command_id": "promote-cmd-1",
            "project_name": SET["project_name"],
            "preview_digest": "sha256:" + "8" * 64,
            "candidate_id": SET["candidate_id"],
            "candidate_revision": SET["candidate_revision"],
            "target": {"kind": "PRODUCTION_BINDING", "target_ref": SET["binding_id"], "expected_target_version": 1},
            "result_artifact_ref": binding_version_ref(SET["binding_id"], 2),
            "result_master_id": None,
            "result_digest": ENVELOPE_V2,
            "promoted_at": (ISSUED + timedelta(minutes=5)).isoformat(),
        },
        "result": {
            "schema_version": "2",
            "binding_id": SET["binding_id"],
            "binding_version": 2,
            "binding_envelope_digest": ENVELOPE_V2,
            "constraint_set_id": spatial_constraint_set_id(SET_VECTOR["digest"]),
            "constraint_set_digest": SET_VECTOR["digest"],
        },
    }

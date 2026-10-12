"""Check internal agreement of public Governance custody copies."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from r2.contracts.governance_host_records import (
    HostRecordInvalid,
    ParsedApprovedDeploymentV1,
    ParsedCheckpointHighWaterV1,
    parse_approved_deployment,
    parse_checkpoint_high_water,
)
from r2.contracts.governance_verifier_registry import (
    ParsedVerifierRegistryV1,
    VerifierRegistryInvalid,
    parse_verifier_registry,
)
from r2.contracts.grant_checkpoint import CheckpointInvalid
from r2.governance.checkpoint_signature import VerifiedGrantCheckpointV1, verify_grant_checkpoint


class PublicCustodyMismatch(ValueError):
    """The public copies cannot establish one internally consistent checkpoint."""

    def __init__(self) -> None:
        super().__init__("public Governance custody is unavailable")


@dataclass(frozen=True)
class VerifiedPublicCustodySnapshotV1:
    approval: ParsedApprovedDeploymentV1
    registry: ParsedVerifierRegistryV1
    high_water: ParsedCheckpointHighWaterV1
    checkpoint: VerifiedGrantCheckpointV1


def validate_public_custody_snapshot(
    approved_raw: bytes, registry_raw: bytes, high_water_raw: bytes, checkpoint_raw: bytes
) -> VerifiedPublicCustodySnapshotV1:
    """Check public bytes; archive freshness and image identity require operator preflight."""

    try:
        approval = parse_approved_deployment(approved_raw)
        registry = parse_verifier_registry(registry_raw)
        high_water = parse_checkpoint_high_water(high_water_raw)
        approved = approval.body
        current = high_water.body
        if (
            approved.approval_sequence != 1
            or approved.deployment_id != registry.deployment_id
            or approved.deployment_id != current.deployment_id
            or approved.registry_sequence != registry.registry_sequence
            or approved.registry_file_digest != registry.registry_digest
            or approved.grant_event_key_id != registry.grant_event.key_id
            or approved.checkpoint_key_id != registry.grant_checkpoint.key_id
            or current.approved_deployment_digest != approval.record_digest
            or current.signer_key_id != registry.grant_checkpoint.key_id
            or current.checkpoint_file_digest != "sha256:" + hashlib.sha256(checkpoint_raw).hexdigest()
        ):
            raise PublicCustodyMismatch
        checkpoint = verify_grant_checkpoint(
            checkpoint_raw,
            deployment_id=approved.deployment_id,
            key_id=registry.grant_checkpoint.key_id,
            public_key=registry.grant_checkpoint.public_key,
        )
        if (
            current.checkpoint_sequence != checkpoint.body.checkpoint_sequence
            or current.checkpoint_body_digest != checkpoint.checkpoint_digest
            or current.previous_checkpoint_body_digest != checkpoint.body.previous_checkpoint_digest
            or current.checkpoint_issued_at != checkpoint.body.issued_at
        ):
            raise PublicCustodyMismatch
    except (HostRecordInvalid, VerifierRegistryInvalid, CheckpointInvalid):
        raise PublicCustodyMismatch from None
    return VerifiedPublicCustodySnapshotV1(approval, registry, high_water, checkpoint)


__all__ = ["PublicCustodyMismatch", "VerifiedPublicCustodySnapshotV1", "validate_public_custody_snapshot"]

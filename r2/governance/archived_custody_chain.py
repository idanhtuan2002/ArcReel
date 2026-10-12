"""Validate retained Governance checkpoint history against public copies."""

from __future__ import annotations

from collections.abc import Sequence

from r2.governance.public_custody_snapshot import (
    PublicCustodyMismatch,
    VerifiedPublicCustodySnapshotV1,
    validate_public_custody_snapshot,
)


class ArchivedCustodyInvalid(ValueError):
    """Retained and public Governance custody bytes do not form one chain."""

    def __init__(self) -> None:
        super().__init__("archived Governance custody is unavailable")


def validate_archived_custody_chain(
    approved_raw: bytes,
    registry_raw: bytes,
    history: Sequence[tuple[bytes, bytes]],
    public: tuple[bytes, bytes, bytes, bytes],
) -> VerifiedPublicCustodySnapshotV1:
    """Check caller-supplied archive bytes; filesystem custody remains separate."""

    if not history or public[:2] != (approved_raw, registry_raw) or public[2:] != history[-1]:
        raise ArchivedCustodyInvalid
    previous: VerifiedPublicCustodySnapshotV1 | None = None
    try:
        for sequence, (high_water_raw, checkpoint_raw) in enumerate(history, start=1):
            current = validate_public_custody_snapshot(approved_raw, registry_raw, high_water_raw, checkpoint_raw)
            if current.high_water.checkpoint_sequence != sequence:
                raise ArchivedCustodyInvalid
            if previous is not None:
                if (
                    current.high_water.body.previous_high_water_digest != previous.high_water.record_digest
                    or current.high_water.body.previous_checkpoint_body_digest != previous.checkpoint.checkpoint_digest
                ):
                    raise ArchivedCustodyInvalid
                old_heads = {
                    (head.user_id, head.project_name, head.principal): head for head in previous.checkpoint.body.heads
                }
                new_heads = {
                    (head.user_id, head.project_name, head.principal): head for head in current.checkpoint.body.heads
                }
                for scope, old_head in old_heads.items():
                    new_head = new_heads.get(scope)
                    if (
                        new_head is None
                        or new_head.head_sequence < old_head.head_sequence
                        or (
                            new_head.head_sequence == old_head.head_sequence
                            and new_head.head_event_digest != old_head.head_event_digest
                        )
                    ):
                        raise ArchivedCustodyInvalid
            previous = current
    except PublicCustodyMismatch:
        raise ArchivedCustodyInvalid from None
    if previous is None:
        raise ArchivedCustodyInvalid
    return previous


__all__ = ["ArchivedCustodyInvalid", "validate_archived_custody_chain"]

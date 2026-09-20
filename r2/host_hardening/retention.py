"""Shared candidate-deletion guard for M7-B (H3-H4).

``CandidateRetentionPolicy`` is the one gate every existing candidate/media
deletion route must call before removing bytes. It never invents its own
notion of "in use" -- it asks each protected-reference owner (master head,
active attempt, retained promotion receipt, incomplete backup set) directly,
so retention policy stays exactly as current as those owners' own state.
"""

from __future__ import annotations

from pathlib import Path

from r2.host_hardening.ports import (
    ActiveAttemptReferenceCheck,
    IncompleteBackupReferenceCheck,
    MasterHeadReferenceCheck,
    RetainedReceiptReferenceCheck,
)


class CandidateRetentionPolicy:
    def __init__(
        self,
        *,
        master_head: MasterHeadReferenceCheck,
        active_attempt: ActiveAttemptReferenceCheck,
        retained_receipt: RetainedReceiptReferenceCheck,
        incomplete_backup: IncompleteBackupReferenceCheck,
    ) -> None:
        self._master_head = master_head
        self._active_attempt = active_attempt
        self._retained_receipt = retained_receipt
        self._incomplete_backup = incomplete_backup

    async def can_delete(self, *, user_id: str, project_name: str, candidate_id: str) -> bool:
        if await self._master_head.references_candidate(
            user_id=user_id, project_name=project_name, candidate_id=candidate_id
        ):
            return False
        if await self._active_attempt.has_active_attempt_for_candidate(
            user_id=user_id, project_name=project_name, candidate_id=candidate_id
        ):
            return False
        if await self._retained_receipt.has_retained_receipt_for_candidate(
            user_id=user_id, project_name=project_name, candidate_id=candidate_id
        ):
            return False
        return not await self._incomplete_backup.has_incomplete_backup_referencing(
            user_id=user_id, project_name=project_name, candidate_id=candidate_id
        )


async def delete_candidate_if_permitted(
    *, policy: CandidateRetentionPolicy, user_id: str, project_name: str, candidate_id: str, object_ref: Path
) -> bool:
    """The one sanctioned way to remove a candidate object's bytes.

    ``scripts/r2/verify_m7_scope.py``'s architecture check (spec section 6,
    "reject bypasses architecturally") fails closed if any other code path
    under the candidate media root calls ``Path.unlink``/``os.remove``/
    ``os.replace`` directly instead of going through this function. Returns
    ``False`` without touching the filesystem when the policy still protects
    the candidate; the caller decides what "not deletable yet" means for its
    own flow (retry later, surface to an operator, etc.).
    """

    if not await policy.can_delete(user_id=user_id, project_name=project_name, candidate_id=candidate_id):
        return False
    object_ref.unlink(missing_ok=True)  # noqa: ASYNC240 -- single local-file delete, not a blocking I/O concern
    return True


__all__ = ["CandidateRetentionPolicy", "delete_candidate_if_permitted"]

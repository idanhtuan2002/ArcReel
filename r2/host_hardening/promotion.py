"""Atomic master promotion (M7-B, H3-H4 design spec section 6).

``AtomicPromotionService.promote`` is the only way a candidate becomes the
master for an artifact. It verifies the candidate exists and belongs to the
exact scope, replays an exact-command retry idempotently, CASes the master
pointer via two independent DB-level guards (the append-only version's unique
constraint, then the pointer's expected-version-guarded update), and appends
the promotion receipt and durable outbox event in the same unit of work as the
caller's ``commit``. A CAS conflict never silently retries or picks a winner
here -- the caller decides whether to re-plan against the new current version.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime

from r2.contracts.common import ensure_json_value
from r2.contracts.fingerprints import canonical_json_bytes
from r2.contracts.host_hardening import MasterHeadSnapshot, PromotionReceipt
from r2.host_hardening.ports import CandidateObjectPort, MasterAuthorityPort, PromotionReceiptPort


class CandidateNotFoundError(LookupError):
    """No candidate with this ID exists in this scope."""


class CandidateArtifactMismatchError(ValueError):
    """The candidate was prepared for a different ``artifact_key``."""


class PromotionExpectedVersionConflictError(RuntimeError):
    """``expected_master_version`` no longer matches the current pointer."""


class PromotionReceiptReplayMismatchError(RuntimeError):
    """This ``command_id`` was already used for a different intended promotion."""


async def _no_commit() -> None:
    return None


def _command_digest(*, artifact_key: str, candidate_id: str, expected_master_version: int, approval_record: str) -> str:
    payload = ensure_json_value(
        {
            "artifact_key": artifact_key,
            "candidate_id": candidate_id,
            "expected_master_version": expected_master_version,
            "approval_record": approval_record,
        }
    )
    return "sha256:" + hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


class AtomicPromotionService:
    def __init__(
        self,
        *,
        candidates: CandidateObjectPort,
        authorities: MasterAuthorityPort,
        receipts: PromotionReceiptPort,
        clock: Callable[[], datetime],
        master_head_version_id_factory: Callable[[], str] = lambda: str(uuid.uuid4()),
        commit: Callable[[], Awaitable[None]] = _no_commit,
    ) -> None:
        self._candidates = candidates
        self._authorities = authorities
        self._receipts = receipts
        self._clock = clock
        self._master_head_version_id_factory = master_head_version_id_factory
        self._commit = commit

    async def promote(
        self,
        *,
        user_id: str,
        project_name: str,
        artifact_key: str,
        candidate_id: str,
        expected_master_version: int,
        approval_record: str,
        command_id: str,
    ) -> MasterHeadSnapshot:
        digest = _command_digest(
            artifact_key=artifact_key,
            candidate_id=candidate_id,
            expected_master_version=expected_master_version,
            approval_record=approval_record,
        )
        existing_receipt = await self._receipts.get_exact(
            user_id=user_id, project_name=project_name, artifact_key=artifact_key, command_id=command_id
        )
        if existing_receipt is not None:
            if existing_receipt.command_digest != digest:
                raise PromotionReceiptReplayMismatchError(
                    f"command {command_id!r} was already used for a different promotion in this scope"
                )
            current = await self._authorities.get_current(
                user_id=user_id, project_name=project_name, artifact_key=artifact_key
            )
            if current is None or current.master_version != existing_receipt.master_version:
                raise PromotionReceiptReplayMismatchError(
                    f"receipt for command {command_id!r} no longer matches the current master head"
                )
            return current

        candidate = await self._candidates.get_exact(
            user_id=user_id, project_name=project_name, candidate_id=candidate_id
        )
        if candidate is None:
            raise CandidateNotFoundError(f"no candidate {candidate_id!r} in this scope")
        if candidate.artifact_key != artifact_key:
            raise CandidateArtifactMismatchError(
                f"candidate {candidate_id!r} was prepared for {candidate.artifact_key!r}, not {artifact_key!r}"
            )

        current_version = await self._authorities.get_current_version(
            user_id=user_id, project_name=project_name, artifact_key=artifact_key
        )
        if current_version != expected_master_version:
            raise PromotionExpectedVersionConflictError(
                f"{artifact_key!r} is at version {current_version}, expected {expected_master_version}"
            )

        new_version = current_version + 1
        snapshot = MasterHeadSnapshot(
            artifact_key=artifact_key,
            master_version=new_version,
            candidate_id=candidate_id,
            object_ref=candidate.object_ref,
            content_digest=candidate.content_digest,
            approval_record=approval_record,
        )
        now = self._clock()
        await self._authorities.insert_head_version(
            user_id=user_id,
            project_name=project_name,
            master_head_version_id=self._master_head_version_id_factory(),
            snapshot=snapshot,
            promoted_at=now,
        )
        await self._authorities.advance_head(
            user_id=user_id,
            project_name=project_name,
            artifact_key=artifact_key,
            expected_current_version=current_version,
            new_version=new_version,
        )
        await self._receipts.add(
            user_id=user_id,
            project_name=project_name,
            receipt=PromotionReceipt(
                artifact_key=artifact_key,
                command_id=command_id,
                command_digest=digest,
                candidate_id=candidate_id,
                master_version=new_version,
                approval_record=approval_record,
                created_at=now,
            ),
        )
        await self._authorities.append_promoted_event(user_id=user_id, project_name=project_name, snapshot=snapshot)
        await self._commit()
        return snapshot


__all__ = [
    "AtomicPromotionService",
    "CandidateArtifactMismatchError",
    "CandidateNotFoundError",
    "PromotionExpectedVersionConflictError",
    "PromotionReceiptReplayMismatchError",
]

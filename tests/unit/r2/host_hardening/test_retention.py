"""CandidateRetentionPolicy: one guard shared by every candidate deletion route.

Each protected reference kind is exercised through its own fake so a failure
here points at exactly which owner still holds the candidate.
"""

from __future__ import annotations

from r2.host_hardening.retention import CandidateRetentionPolicy

USER = "u1"
PROJECT = "demo"
CANDIDATE = "cand-1"


class _FixedCheck:
    def __init__(self, *, result: bool) -> None:
        self._result = result
        self.calls: list[dict[str, str]] = []

    async def _record_and_return(self, **kwargs: str) -> bool:
        self.calls.append(kwargs)
        return self._result


class _MasterHead(_FixedCheck):
    async def references_candidate(self, *, user_id: str, project_name: str, candidate_id: str) -> bool:
        return await self._record_and_return(user_id=user_id, project_name=project_name, candidate_id=candidate_id)


class _ActiveAttempt(_FixedCheck):
    async def has_active_attempt_for_candidate(self, *, user_id: str, project_name: str, candidate_id: str) -> bool:
        return await self._record_and_return(user_id=user_id, project_name=project_name, candidate_id=candidate_id)


class _RetainedReceipt(_FixedCheck):
    async def has_retained_receipt_for_candidate(self, *, user_id: str, project_name: str, candidate_id: str) -> bool:
        return await self._record_and_return(user_id=user_id, project_name=project_name, candidate_id=candidate_id)


class _IncompleteBackup(_FixedCheck):
    async def has_incomplete_backup_referencing(self, *, user_id: str, project_name: str, candidate_id: str) -> bool:
        return await self._record_and_return(user_id=user_id, project_name=project_name, candidate_id=candidate_id)


def _policy(
    *,
    master_referenced: bool = False,
    attempt_active: bool = False,
    receipt_retained: bool = False,
    backup_incomplete: bool = False,
) -> tuple[CandidateRetentionPolicy, dict[str, _FixedCheck]]:
    checks = {
        "master_head": _MasterHead(result=master_referenced),
        "active_attempt": _ActiveAttempt(result=attempt_active),
        "retained_receipt": _RetainedReceipt(result=receipt_retained),
        "incomplete_backup": _IncompleteBackup(result=backup_incomplete),
    }
    policy = CandidateRetentionPolicy(
        master_head=checks["master_head"],
        active_attempt=checks["active_attempt"],
        retained_receipt=checks["retained_receipt"],
        incomplete_backup=checks["incomplete_backup"],
    )
    return policy, checks


async def test_can_delete_true_when_no_owner_references_the_candidate() -> None:
    policy, checks = _policy()

    result = await policy.can_delete(user_id=USER, project_name=PROJECT, candidate_id=CANDIDATE)

    assert result is True
    for check in checks.values():
        assert check.calls == [{"user_id": USER, "project_name": PROJECT, "candidate_id": CANDIDATE}]


async def test_can_delete_false_when_a_master_head_references_the_candidate() -> None:
    policy, _ = _policy(master_referenced=True)
    assert await policy.can_delete(user_id=USER, project_name=PROJECT, candidate_id=CANDIDATE) is False


async def test_can_delete_false_when_an_attempt_is_still_active_for_the_candidate() -> None:
    policy, _ = _policy(attempt_active=True)
    assert await policy.can_delete(user_id=USER, project_name=PROJECT, candidate_id=CANDIDATE) is False


async def test_can_delete_false_when_a_promotion_receipt_is_retained() -> None:
    policy, _ = _policy(receipt_retained=True)
    assert await policy.can_delete(user_id=USER, project_name=PROJECT, candidate_id=CANDIDATE) is False


async def test_can_delete_false_when_an_incomplete_backup_set_references_the_candidate() -> None:
    policy, _ = _policy(backup_incomplete=True)
    assert await policy.can_delete(user_id=USER, project_name=PROJECT, candidate_id=CANDIDATE) is False


async def test_can_delete_short_circuits_on_the_first_blocking_owner() -> None:
    # The master-head check is authoritative and cheapest; a positive result must
    # not require probing the other three owners before refusing deletion.
    policy, checks = _policy(master_referenced=True)

    await policy.can_delete(user_id=USER, project_name=PROJECT, candidate_id=CANDIDATE)

    assert checks["master_head"].calls
    assert checks["active_attempt"].calls == []
    assert checks["retained_receipt"].calls == []
    assert checks["incomplete_backup"].calls == []

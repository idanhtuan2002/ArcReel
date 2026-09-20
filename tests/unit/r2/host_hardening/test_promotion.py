"""AtomicPromotionService against pure fakes: candidate scope checks, the CAS
boundary, exact command replay, and conflicting replay."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

import pytest

from r2.contracts.host_hardening import MasterHeadSnapshot, PromotionReceipt, VerifiedCandidateObject
from r2.host_hardening.promotion import (
    AtomicPromotionService,
    CandidateArtifactMismatchError,
    CandidateNotFoundError,
    PromotionExpectedVersionConflictError,
    PromotionReceiptReplayMismatchError,
)

USER = "u1"
PROJECT = "demo"
ARTIFACT_KEY = "videos/E1S01"
NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


def _candidate(candidate_id: str, artifact_key: str = ARTIFACT_KEY) -> VerifiedCandidateObject:
    return VerifiedCandidateObject(
        candidate_id=candidate_id,
        project_name=PROJECT,
        artifact_key=artifact_key,
        object_ref=f"/data/{PROJECT}/videos/{candidate_id}.mp4",
        byte_size=1024,
        content_digest="sha256:" + candidate_id,
        media_probe_digest="sha256:probe-" + candidate_id,
    )


class _FakeCandidates:
    def __init__(self, *candidates: VerifiedCandidateObject) -> None:
        self._by_id = {c.candidate_id: c for c in candidates}

    async def get_exact(self, *, user_id: str, project_name: str, candidate_id: str) -> VerifiedCandidateObject | None:
        del user_id, project_name
        return self._by_id.get(candidate_id)


class _FakeAuthorities:
    def __init__(self, *, current_version: int = 0) -> None:
        self.current_version = current_version
        self.current_snapshot: MasterHeadSnapshot | None = None
        self.inserted_versions: list[MasterHeadSnapshot] = []
        self.advanced: list[tuple[int, int]] = []
        self.events: list[MasterHeadSnapshot] = []

    async def get_current(self, *, user_id: str, project_name: str, artifact_key: str) -> MasterHeadSnapshot | None:
        del user_id, project_name, artifact_key
        return self.current_snapshot

    async def get_current_version(self, *, user_id: str, project_name: str, artifact_key: str) -> int:
        del user_id, project_name, artifact_key
        return self.current_version

    async def insert_head_version(self, *, user_id, project_name, master_head_version_id, snapshot, promoted_at):
        del user_id, project_name, master_head_version_id, promoted_at
        self.inserted_versions.append(snapshot)

    async def advance_head(self, *, user_id, project_name, artifact_key, expected_current_version, new_version):
        del user_id, project_name, artifact_key
        self.advanced.append((expected_current_version, new_version))
        self.current_version = new_version
        self.current_snapshot = self.inserted_versions[-1]

    async def append_promoted_event(self, *, user_id, project_name, snapshot) -> None:
        del user_id, project_name
        self.events.append(snapshot)


class _FakeReceipts:
    def __init__(self) -> None:
        self._by_key: dict[tuple[str, str], PromotionReceipt] = {}

    async def get_exact(
        self, *, user_id: str, project_name: str, artifact_key: str, command_id: str
    ) -> PromotionReceipt | None:
        del user_id, project_name
        return self._by_key.get((artifact_key, command_id))

    async def add(self, *, user_id: str, project_name: str, receipt: PromotionReceipt) -> None:
        del user_id, project_name
        self._by_key[(receipt.artifact_key, receipt.command_id)] = receipt


def _service(
    *,
    candidates: _FakeCandidates,
    authorities: _FakeAuthorities,
    receipts: _FakeReceipts,
    notify: Callable[[], None] = lambda: None,
) -> AtomicPromotionService:
    return AtomicPromotionService(
        candidates=candidates, authorities=authorities, receipts=receipts, clock=lambda: NOW, notify=notify
    )


async def test_promote_appends_a_version_advances_the_head_and_records_a_receipt() -> None:
    candidates = _FakeCandidates(_candidate("cand-1"))
    authorities = _FakeAuthorities()
    receipts = _FakeReceipts()
    service = _service(candidates=candidates, authorities=authorities, receipts=receipts)

    snapshot = await service.promote(
        user_id=USER,
        project_name=PROJECT,
        artifact_key=ARTIFACT_KEY,
        candidate_id="cand-1",
        expected_master_version=0,
        approval_record="approval-1",
        command_id="cmd-1",
    )

    assert snapshot.master_version == 1
    assert snapshot.candidate_id == "cand-1"
    assert authorities.advanced == [(0, 1)]
    assert authorities.events == [snapshot]
    stored = await receipts.get_exact(user_id=USER, project_name=PROJECT, artifact_key=ARTIFACT_KEY, command_id="cmd-1")
    assert stored is not None
    assert stored.candidate_id == "cand-1"
    assert stored.master_version == 1


async def test_promote_rejects_an_unknown_candidate() -> None:
    service = _service(candidates=_FakeCandidates(), authorities=_FakeAuthorities(), receipts=_FakeReceipts())

    with pytest.raises(CandidateNotFoundError):
        await service.promote(
            user_id=USER,
            project_name=PROJECT,
            artifact_key=ARTIFACT_KEY,
            candidate_id="cand-1",
            expected_master_version=0,
            approval_record="approval-1",
            command_id="cmd-1",
        )


async def test_promote_rejects_a_candidate_prepared_for_a_different_artifact() -> None:
    candidates = _FakeCandidates(_candidate("cand-1", artifact_key="videos/other"))
    service = _service(candidates=candidates, authorities=_FakeAuthorities(), receipts=_FakeReceipts())

    with pytest.raises(CandidateArtifactMismatchError):
        await service.promote(
            user_id=USER,
            project_name=PROJECT,
            artifact_key=ARTIFACT_KEY,
            candidate_id="cand-1",
            expected_master_version=0,
            approval_record="approval-1",
            command_id="cmd-1",
        )


async def test_promote_rejects_a_stale_expected_master_version() -> None:
    candidates = _FakeCandidates(_candidate("cand-1"))
    authorities = _FakeAuthorities(current_version=3)
    service = _service(candidates=candidates, authorities=authorities, receipts=_FakeReceipts())

    with pytest.raises(PromotionExpectedVersionConflictError):
        await service.promote(
            user_id=USER,
            project_name=PROJECT,
            artifact_key=ARTIFACT_KEY,
            candidate_id="cand-1",
            expected_master_version=0,
            approval_record="approval-1",
            command_id="cmd-1",
        )


async def test_promote_is_idempotent_for_an_exact_command_replay() -> None:
    candidates = _FakeCandidates(_candidate("cand-1"))
    authorities = _FakeAuthorities()
    receipts = _FakeReceipts()
    service = _service(candidates=candidates, authorities=authorities, receipts=receipts)
    first = await service.promote(
        user_id=USER,
        project_name=PROJECT,
        artifact_key=ARTIFACT_KEY,
        candidate_id="cand-1",
        expected_master_version=0,
        approval_record="approval-1",
        command_id="cmd-1",
    )

    second = await service.promote(
        user_id=USER,
        project_name=PROJECT,
        artifact_key=ARTIFACT_KEY,
        candidate_id="cand-1",
        expected_master_version=0,
        approval_record="approval-1",
        command_id="cmd-1",
    )

    assert second == first
    assert len(authorities.advanced) == 1  # never re-promoted


async def test_promote_rejects_a_conflicting_replay_of_the_same_command_id() -> None:
    candidates = _FakeCandidates(_candidate("cand-1"), _candidate("cand-2"))
    authorities = _FakeAuthorities()
    receipts = _FakeReceipts()
    service = _service(candidates=candidates, authorities=authorities, receipts=receipts)
    await service.promote(
        user_id=USER,
        project_name=PROJECT,
        artifact_key=ARTIFACT_KEY,
        candidate_id="cand-1",
        expected_master_version=0,
        approval_record="approval-1",
        command_id="cmd-1",
    )

    with pytest.raises(PromotionReceiptReplayMismatchError):
        await service.promote(
            user_id=USER,
            project_name=PROJECT,
            artifact_key=ARTIFACT_KEY,
            candidate_id="cand-2",
            expected_master_version=0,
            approval_record="approval-1",
            command_id="cmd-1",
        )


async def test_promote_calls_notify_only_after_the_commit() -> None:
    candidates = _FakeCandidates(_candidate("cand-1"))
    authorities = _FakeAuthorities()
    receipts = _FakeReceipts()
    calls: list[str] = []

    async def _commit() -> None:
        calls.append("commit")

    def _notify() -> None:
        calls.append("notify")

    service = AtomicPromotionService(
        candidates=candidates,
        authorities=authorities,
        receipts=receipts,
        clock=lambda: NOW,
        commit=_commit,
        notify=_notify,
    )

    await service.promote(
        user_id=USER,
        project_name=PROJECT,
        artifact_key=ARTIFACT_KEY,
        candidate_id="cand-1",
        expected_master_version=0,
        approval_record="approval-1",
        command_id="cmd-1",
    )

    assert calls == ["commit", "notify"]


async def test_promote_does_not_notify_on_a_conflicting_replay() -> None:
    candidates = _FakeCandidates(_candidate("cand-1"), _candidate("cand-2"))
    authorities = _FakeAuthorities()
    receipts = _FakeReceipts()
    notified = False

    def _notify() -> None:
        nonlocal notified
        notified = True

    service = _service(candidates=candidates, authorities=authorities, receipts=receipts, notify=_notify)
    await service.promote(
        user_id=USER,
        project_name=PROJECT,
        artifact_key=ARTIFACT_KEY,
        candidate_id="cand-1",
        expected_master_version=0,
        approval_record="approval-1",
        command_id="cmd-1",
    )
    notified = False  # reset after the real promotion's own (expected) notify

    with pytest.raises(PromotionReceiptReplayMismatchError):
        await service.promote(
            user_id=USER,
            project_name=PROJECT,
            artifact_key=ARTIFACT_KEY,
            candidate_id="cand-2",
            expected_master_version=0,
            approval_record="approval-1",
            command_id="cmd-1",
        )

    assert notified is False

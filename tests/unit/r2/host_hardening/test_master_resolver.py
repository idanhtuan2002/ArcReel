"""DatabaseMasterResolver: authoritative reads, failing closed on legacy
projection divergence rather than silently picking a side."""

from __future__ import annotations

import pytest

from r2.contracts.host_hardening import MasterHeadSnapshot
from r2.host_hardening.master_resolver import DatabaseMasterResolver, MasterDivergedError

USER = "u1"
PROJECT = "demo"
ARTIFACT_KEY = "videos/E1S01"

_SNAPSHOT = MasterHeadSnapshot(
    artifact_key=ARTIFACT_KEY,
    master_version=1,
    candidate_id="cand-1",
    object_ref="/data/demo/videos/cand-1.mp4",
    content_digest="sha256:cand-1",
    approval_record="approval-1",
)


class _FakeAuthorities:
    def __init__(self, *, current: MasterHeadSnapshot | None) -> None:
        self._current = current

    async def get_current(self, *, user_id: str, project_name: str, artifact_key: str) -> MasterHeadSnapshot | None:
        del user_id, project_name, artifact_key
        return self._current


class _FakeLegacyProjection:
    def __init__(self, *, selected_candidate_id: str | None) -> None:
        self._selected_candidate_id = selected_candidate_id

    async def get_selected_candidate_id(self, *, user_id: str, project_name: str, artifact_key: str) -> str | None:
        del user_id, project_name, artifact_key
        return self._selected_candidate_id


async def test_get_exact_returns_the_database_head_with_no_legacy_projection() -> None:
    resolver = DatabaseMasterResolver(authorities=_FakeAuthorities(current=_SNAPSHOT))
    result = await resolver.get_exact(user_id=USER, project_name=PROJECT, artifact_key=ARTIFACT_KEY)
    assert result == _SNAPSHOT


async def test_get_exact_returns_none_when_nothing_has_been_promoted_yet() -> None:
    resolver = DatabaseMasterResolver(authorities=_FakeAuthorities(current=None))
    result = await resolver.get_exact(user_id=USER, project_name=PROJECT, artifact_key=ARTIFACT_KEY)
    assert result is None


async def test_get_exact_passes_when_the_legacy_projection_agrees() -> None:
    resolver = DatabaseMasterResolver(
        authorities=_FakeAuthorities(current=_SNAPSHOT),
        legacy_projection=_FakeLegacyProjection(selected_candidate_id="cand-1"),
    )
    result = await resolver.get_exact(user_id=USER, project_name=PROJECT, artifact_key=ARTIFACT_KEY)
    assert result == _SNAPSHOT


async def test_get_exact_is_silent_when_the_legacy_projection_has_no_opinion() -> None:
    resolver = DatabaseMasterResolver(
        authorities=_FakeAuthorities(current=_SNAPSHOT),
        legacy_projection=_FakeLegacyProjection(selected_candidate_id=None),
    )
    result = await resolver.get_exact(user_id=USER, project_name=PROJECT, artifact_key=ARTIFACT_KEY)
    assert result == _SNAPSHOT


async def test_get_exact_fails_closed_when_the_legacy_projection_disagrees() -> None:
    resolver = DatabaseMasterResolver(
        authorities=_FakeAuthorities(current=_SNAPSHOT),
        legacy_projection=_FakeLegacyProjection(selected_candidate_id="cand-stale"),
    )
    with pytest.raises(MasterDivergedError, match="M7_MASTER_DIVERGED"):
        await resolver.get_exact(user_id=USER, project_name=PROJECT, artifact_key=ARTIFACT_KEY)


async def test_get_exact_fails_closed_when_legacy_has_a_candidate_but_db_has_none() -> None:
    resolver = DatabaseMasterResolver(
        authorities=_FakeAuthorities(current=None),
        legacy_projection=_FakeLegacyProjection(selected_candidate_id="cand-legacy-only"),
    )
    with pytest.raises(MasterDivergedError, match="M7_MASTER_DIVERGED"):
        await resolver.get_exact(user_id=USER, project_name=PROJECT, artifact_key=ARTIFACT_KEY)

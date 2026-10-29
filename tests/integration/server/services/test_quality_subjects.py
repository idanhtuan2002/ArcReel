"""The server-side M10 subject resolver over real master authority and a real project manifest."""

from __future__ import annotations

import pytest

from r2.advanced_creative.digests import canonical_json_bytes
from r2.quality.errors import SubjectStaleError
from server.services.quality_runs import _subject_authoritative
from server.services.quality_subjects import resolve_assessed_subject
from tests.integration.server.services.test_quality_runs import closure_host as closure_host
from tests.integration.server.services.test_quality_runs import subject_of, write_manifest


async def _resolve(env, key: str | None = None):
    async with env["factory"]() as session:
        return await resolve_assessed_subject(
            session,
            env["project"],
            user_id="default",
            project_name="project",
            root_artifact_key=key or env["root"].artifact_key,
        )


async def test_the_resolved_subject_is_the_accepted_fixture_subject_and_is_authoritative(closure_host) -> None:
    env = closure_host
    resolved = await _resolve(env)
    assert canonical_json_bytes(resolved) == canonical_json_bytes(subject_of(env))
    async with env["factory"]() as session:
        assert await _subject_authoritative(session, env["project"], resolved) is True


async def test_an_approval_record_that_disagrees_with_the_master_head_is_stale(closure_host) -> None:
    env = closure_host
    body = subject_of(env).master_binding.metadata_snapshots[0].body.model_dump(mode="json")
    write_manifest(
        env["project"],
        subject_of(env),
        change={"approved_master": body["approved_master"] | {"approval_record": "APR-other"}},
    )
    with pytest.raises(SubjectStaleError):
        await _resolve(env)


async def test_a_root_without_a_master_head_is_stale(closure_host) -> None:
    from r2.artifact_identity import episode_video_key

    with pytest.raises(SubjectStaleError):
        await _resolve(closure_host, episode_video_key(9, "FINAL"))

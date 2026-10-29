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


def _rewrite(env, artifact_key: str, change) -> None:
    """Replace one artifact's manifest metadata body with `change(body)`."""
    from lib.artifact_manifest import ArtifactKey, ArtifactManifestEntry, ProjectArtifactManifestAdapter
    from r2.contracts.quality import decode_episode_video_key

    subject = subject_of(env)
    snapshot = next(s for s in subject.master_binding.metadata_snapshots if s.artifact_key == artifact_key)
    episode, resource = decode_episode_video_key(artifact_key)
    ProjectArtifactManifestAdapter(env["project"]).put_entry(
        ArtifactKey.episode_video(episode, resource),
        ArtifactManifestEntry(
            artifact_path=f"videos/episode_{episode}/{resource}.mp4",
            basis_digest="sha256-v1:" + "e" * 64,
            r2=change(snapshot.body.model_dump(mode="json")),
        ),
    )


async def test_a_non_master_dependency_stays_in_the_metadata_and_creates_no_edge(closure_host) -> None:
    env = closure_host
    root = env["root"].artifact_key
    claim = {"ref": "claim:source-1", "version": "1", "fingerprint": "sha256:" + "c" * 64}
    _rewrite(env, root, lambda body: body | {"direct_dependencies": [*body["direct_dependencies"], claim]})
    resolved = await _resolve(env)
    assert resolved.master_binding.dependency_edges == subject_of(env).master_binding.dependency_edges
    body = next(s for s in resolved.master_binding.metadata_snapshots if s.artifact_key == root).body.model_dump(
        mode="json"
    )
    assert claim["ref"] in [dependency["ref"] for dependency in body["direct_dependencies"]]


async def test_a_dependency_fingerprint_that_is_not_the_child_master_is_stale(closure_host) -> None:
    env = closure_host

    def wrong(body):
        return body | {
            "direct_dependencies": [
                dependency | {"fingerprint": "sha256:" + "f" * 64}
                if dependency["ref"].startswith("master:")
                else dependency
                for dependency in body["direct_dependencies"]
            ]
        }

    _rewrite(env, env["root"].artifact_key, wrong)
    with pytest.raises(SubjectStaleError):
        await _resolve(env)


async def test_a_master_dependency_without_a_head_is_stale(closure_host) -> None:
    env = closure_host
    missing = {"ref": "master:SH09", "version": "CAND-SH09-V1@1", "fingerprint": "sha256:" + "9" * 64}
    _rewrite(
        env,
        env["root"].artifact_key,
        lambda body: body | {"direct_dependencies": [*body["direct_dependencies"], missing]},
    )
    with pytest.raises(SubjectStaleError):
        await _resolve(env)


async def test_a_manifest_selection_that_diverges_from_the_database_master_is_stale(closure_host) -> None:
    env = closure_host
    _rewrite(
        env,
        env["root"].artifact_key,
        lambda body: body | {"approved_master": body["approved_master"] | {"selected_candidate_id": "CAND-OTHER"}},
    )
    with pytest.raises(SubjectStaleError):
        await _resolve(env)

"""Server-side `AssessedSubject` for an approved master root (M10-C).

The closure is exactly the accepted `MasterBindingV1` one: from the root, only `master:` dependency refs become
same-episode edges; every member's head is the database master (with the legacy file projection agreeing) and its
metadata is the manifest's normalized R2 body. The contract validators decide coherence (ShotSpec children, version
and fingerprint linkage, cycles, reachability); any refusal is `M10_SUBJECT_STALE`. The services still verify the
subject against authority and lock its masters, so this module never widens what a request may claim.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

import r2.contracts.quality as q
from lib.artifact_manifest import ArtifactManifestError, ProjectArtifactManifestAdapter
from lib.db.repositories.host_hardening import MasterAuthorityRepository
from r2.artifact_identity import decode_episode_video_key, episode_video_key
from r2.contracts.artifact_metadata import R2ArtifactMetadata
from r2.host_hardening.master_resolver import DatabaseMasterResolver, MasterDivergedError
from r2.quality.digests import compute_digest, verify_caches
from r2.quality.errors import SubjectStaleError
from server.services.master_authority import file_master_projection

_PLACEHOLDER_DIGEST = "sha256:" + "0" * 64
_MASTER_REF = "master:"


def _manifest_bodies(project_root: Path) -> dict[str, dict[str, Any]]:
    entries = ProjectArtifactManifestAdapter(project_root).snapshot_entries()
    return {
        key.encode(): R2ArtifactMetadata.model_validate(entry.r2).model_dump(mode="json")
        for key, entry in entries.items()
        if entry.r2 is not None
    }


def _media_digest(value: str) -> str:
    return "sha256:" + value.removeprefix("sha256:").lower()


async def resolve_assessed_subject(
    session: AsyncSession, project_root: Path, *, user_id: str, project_name: str, root_artifact_key: str
) -> q.AssessedSubject:
    """The subject of `root_artifact_key` as the current database masters and manifest describe it."""
    try:
        bodies = await asyncio.to_thread(_manifest_bodies, project_root)
    except (ArtifactManifestError, OSError, ValueError):
        raise SubjectStaleError() from None
    resolver = DatabaseMasterResolver(
        authorities=MasterAuthorityRepository(session), legacy_projection=file_master_projection(project_root, session)
    )
    heads: dict[str, q.MasterHeadSnapshot] = {}
    edges: list[dict[str, str]] = []
    pending = [root_artifact_key]
    try:
        while pending:
            key = pending.pop()
            if key in heads:
                continue
            body = bodies.get(key)
            head = await resolver.get_exact(user_id=user_id, project_name=project_name, artifact_key=key)
            approved = None if body is None else body.get("approved_master")
            if head is None or approved is None or approved.get("approval_record") != head.approval_record:
                raise SubjectStaleError()
            heads[key] = head
            episode, _ = decode_episode_video_key(key)
            for dependency in body["direct_dependencies"] if body is not None else ():
                ref = dependency["ref"]
                if ref.startswith(_MASTER_REF):
                    child = episode_video_key(episode, ref.removeprefix(_MASTER_REF))
                    edges.append({"parent_artifact_key": key, "child_artifact_key": child, "dependency_ref": ref})
                    pending.append(child)
        snapshots = []
        for key in heads:
            snapshot = {"artifact_key": key, "body": bodies[key], "metadata_digest": _PLACEHOLDER_DIGEST}
            snapshot["metadata_digest"] = compute_digest("m10.artifact-metadata.v1", snapshot)
            snapshots.append(snapshot)
        root = heads[root_artifact_key]
        binding = {
            "schema_id": "m10.master-binding.v1",
            "user_id": user_id,
            "project_name": project_name,
            "root": root.model_dump(mode="python"),
            "dependency_heads": [
                head.model_dump(mode="python") for key, head in heads.items() if key != root_artifact_key
            ],
            "metadata_snapshots": snapshots,
            "dependency_edges": edges,
        }
        subject = q.AssessedSubject.model_validate(
            {
                "master_binding": binding,
                "master_binding_digest": compute_digest("m10.master-binding.v1", binding),
                "artifact_ref": root.object_ref,
                "artifact_digest": _media_digest(root.content_digest),
                "content_basis_digest": compute_digest(
                    "m10.content-basis.v1", bodies[root_artifact_key]["content_basis"]
                ),
                "caption_digest": None,
                "audio_digest": None,
            }
        )
        verify_caches(subject)
    except (MasterDivergedError, ValidationError, ValueError, KeyError, TypeError):
        raise SubjectStaleError() from None
    return subject


__all__ = ["resolve_assessed_subject"]

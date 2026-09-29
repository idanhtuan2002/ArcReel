"""Version 1 of the server-resolved M8 lineage (ADR-0098).

The resolution is pure: the host reads the episode's indexed script bytes and passes them in.
The content basis binds the script bytes; no host seam names an episode master yet, so the
master is null; every revision binds the ArcReel host profile and its empty policy.
"""

from __future__ import annotations

import hashlib

from r2.advanced_creative.digests import digest_canonical
from r2.contracts.advanced_creative import LineageBinding

HOST_PROFILE_ID = "arcreel.host"
HOST_PROFILE_VERSION = "1"
EPISODE_SCRIPT_BASIS = "host_episode_script"


def host_policy_digest() -> str:
    return digest_canonical({"profile_id": HOST_PROFILE_ID, "profile_version": HOST_PROFILE_VERSION, "rules": []})


def episode_content_basis_digest(episode: int, script_bytes: bytes) -> str:
    return digest_canonical(
        {
            "basis_kind": EPISODE_SCRIPT_BASIS,
            "episode": episode,
            "script_digest": "sha256:" + hashlib.sha256(script_bytes).hexdigest(),
        }
    )


def resolve_episode_lineage(project_name: str, episode: int, script_bytes: bytes) -> LineageBinding:
    return LineageBinding(
        project_name=project_name,
        content_basis_digest=episode_content_basis_digest(episode, script_bytes),
        approved_master_id=None,
        approved_master_digest=None,
        creative_profile_id=HOST_PROFILE_ID,
        creative_profile_version=HOST_PROFILE_VERSION,
        policy_digest=host_policy_digest(),
    )

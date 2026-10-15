"""The server-resolved M8 lineage: version 1 (ADR-0098) and version 2 (ADR-0105).

The resolution is pure: the host reads the episode's indexed script bytes and the project's
effective screenplay admissions and passes them in. Without an admission, version 1 binds the
script bytes and the ArcReel host profile with its empty policy. With exactly one admission,
version 2 binds that admission's M6 profile and policy pack, and its content basis binds the
admission and screenplay as well as the script bytes. No host seam names an episode master yet,
so the master is null in both versions.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

from r2.advanced_creative.digests import digest_canonical
from r2.advanced_creative.errors import LineageAmbiguousError, LineageEpisodeOutOfScopeError
from r2.contracts.adaptation import AdmittedScreenplayRef
from r2.contracts.advanced_creative import LineageBinding

HOST_PROFILE_ID = "arcreel.host"
HOST_PROFILE_VERSION = "1"
EPISODE_SCRIPT_BASIS = "host_episode_script"
ADMITTED_SCRIPT_BASIS = "admitted_screenplay_episode_script"
ADMITTED_EPISODE = 1


def host_policy_digest() -> str:
    return digest_canonical({"profile_id": HOST_PROFILE_ID, "profile_version": HOST_PROFILE_VERSION, "rules": []})


def _script_digest(script_bytes: bytes) -> str:
    return "sha256:" + hashlib.sha256(script_bytes).hexdigest()


def episode_content_basis_digest(episode: int, script_bytes: bytes) -> str:
    return digest_canonical(
        {"basis_kind": EPISODE_SCRIPT_BASIS, "episode": episode, "script_digest": _script_digest(script_bytes)}
    )


def _single_admission(admissions: Sequence[AdmittedScreenplayRef]) -> AdmittedScreenplayRef | None:
    if len(admissions) > 1:
        raise LineageAmbiguousError("the project has more than one effective screenplay admission")
    return admissions[0] if admissions else None


def project_profile(admissions: Sequence[AdmittedScreenplayRef]) -> tuple[str, str, str]:
    """``(creative_profile_id, creative_profile_version, policy_digest)`` of a project."""
    admission = _single_admission(admissions)
    if admission is None:
        return HOST_PROFILE_ID, HOST_PROFILE_VERSION, host_policy_digest()
    profile = admission.profile_ref
    return profile.profile_id.value, profile.profile_version, profile.policy_pack_digest


def resolve_episode_lineage(
    project_name: str, episode: int, script_bytes: bytes, *, admissions: Sequence[AdmittedScreenplayRef] = ()
) -> LineageBinding:
    admission = _single_admission(admissions)
    if admission is None:
        basis = episode_content_basis_digest(episode, script_bytes)
    elif episode != ADMITTED_EPISODE:
        raise LineageEpisodeOutOfScopeError("an admitted project has only episode 1")
    else:
        screenplay = admission.screenplay_ref
        basis = digest_canonical(
            {
                "basis_kind": ADMITTED_SCRIPT_BASIS,
                "episode": episode,
                "script_digest": _script_digest(script_bytes),
                "admission_decision_id": admission.admission_ref.decision_id,
                "admission_decision_digest": admission.admission_ref.decision_digest,
                "screenplay_id": screenplay.artifact_id,
                "screenplay_version": screenplay.version,
                "screenplay_content_hash": screenplay.content_hash,
            }
        )
    profile_id, profile_version, policy_digest = project_profile(admissions)
    return LineageBinding(
        project_name=project_name,
        content_basis_digest=basis,
        approved_master_id=None,
        approved_master_digest=None,
        creative_profile_id=profile_id,
        creative_profile_version=profile_version,
        policy_digest=policy_digest,
    )

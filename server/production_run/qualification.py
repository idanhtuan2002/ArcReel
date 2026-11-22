"""Launch qualification of automatic production, shared by the CLI and the host's API.

A launch qualification is recorded only when the real preflight's sole blocking reason is its absence, bound to a host
media-route evidence file. Reviewers have no qualification: they are trusted by configuration (ADR-0169).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from lib.config.resolver import ConfigResolver
from lib.project_manager import ProjectManager
from r2.automation.profiles import resolve_launch_profile
from r2.contracts.automation import (
    AutomationMode,
    LaunchQualification,
)
from server.production_run.composition import HostPreflightReader, ProjectPolicyResolver
from server.production_run.inputs import ProjectInputWitness
from server.production_run.preflight import ProductionPreflight

ONLY_MISSING = ("LAUNCH_PROFILE_NOT_QUALIFIED",)
#: A record whose routes, profile or resources moved since it was written is replaced the same way (ADR-0139): a
#: Showrunner changing models re-qualifies the launch, the newest record being the current one.
ONLY_STALE = ("LAUNCH_QUALIFICATION_CHANGED",)


def evidence_receipt(path: Path) -> tuple[str, str]:
    """The evidence file's name and digest; it must be a JSON document."""
    raw = path.read_bytes()
    json.loads(raw)
    return path.name, "sha256:" + hashlib.sha256(raw).hexdigest()


async def build_record(
    sessions, *, projects: ProjectManager, user_id: str, project_name: str, evidence: Path
) -> tuple[LaunchQualification | None, tuple[str, ...]]:
    """The record to store, or ``None`` with the preflight's blocking reasons when anything besides it is missing."""
    policies = ProjectPolicyResolver(sessions, projects=projects, resolver=ConfigResolver(sessions))
    policy = await policies.resolve(user_id=user_id, project_name=project_name, mode=AutomationMode.AUTO)
    reader = HostPreflightReader(
        sessions,
        projects=projects,
        policies=policies,
        witness=ProjectInputWitness(sessions, projects=projects),
    )
    report = await ProductionPreflight(reader).check(user_id=user_id, project_name=project_name, policy=policy)
    if report.blocking_reasons not in (ONLY_MISSING, ONLY_STALE):
        return None, report.blocking_reasons
    launch_profile = resolve_launch_profile(policy.launch_profile_id)
    receipt_ref, digest = evidence_receipt(evidence)
    return (
        LaunchQualification(
            owner="launch-qualification",
            receipt_ref=receipt_ref,
            digest=digest,
            user_id=user_id,
            project_name=project_name,
            launch_profile_id=policy.launch_profile_id,
            profile_digest=policy.profile_digest,
            route_digests=report.route_digests,
            required_disk_bytes=launch_profile.required_disk_bytes,
            required_gpu_bytes=launch_profile.required_gpu_bytes,
        ),
        (),
    )


__all__ = ["ONLY_MISSING", "ONLY_STALE", "build_record", "evidence_receipt"]

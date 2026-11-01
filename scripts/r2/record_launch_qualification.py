"""Record a project's launch qualification once every other automatic-production prerequisite already holds.

The release owner runs this after the project's automatic Quality profile is published and both reviewer routes are
qualified (``qualify_reviewers.py --record``). ``--evidence`` is the host's media-route qualification record for the
launch profile's image, video and audio routes. It resolves the policy a run would freeze, runs the real preflight,
and refuses unless the only blocking reason is the missing launch qualification. The record binds the project, launch
profile, profile digest, route digests and the project's declared resource envelope; the evidence file is named and
hashed in the receipt. GPU capacity is read as the host reads it: with the admission probes of
``ARCREEL_GPU_ADMISSION_PROBES`` configured. A run admitted by this record is the acceptance evidence, not the record itself.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path

from lib.config.resolver import ConfigResolver
from lib.db import async_session_factory
from lib.db.repositories.launch_qualifications import LaunchQualificationRepository
from lib.generation_resources import configure_device_admission
from lib.project_manager import ProjectManager, get_project_manager
from r2.contracts.automation import AutomationMode, LaunchQualification
from server.production_run.composition import HostPreflightReader, ProjectPolicyResolver, device_admission_from_env
from server.production_run.inputs import ProjectInputWitness
from server.production_run.preflight import ProductionPreflight

ONLY_MISSING = ("LAUNCH_PROFILE_NOT_QUALIFIED",)


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
    if report.blocking_reasons != ONLY_MISSING:
        return None, report.blocking_reasons
    settings = projects.load_project(project_name)["automation"]
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
            required_disk_bytes=int(settings["required_disk_bytes"]),
            required_gpu_bytes=int(settings["required_gpu_bytes"]),
        ),
        (),
    )


async def _main(args: argparse.Namespace) -> int:
    configure_device_admission(device_admission_from_env())
    record, reasons = await build_record(
        async_session_factory,
        projects=get_project_manager(),
        user_id=args.user,
        project_name=args.project,
        evidence=Path(args.evidence),
    )
    if record is None:
        print(json.dumps({"recorded": False, "blocking_reasons": list(reasons)}, indent=2))
        return 1
    async with async_session_factory() as session, session.begin():
        digest = await LaunchQualificationRepository(session).record(record)
    print(json.dumps({"recorded": True, "digest": digest, "record": record.model_dump(mode="json")}, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--user", default="default")
    parser.add_argument("--evidence", required=True, help="JSON media-route qualification record of this host")
    return asyncio.run(_main(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())

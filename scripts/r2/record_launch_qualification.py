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
import json
from pathlib import Path

from lib.db import async_session_factory
from lib.db.repositories.launch_qualifications import LaunchQualificationRepository
from lib.generation_resources import configure_device_admission
from lib.project_manager import get_project_manager
from server.production_run.composition import device_admission_from_env
from server.production_run.qualification import build_record


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

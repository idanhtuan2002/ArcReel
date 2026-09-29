"""Promote existing file masters into the database master authority (ADR-0096).

A project approved before the database head became the authority has file masters only, and
master-consuming routes refuse it as diverged. This command registers each file master's
selected host version as a candidate object and promotes it, with the deterministic command
``backfill:<artifact_key>:<candidate>``, so a rerun replays instead of writing again.

    --user-id <id> --project <name>     one project
    --user-id <id> --all                every project

It prints a JSON summary: promoted, already current, and diverged artifacts. The exit status is 2
when any artifact's database head disagrees with its file master; nothing is changed for that
artifact.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from lib.artifact_manifest import ArtifactKey, ArtifactKind
from lib.db import async_session_factory
from lib.db.repositories.host_hardening import MasterAuthorityRepository
from lib.project_manager import get_project_manager
from r2.host_hardening.master_authority import m7_candidate_id
from r2.m3.host_integration import GoldenAHostIntegration
from server.services.master_authority import master_authority_unit, projected_master_records


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--user-id", required=True)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--project")
    target.add_argument("--all", action="store_true")
    return parser


async def backfill_project(*, user_id: str, project_name: str, project_dir: Path) -> dict[str, list[str]]:
    summary: dict[str, list[str]] = {"promoted": [], "current": [], "diverged": [], "skipped": []}
    records = await asyncio.to_thread(projected_master_records, project_dir)
    root = await asyncio.to_thread(Path(project_dir).resolve)
    for artifact_key, record in sorted(records.items()):
        key = ArtifactKey.decode(artifact_key)
        if key.kind is not ArtifactKind.EPISODE_VIDEO:
            summary["skipped"].append(artifact_key)
            continue
        expected = m7_candidate_id(artifact_key, record.selected_candidate_id)
        async with async_session_factory() as session:
            head = await MasterAuthorityRepository(session).get_current(
                user_id=user_id, project_name=project_name, artifact_key=artifact_key
            )
        if head is not None:
            summary["current" if head.candidate_id == expected else "diverged"].append(artifact_key)
            continue
        episode, target_ref = int(key.components[0]), str(key.components[1])
        host = GoldenAHostIntegration(project_dir, resource_type="videos", episode=episode)
        version_file = await asyncio.to_thread(host.version_file_for, target_ref, record.host_version_ref)
        async with async_session_factory() as session:
            await master_authority_unit(session).promote_staged(
                user_id=user_id,
                project_name=project_name,
                project_dir=root,
                artifact_key=artifact_key,
                generation_candidate_id=record.selected_candidate_id,
                version_file=version_file,
                approval_record=record.approval_record,
                command_id=f"backfill:{artifact_key}:{record.selected_candidate_id}",
            )
        summary["promoted"].append(artifact_key)
    return summary


async def _run(args: argparse.Namespace) -> dict[str, dict[str, list[str]]]:
    manager = get_project_manager()
    names = manager.list_projects() if args.all else [args.project]
    return {
        name: await backfill_project(
            user_id=args.user_id, project_name=name, project_dir=manager.get_project_path(name)
        )
        for name in names
    }


async def main_async(argv: list[str] | None = None) -> int:
    result = await _run(build_parser().parse_args(argv))
    print(json.dumps(result, indent=2))
    return 2 if any(summary["diverged"] for summary in result.values()) else 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(main_async(argv))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

"""Operator CLI for V1 whole-deployment backup sets (H6, ADR-0090).

Database URLs are read from environment variables named on the command line,
never from argv, so credentials do not appear in process listings. Every
filesystem location is explicit; nothing is inferred from the deployment's own
configuration. Stop the application and worker before ``create``.

    create   capture a backup set under the offline fence
    restore  restore a set into an empty database and empty roots
    verify   run the automated checks on a restored target (verdicts/<id>.json)
    attest   mark the set VERIFIED from a passing verdict plus Golden evidence
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

from pydantic import ValidationError

from lib.logging_utils import redact_provider_text
from r2.contracts.host_hardening import GoldenRestoreEvidence
from r2.host_hardening.deployment_backup import (
    DeploymentBackupError,
    ReleaseIdentity,
    attest_deployment_restore,
    create_deployment_backup,
    manifest_digest,
    restore_deployment_backup,
    verify_restored_deployment,
)


def _roots(values: list[str]) -> dict[str, Path]:
    roots: dict[str, Path] = {}
    for value in values:
        name, sep, raw = value.partition("=")
        if not sep or not name or not raw:
            raise SystemExit(f"--root expects NAME=PATH, got {value!r}")
        if name in roots:
            raise SystemExit(f"--root {name!r} given twice")
        roots[name] = Path(raw).expanduser().resolve()
    return roots


def _env_url(name: str) -> str:
    url = os.environ.get(name, "")
    if not url:
        raise SystemExit(f"environment variable {name} is not set")
    return url


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("create")
    create.add_argument("--backup-set-id", required=True)
    create.add_argument("--backup-dir", required=True, type=Path)
    create.add_argument("--root", action="append", required=True, help="NAME=PATH; 'data' is required")
    create.add_argument("--database-url-env", default="DATABASE_URL")
    create.add_argument("--deployment-id", required=True)
    create.add_argument("--release-git-sha", required=True)
    create.add_argument("--release-image-digest", required=True)
    create.add_argument("--configuration-json", type=Path, help="non-secret deployment configuration to digest")

    restore = sub.add_parser("restore")
    restore.add_argument("--backup-dir", required=True, type=Path)
    restore.add_argument("--target-root", action="append", required=True, help="NAME=PATH (empty directories)")
    restore.add_argument("--target-database-url-env", required=True)

    verify = sub.add_parser("verify")
    verify.add_argument("--backup-dir", required=True, type=Path)
    verify.add_argument("--target-root", action="append", required=True)
    verify.add_argument("--target-database-url-env", required=True)
    verify.add_argument("--target-release-git-sha", required=True, help="release running on the restored target")
    verify.add_argument("--restore-target-id", required=True, help="operator label of this restored target")

    attest = sub.add_parser("attest")
    attest.add_argument("--backup-dir", required=True, type=Path)
    attest.add_argument("--golden-evidence", required=True, type=Path, help="GoldenRestoreEvidence JSON")
    attest.add_argument("--measured-rpo-seconds", required=True, type=int)
    attest.add_argument("--measured-rto-seconds", required=True, type=int)
    return parser


async def _run(args: argparse.Namespace) -> dict[str, object]:
    if args.command == "create":
        configuration = {}
        if args.configuration_json is not None:
            configuration = json.loads(args.configuration_json.read_text(encoding="utf-8"))
        manifest = await create_deployment_backup(
            backup_set_id=args.backup_set_id,
            database_url=_env_url(args.database_url_env),
            roots=_roots(args.root),
            backup_dir=args.backup_dir.resolve(),
            identity=ReleaseIdentity(
                source_deployment_id=args.deployment_id,
                release_git_sha=args.release_git_sha,
                release_image_digest=args.release_image_digest,
                configuration=configuration,
            ),
        )
        return {
            "state": "COMPLETE",
            "backup_set_id": manifest.backup_set_id,
            "manifest_digest": manifest_digest(manifest),
            "recovery_point": manifest.recovery_point.isoformat(),
            "file_count": len(manifest.files),
            "table_count": len(manifest.table_row_counts),
            "sanitized_tables": [t.table for t in manifest.sanitized_tables],
            "excluded_data_entries": list(manifest.excluded_data_entries),
        }
    if args.command == "restore":
        started = time.monotonic()
        manifest = await restore_deployment_backup(
            backup_dir=args.backup_dir.resolve(),
            target_database_url=_env_url(args.target_database_url_env),
            target_roots=_roots(args.target_root),
        )
        return {
            "backup_set_id": manifest.backup_set_id,
            "restored_file_count": len(manifest.files),
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "credentials_to_reenter": [t.table for t in manifest.sanitized_tables],
        }
    if args.command == "verify":
        verdict = await verify_restored_deployment(
            backup_dir=args.backup_dir.resolve(),
            target_database_url=_env_url(args.target_database_url_env),
            target_roots=_roots(args.target_root),
            restore_target_id=args.restore_target_id,
            target_release_git_sha=args.target_release_git_sha,
        )
        return verdict.model_dump(mode="json")
    evidence = GoldenRestoreEvidence.model_validate_json(args.golden_evidence.read_text(encoding="utf-8"))
    attestation = attest_deployment_restore(
        backup_dir=args.backup_dir.resolve(),
        golden_evidence=evidence,
        measured_rpo_seconds=args.measured_rpo_seconds,
        measured_rto_seconds=args.measured_rto_seconds,
    )
    return {"state": "VERIFIED", **attestation.model_dump(mode="json")}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = asyncio.run(_run(args))
    except DeploymentBackupError as exc:
        print(json.dumps({"error": exc.reason_code, "detail": redact_provider_text(str(exc))}), file=sys.stderr)
        return 2
    except ValidationError as exc:
        print(
            json.dumps({"error": "INVALID_INPUT", "detail": f"{exc.error_count()} validation error(s)"}),
            file=sys.stderr,
        )
        return 2
    except Exception as exc:
        detail = redact_provider_text(f"{type(exc).__name__}: {exc}")[:500]
        print(json.dumps({"error": "UNEXPECTED", "detail": detail}), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.command == "verify" and not result.get("checks_passed"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

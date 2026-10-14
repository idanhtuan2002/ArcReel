"""Operator ceremony for ADR-0103 activation (runbook: docs/r2/runbooks/governance-activation.md).

Offline commands run on the signing machine and never touch a database:
  keygen, registry, approve, genesis-body, sign-checkpoint, sign-event.
Host commands run as root with the application and its workers stopped; the database URL comes
from an environment variable, never argv:
  enroll, import-event, next-body, publish.

Every output file is created exclusively (an existing file is refused). Private keys are written
with mode 0600 and must never be copied to the host.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import os
import sys
from pathlib import Path
from typing import cast

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from r2.contracts.governance_verifier_registry import parse_verifier_registry
from r2.governance.ceremony import (
    CeremonyInvalid,
    build_approved_deployment,
    build_registry,
    checkpoint_body,
    decode_public_key,
    generate_key,
    public_key_of,
    sign_checkpoint,
    sign_grant_event,
)
from server.services.governance_ceremony import (
    enroll_genesis,
    import_grant_event,
    next_checkpoint_body,
    publish_signed_checkpoint,
    reconcile,
)

OFFLINE = ("keygen", "registry", "approve", "genesis-body", "sign-checkpoint", "sign-event")
HOST = ("enroll", "import-event", "next-body", "publish", "reconcile")


def _require_posix_key_custody() -> None:
    """Key files rely on POSIX modes; other platforms cannot guarantee a private key stays private."""
    if os.name != "posix":
        raise CeremonyInvalid("signing keys are supported only on a POSIX signing machine")


def _write_new(path: Path, raw: bytes, mode: int = 0o644) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), mode)
    try:
        if os.name == "posix":
            os.fchmod(fd, mode)
        view = memoryview(raw)
        while view:
            view = view[os.write(fd, view) :]
        os.fsync(fd)
    finally:
        os.close(fd)


def _read(path: Path) -> bytes:
    return path.read_bytes()


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def _private_key(path: Path) -> bytes:
    _require_posix_key_custody()
    if path.stat().st_mode & 0o077:
        raise CeremonyInvalid("the private key file must not be readable by group or others")
    return decode_public_key(_text(path))  # the same 32-byte base64url encoding


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)

    keygen = commands.add_parser("keygen", help="create one Ed25519 key pair")
    keygen.add_argument("--private", type=Path, required=True)
    keygen.add_argument("--public", type=Path, required=True)

    registry = commands.add_parser("registry", help="build the public verifier registry")
    registry.add_argument("--deployment-id", required=True)
    registry.add_argument("--grant-key-id", required=True)
    registry.add_argument("--grant-public", type=Path, required=True)
    registry.add_argument("--checkpoint-key-id", required=True)
    registry.add_argument("--checkpoint-public", type=Path, required=True)
    registry.add_argument("--out", type=Path, required=True)

    approve = commands.add_parser("approve", help="approve the pinned image against the registry")
    approve.add_argument("--registry", type=Path, required=True)
    approve.add_argument("--image-ref", required=True, help="repository@sha256:<digest>")
    approve.add_argument("--image-platform", required=True, help="for example linux/amd64")
    approve.add_argument("--operator-id", required=True)
    approve.add_argument("--out", type=Path, required=True)

    genesis = commands.add_parser("genesis-body", help="the unsigned empty sequence-1 checkpoint body")
    genesis.add_argument("--registry", type=Path, required=True)
    genesis.add_argument("--out", type=Path, required=True)

    sign_cp = commands.add_parser("sign-checkpoint", help="sign an exact unsigned checkpoint body")
    sign_cp.add_argument("--key", type=Path, required=True)
    sign_cp.add_argument("--body", type=Path, required=True)
    sign_cp.add_argument("--out", type=Path, required=True)

    sign_ev = commands.add_parser("sign-event", help="sign one ISSUE or REVOKE grant event")
    sign_ev.add_argument("--key", type=Path, required=True)
    sign_ev.add_argument("--key-id", required=True)
    sign_ev.add_argument("--type", choices=("ISSUE", "REVOKE"), required=True)
    sign_ev.add_argument("--user-id", required=True)
    sign_ev.add_argument("--project", required=True)
    sign_ev.add_argument("--principal", required=True)
    sign_ev.add_argument("--sequence", type=int, required=True)
    sign_ev.add_argument("--previous-event-digest", help="omit only for sequence 1")
    sign_ev.add_argument("--expires-at", help="ISSUE only, UTC like 2027-01-01T00:00:00Z")
    sign_ev.add_argument("--out", type=Path, required=True)

    for name, help_text in (
        ("enroll", "create the genesis archive over an empty grant ledger"),
        ("import-event", "import one signed grant event"),
        ("next-body", "export the unsigned next checkpoint body"),
        ("publish", "retain and publish one signed successor checkpoint"),
        ("reconcile", "republish the public pair from the retained archive"),
    ):
        host = commands.add_parser(name, help=help_text)
        host.add_argument("--root", type=Path, required=True)
        host.add_argument("--database-url-env", default="DATABASE_URL")
    commands.choices["enroll"].add_argument("--registry", type=Path, required=True)
    commands.choices["enroll"].add_argument("--approved", type=Path, required=True)
    commands.choices["enroll"].add_argument("--checkpoint", type=Path, required=True)
    commands.choices["enroll"].add_argument("--operator-id", required=True)
    commands.choices["import-event"].add_argument("--event", type=Path, required=True)
    commands.choices["next-body"].add_argument("--out", type=Path, required=True)
    commands.choices["publish"].add_argument("--checkpoint", type=Path, required=True)
    commands.choices["publish"].add_argument("--operator-id", required=True)
    return parser


def run_offline(args: argparse.Namespace) -> str:
    command = cast(str, args.command)
    if command == "keygen":
        _require_posix_key_custody()
        pair = generate_key()
        encoded = public_key_of(pair.private_raw)
        _write_new(args.private, (_b64(pair.private_raw) + "\n").encode(), 0o600)
        _write_new(args.public, (encoded + "\n").encode())
        return f"key pair created; public key {encoded}"
    if command == "registry":
        raw, parsed = build_registry(
            deployment_id=args.deployment_id,
            grant_key_id=args.grant_key_id,
            grant_public_key=_text(args.grant_public),
            checkpoint_key_id=args.checkpoint_key_id,
            checkpoint_public_key=_text(args.checkpoint_public),
        )
        _write_new(args.out, raw)
        return f"registry {parsed.registry_digest}"
    if command == "approve":
        raw = build_approved_deployment(
            _read(args.registry),
            image_ref=args.image_ref,
            image_platform=args.image_platform,
            operator_id=args.operator_id,
        )
        _write_new(args.out, raw)
        return "approved deployment written"
    if command == "genesis-body":
        registry = parse_verifier_registry(_read(args.registry))
        body = checkpoint_body(
            deployment_id=registry.deployment_id,
            signer_key_id=registry.grant_checkpoint.key_id,
            sequence=1,
            previous=None,
            heads=(),
        )
        _write_new(args.out, body)
        return "genesis checkpoint body written"
    if command == "sign-checkpoint":
        _write_new(args.out, sign_checkpoint(_read(args.body), _private_key(args.key)))
        return "checkpoint signed"
    raw, event = sign_grant_event(
        private_raw=_private_key(args.key),
        signer_key_id=args.key_id,
        event_type=args.type,
        user_id=args.user_id,
        project_name=args.project,
        principal=args.principal,
        sequence=args.sequence,
        previous_event_digest=args.previous_event_digest,
        expires_at=args.expires_at,
    )
    _write_new(args.out, raw)
    return f"{args.type} event signed; event digest {event.event_digest}"


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


async def run_host(args: argparse.Namespace) -> str:
    if os.geteuid() != 0 or os.getegid() != 0:
        raise CeremonyInvalid("host commands run as root")
    url = os.environ.get(cast(str, args.database_url_env), "")
    if not url.startswith("postgresql+asyncpg://"):
        raise CeremonyInvalid("database configuration")
    engine = create_async_engine(url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    root = cast(Path, args.root)
    try:
        if args.command == "enroll":
            result = await enroll_genesis(
                root,
                registry_raw=_read(args.registry),
                approved_raw=_read(args.approved),
                checkpoint_raw=_read(args.checkpoint),
                operator_id=args.operator_id,
                session_factory=sessions,
            )
            return f"enrolled; checkpoint sequence {result.snapshot.high_water.checkpoint_sequence}"
        if args.command == "import-event":
            event = await import_grant_event(root, _read(args.event), session_factory=sessions)
            return f"imported {event.body.event_type} sequence {event.body.sequence}; publish a checkpoint next"
        if args.command == "next-body":
            _write_new(args.out, await next_checkpoint_body(root, session_factory=sessions))
            return "next checkpoint body written; sign it offline"
        if args.command == "reconcile":
            result = await reconcile(root, session_factory=sessions)
            return f"reconciled; checkpoint sequence {result.snapshot.high_water.checkpoint_sequence}"
        result = await publish_signed_checkpoint(
            root, _read(args.checkpoint), operator_id=args.operator_id, session_factory=sessions
        )
        return f"published; checkpoint sequence {result.snapshot.high_water.checkpoint_sequence}"
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        message = asyncio.run(run_host(args)) if args.command in HOST else run_offline(args)
    except Exception as error:
        # Sanitized: a category, never a key, path content, SQL or database detail.
        print(f"Governance ceremony refused: {type(error).__name__}", file=sys.stderr)
        return 1
    print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

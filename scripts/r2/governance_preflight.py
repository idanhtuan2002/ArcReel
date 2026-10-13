"""Read-only operator Governance preflight and host startup attestor.

Run as root with already provisioned absolute paths. Database credentials come
from an environment variable; this command never migrates or publishes.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import signal
import sys
from pathlib import Path
from typing import cast

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from server.services.governance_attestation import serve_governance_attestor
from server.services.governance_operator_archive import verify_operator_archive_preflight


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("preflight", "serve"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--socket-directory", type=Path)
    parser.add_argument("--database-url-env", default="DATABASE_URL")
    return parser


async def run(args: argparse.Namespace) -> None:
    if os.geteuid() != 0 or os.getegid() != 0:
        raise ValueError("host principal")
    root = cast(Path, args.root)
    url = os.environ.get(cast(str, args.database_url_env), "")
    if not url.startswith("postgresql+asyncpg://"):
        raise ValueError("database configuration")
    engine = create_async_engine(url)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    try:
        if args.command == "preflight":
            await verify_operator_archive_preflight(root, session_factory=sessions)
            print("Governance preflight passed")
        else:
            runtime = cast(Path | None, args.socket_directory)
            if runtime is None:
                raise ValueError("socket configuration")
            stopped = asyncio.Event()
            loop = asyncio.get_running_loop()
            signals = (signal.SIGTERM, signal.SIGINT)
            for signum in signals:
                loop.add_signal_handler(signum, stopped.set)
            try:
                async with serve_governance_attestor(root, runtime, session_factory=sessions):
                    await stopped.wait()
            finally:
                for signum in signals:
                    loop.remove_signal_handler(signum)
    finally:
        await engine.dispose()


def main() -> int:
    args = build_parser().parse_args()
    try:
        asyncio.run(run(args))
    except Exception:
        print("Governance operator command failed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

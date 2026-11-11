"""Set tasks aside for a deploy, and bring them back (ADR-0130).

Run only while the application and its worker are stopped. ``park`` turns every queued, running or cancelling task
into ``parked`` so the offline backup (whose fence refuses active tasks) can run; the application gives them back
when it starts (a task that was running then goes through restart recovery). ``unpark`` does the same by hand.
The database URL is read from the environment variable named on the command line, never from argv.

    park     --database-url-env NAME [--refuse-if-listening PORT]
    unpark   --database-url-env NAME
"""

from __future__ import annotations

import argparse
import asyncio
import os
import socket
import sys

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from lib.db.repositories.task_repo import TaskRepository


def _listening(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


async def _run(action: str, url: str) -> int:
    engine = create_async_engine(url)
    try:
        async with async_sessionmaker(engine)() as session:
            repo = TaskRepository(session)
            return await (repo.park_active() if action == "park" else repo.unpark())
    finally:
        await engine.dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=("park", "unpark"))
    parser.add_argument("--database-url-env", required=True)
    parser.add_argument("--refuse-if-listening", type=int)
    args = parser.parse_args(argv)
    url = os.environ.get(args.database_url_env)
    if not url:
        print(f"environment variable {args.database_url_env} is empty", file=sys.stderr)
        return 2
    if args.action == "park" and args.refuse_if_listening and _listening(args.refuse_if_listening):
        print(f"the app on :{args.refuse_if_listening} is still running; stop it first", file=sys.stderr)
        return 1
    count = asyncio.run(_run(args.action, url))
    print(f"{args.action}ed {count} task(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

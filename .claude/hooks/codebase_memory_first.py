"""Codebase-memory first (AGENTS.md): a grep over source code is refused until codebase-memory was used recently.

Two modes, chosen by argv[1]:

- ``mark`` (PostToolUse on ``mcp__codebase-memory-mcp__*``): records the time of the call for this session.
- ``guard`` (PreToolUse on ``Grep`` and ``Bash``): refuses a text search over source directories when the session has
  made no codebase-memory call in the last ``WINDOW_SECONDS``. Searches over docs, logs, configs or paths outside the
  repository's source directories pass.

Reads the hook JSON on stdin; prints a deny decision or nothing.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

WINDOW_SECONDS = 30 * 60
SOURCE_DIRS = ("lib/", "server/", "r2/", "frontend/src", "scripts/", "alembic/", "agent_runtime_profile/")
_SEARCH = re.compile(r"(^|[|;&(]\s*|\s)(grep|egrep|rg|ugrep|ag)\s")


def _marker(session: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_-]", "_", session or "unknown")
    return Path(tempfile.gettempdir()) / f"claude-codebase-memory-{safe}"


def _recent(session: str) -> bool:
    try:
        return time.time() - _marker(session).stat().st_mtime < WINDOW_SECONDS
    except OSError:
        return False


_REPO_SOURCE = re.compile(
    r"(?:^|[\s='\"(])(?:\./|\S*content-production-os(?:/\.worktrees/[^/\s]+)?/)?"
    r"(?:" + "|".join(re.escape(d.rstrip("/")) for d in SOURCE_DIRS) + r")(?:/|\b)"
)


def _targets_source(text: str) -> bool:
    """A path of this repository's source directories (relative, or under the repository root); donor checkouts and
    other trees with a ``server/`` or ``lib/`` of their own do not count."""
    return bool(_REPO_SOURCE.search(text))


def _deny(reason: str) -> None:
    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": reason,
                }
            },
            ensure_ascii=False,
        )
    )


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "guard"
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return 0
    session = str(event.get("session_id") or "")
    if mode == "mark":
        _marker(session).touch()
        return 0
    tool = event.get("tool_name")
    args = event.get("tool_input") or {}
    if tool == "Grep":
        searched = " ".join(str(args.get(k) or "") for k in ("path", "glob"))
        is_search = True
        # A grep with no path searches the whole repository, source included.
        targets = _targets_source(searched) or not str(args.get("path") or "").strip()
    elif tool == "Bash":
        command = str(args.get("command") or "")
        is_search = bool(_SEARCH.search(command))
        targets = _targets_source(command)
    else:
        return 0
    if is_search and targets and not _recent(session) and os.environ.get("ARCREEL_ALLOW_GREP") != "1":
        _deny(
            "Codebase-memory trước (AGENTS.md): dùng mcp__codebase-memory-mcp__search_graph / search_code / "
            "trace_path / get_code_snippet để tìm định nghĩa, nơi gọi và phạm vi ảnh hưởng, rồi mới grep mã nguồn. "
            "Sau một lần gọi codebase-memory, grep được phép trong 30 phút."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())

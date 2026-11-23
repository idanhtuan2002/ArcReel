"""Stop hook: work must not live only in the session (AGENTS.md "防额度中断丢失").

When the turn ends with uncommitted changes under the task's paths, the stop is held once and the agent is told to
commit, push and update the handoff file; a second stop in a row (``stop_hook_active``) passes, so it never loops.
"""

from __future__ import annotations

import json
import subprocess
import sys

TASK_PATHS = ("docs/", "assembly/", "vendor/", "lib/", "server/", "frontend/src/", "tests/", "AGENTS.md", ".claude/hooks/")


def main() -> int:
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return 0
    if event.get("stop_hook_active"):
        return 0
    cwd = str(event.get("cwd") or "")
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain"], cwd=cwd or None, capture_output=True, text=True, timeout=10
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return 0
    dirty = [line[3:] for line in out.splitlines() if line[3:].startswith(TASK_PATHS)]
    if not dirty:
        return 0
    print(
        "Chưa lưu vào repo (AGENTS.md 防额度中断丢失): "
        + ", ".join(dirty[:8])
        + ". Commit + push và cập nhật file handoff trước khi dừng, hoặc nói rõ vì sao giữ lại.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())

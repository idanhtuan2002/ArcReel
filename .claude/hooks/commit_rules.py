"""PreToolUse guard on ``git commit`` for the rules agents keep forgetting (AGENTS.md).

A commit that changes source code (``lib/``, ``server/``, ``r2/``, ``frontend/src/``, ``scripts/``; tests and docs
alone are exempt) must say in its message:

- ``Donor:`` what was taken from which donor at which commit, or ``Donor: none — <why no donor unit applies>``
  ("Donor 整体移植" and "Research-first").
- for a ``fix`` commit, ``Consumers:`` every consumer of the state, mode or digest that was checked ("按类修复").

Reads the hook JSON on stdin; prints a deny decision or nothing. Set ``ARCREEL_COMMIT_RULES=0`` in the command to
bypass for a commit outside this scope (a revert, a merge).
"""

from __future__ import annotations

import json
import re
import subprocess
import sys

SOURCE = re.compile(r"^(lib|server|r2|scripts|frontend/src)/")
TESTS = re.compile(r"(^|/)tests?/|\.test\.[jt]sx?$|(^|/)test_[^/]*\.py$")
_COMMIT = re.compile(r"\bgit\s+(-C\s+\S+\s+)?commit\b")


def _staged(cwd: str) -> list[str]:
    try:
        out = subprocess.run(
            ["git", "diff", "--cached", "--name-only"], cwd=cwd or None, capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.SubprocessError):
        return []
    return [line for line in out.stdout.splitlines() if line.strip()]


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
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return 0
    if event.get("tool_name") != "Bash":
        return 0
    command = str((event.get("tool_input") or {}).get("command") or "")
    if not _COMMIT.search(command) or "ARCREEL_COMMIT_RULES=0" in command:
        return 0
    # Paths staged before the command, plus paths the same command adds (``git add a b && git commit``).
    paths = _staged(str(event.get("cwd") or ""))
    paths += re.findall(r"(?:^|\s)((?:lib|server|r2|scripts|frontend/src)/[^\s;&|]+)", command)
    code = [p for p in paths if SOURCE.match(p) and not TESTS.search(p)]
    if not code:
        return 0
    missing = []
    if not re.search(r"(?m)^\s*Donor:", command):
        missing.append("`Donor: <repo@commit, đã lấy gì>` hoặc `Donor: none — <vì sao không có đơn vị donor>`")
    if re.search(r"""(-m\s+["']?|<<'?EOF'?\s*\n)\s*fix(\(|:)""", command) and not re.search(
        r"(?m)^\s*Consumers:", command
    ):
        missing.append("`Consumers: <mọi nơi đọc/ghi cùng trạng thái đã quét bằng codebase-memory>` (按类修复)")
    if missing:
        _deny(
            "Commit chạm mã nguồn ("
            + ", ".join(code[:4])
            + ") thiếu trong message: "
            + "; ".join(missing)
            + ". Quy tắc AGENTS.md: Research-first, Donor 整体移植, 资源浪费防线."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())

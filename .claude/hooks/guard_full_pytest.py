"""PreToolUse guard: refuse a pytest run that names no test path (the whole suite, ~90 min of renders).

Run only the tests related to a change. A whole-suite run needs an explicit request; mark it with
``ARCREEL_FULL_SUITE=1`` in the command. Reads the hook JSON on stdin; prints a deny decision or nothing.
"""

from __future__ import annotations

import json
import re
import shlex
import sys

# Options whose next token is their value, not a test path.
_VALUED = {
    "-n",
    "--numprocesses",
    "--dist",
    "-k",
    "-m",
    "-p",
    "-c",
    "-o",
    "--deselect",
    "--ignore",
    "--ignore-glob",
    "--timeout",
    "--rootdir",
    "--basetemp",
    "--durations",
    "--maxfail",
    "--tb",
    "-W",
    "--confcutdir",
}
_WHOLE = {"tests", "tests/", ".", "./"}


def _targets(tokens: list[str]) -> list[str]:
    found: list[str] = []
    skip = False
    for token in tokens:
        if skip:
            skip = False
            continue
        if token in _VALUED:
            skip = True
            continue
        if token.startswith("-"):
            continue
        found.append(token)
    return found


def whole_suite(command: str) -> bool:
    if "ARCREEL_FULL_SUITE=1" in command:
        return False
    for segment in re.split(r"&&|\|\||;|\||\n", command):
        try:
            tokens = shlex.split(segment)
        except ValueError:
            continue
        if "pytest" not in tokens:
            continue
        rest = tokens[tokens.index("pytest") + 1 :]
        targets = _targets(rest)
        if not targets or all(target in _WHOLE for target in targets):
            return True
    return False


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except ValueError:
        return
    command = (payload.get("tool_input") or {}).get("command") or ""
    if whole_suite(command):
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": (
                            "Whole-suite pytest is off by default (CLAUDE.md): name the related test paths. "
                            "If the user explicitly asked for the full suite, prefix ARCREEL_FULL_SUITE=1."
                        ),
                    }
                }
            )
        )


if __name__ == "__main__":
    main()

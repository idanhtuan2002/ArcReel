"""Run release gates and write the evidence the upstream-compatibility verifier re-reads (ADR-0091, T1).

Each gate command runs itself here: no argv shell, output captured. The runner writes one log
per gate: a ``# command`` / ``# exit_code`` / ``# tool_versions`` header, then the combined
output. It then writes one manifest that names every log by path and digest. The verifier
trusts the logs, not the manifest's own fields, and the operator commits both and attests to
the run.

    uv run python -m scripts.r2.run_gates --config gates.json --out docs/r2/evidence/gate-run-<id> \\
        [--changes changes.json]

``gates.json`` maps each gate name to a command string, split with ``shlex``. ``changes.json``
maps upstream commit SHAs to dispositions for the report's change inventory. The manifest's
``target_sha`` is the current ``HEAD``, and the working tree must be clean before the run.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shlex
import subprocess
import sys
from pathlib import Path


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout.strip()


def _tool_versions() -> str:
    return f"python {platform.python_version()}; git {_git('--version').removeprefix('git version ')}"


def run_gate(name: str, command: str, out_dir: Path) -> dict[str, object]:
    completed = subprocess.run(shlex.split(command), capture_output=True, text=True, check=False)
    header = f"# command: {command}\n# exit_code: {completed.returncode}\n# tool_versions: {_tool_versions()}\n"
    text = header + completed.stdout + completed.stderr
    log_path = out_dir / f"{name}.log"
    log_path.write_text(text, encoding="utf-8")
    return {
        "status": "PASS" if completed.returncode == 0 else "FAIL",
        "required_skips": 0,
        "exit_code": completed.returncode,
        "command": command,
        "log_path": log_path.as_posix(),
        "log_digest": "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path, help="repository-relative evidence directory")
    parser.add_argument("--changes", type=Path)
    args = parser.parse_args(argv)

    if _git("status", "--porcelain=v1"):
        print(json.dumps({"error": "DIRTY_TREE", "detail": "commit or discard changes before a gate run"}))
        return 2
    gates: dict[str, str] = json.loads(args.config.read_text(encoding="utf-8"))
    changes: dict[str, str] = json.loads(args.changes.read_text(encoding="utf-8")) if args.changes else {}
    args.out.mkdir(parents=True, exist_ok=True)
    target_sha = _git("rev-parse", "HEAD")
    results = {name: run_gate(name, command, args.out) for name, command in gates.items()}
    manifest = {"schema_version": 1, "target_sha": target_sha, "changes": changes, "results": results}
    manifest_path = args.out / "manifest.json"
    manifest_text = json.dumps(manifest, sort_keys=True)
    manifest_path.write_text(manifest_text, encoding="utf-8")
    failed = sorted(name for name, result in results.items() if result["status"] != "PASS")
    print(
        json.dumps(
            {
                "target_sha": target_sha,
                "manifest": manifest_path.as_posix(),
                "manifest_digest": "sha256:" + hashlib.sha256(manifest_text.encode("utf-8")).hexdigest(),
                "failed": failed,
            },
            indent=2,
        )
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

"""Run one OpenMontage production turn with the chosen agent driver, resumable across its human checkpoints.

OpenMontage is driven by a coding agent that reads `AGENT_GUIDE.md` and stops at human-approval checkpoints
(`skills/meta/checkpoint-protocol.md`). This runs one turn non-interactively and keeps the session id, so the sponsor
can approve and the same session continues: `--resume <session> --message "Đã duyệt, tiếp tục"`.

Drivers (sponsor decision 2026-11-24: both available):
- `claude`: Claude Code headless (`claude -p`), the sponsor's subscription quota.
- `codex`: Codex CLI with the assembly's NewAPI (`~/assembly-data/codex-home/config.toml`, model `DC-codex-agent-LLM`,
  free models), sandbox `workspace-write`; the NewAPI token is read from DramaClaw at run time and never stored.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

OPENMONTAGE = Path(os.environ.get("OPENMONTAGE_DIR", str(Path.home() / "assembly-data/openmontage")))
CODEX_HOME = Path.home() / "assembly-data/codex-home"
RUNS = Path.home() / "assembly-data/openmontage-runs"
PREAMBLE = (
    "You are running non-interactively for the sponsor. Follow AGENT_GUIDE.md exactly. "
    "When a stage reaches a human-approval checkpoint, stop and summarize in Vietnamese what needs approval. "
    "Write every user-facing text in Vietnamese unless the brief says otherwise. "
    "For speech use the openai_tts tool (OPENAI_BASE_URL points to a Vietnamese VieNeu server; voices: alloy, ash, "
    "coral, echo, nova, onyx, sage, shimmer)."
)


def _newapi_token() -> str:
    code = "from novelvideo.model_gateway_settings import get_model_gateway_settings as g;print(g()['custom_newapi_api_key'])"
    out = subprocess.run(
        ["docker", "exec", "assembly-dramaclaw-api-1", "python", "-c", code], check=True, capture_output=True, text=True
    ).stdout
    return out.strip().splitlines()[-1]


def build_command(driver: str, message: str, session: str | None) -> tuple[list[str], dict[str, str]]:
    env = dict(os.environ)
    env["PATH"] = f"{OPENMONTAGE / '.venv/bin'}:{env.get('PATH', '')}"
    if driver == "claude":
        cmd = ["claude", "-p", message, "--output-format", "json", "--permission-mode", "acceptEdits"]
        cmd += ["--allowedTools", "Bash Read Write Edit Glob Grep"]
        if session:
            cmd += ["--resume", session]
        return cmd, env
    if driver == "codex":
        env["CODEX_HOME"] = str(CODEX_HOME)
        cmd = ["codex", "exec", "--json", "--skip-git-repo-check", "--cd", str(OPENMONTAGE)]
        cmd += ["resume", session, message] if session else [message]
        return cmd, env
    raise ValueError(f"unknown driver {driver!r}")


def session_of(driver: str, output: str) -> str:
    if driver == "claude":
        return str(json.loads(output.strip().splitlines()[-1]).get("session_id") or "")
    for line in output.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        for key in ("thread_id", "session_id"):
            if event.get(key):
                return str(event[key])
    return ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--driver", choices=["claude", "codex"], required=True)
    parser.add_argument("--brief", help="the production request (new session)")
    parser.add_argument("--resume", help="session id to continue")
    parser.add_argument("--message", default="Đã duyệt, tiếp tục.", help="message when resuming")
    args = parser.parse_args()
    if not args.brief and not args.resume:
        parser.error("--brief or --resume is required")
    message = args.message if args.resume else f"{PREAMBLE}\n\n{args.brief}"
    cmd, env = build_command(args.driver, message, args.resume)
    if args.driver == "codex":
        env["ASSEMBLY_NEWAPI_TOKEN"] = _newapi_token()
    RUNS.mkdir(parents=True, exist_ok=True)
    log = RUNS / f"{time.strftime('%Y%m%d-%H%M%S')}-{args.driver}.log"
    started = time.monotonic()
    result = subprocess.run(cmd, cwd=OPENMONTAGE, env=env, capture_output=True, text=True, check=False)
    log.write_text(result.stdout + "\n--- stderr ---\n" + result.stderr, encoding="utf-8")
    session = session_of(args.driver, result.stdout) or (args.resume or "")
    print(
        json.dumps(
            {
                "driver": args.driver,
                "exit": result.returncode,
                "session": session,
                "seconds": round(time.monotonic() - started),
                "log": str(log),
            }
        )
    )
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())

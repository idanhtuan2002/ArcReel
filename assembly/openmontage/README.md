# OpenMontage in the assembly

- Working copy: `~/assembly-data/openmontage` pinned at OpenMontage `4f682c8` (Python 3.12 venv `.venv`, Remotion
  `npm install`, `piper-tts`, `faster-whisper`). `.env` (mode 600): `OPENAI_BASE_URL=http://127.0.0.1:23340/v1`
  (VieNeu shim, Vietnamese speech through the `openai_tts` tool), `OPENAI_API_KEY=local`.
- Drivers (`python -m assembly.openmontage.run`):
  - `--driver claude`: Claude Code headless, the sponsor's subscription.
  - `--driver codex`: Codex CLI 0.163 with `~/assembly-data/codex-home/config.toml` → NewAPI `DC-codex-agent-LLM`
    (free models), sandbox `workspace-write`.
- Human checkpoints: OpenMontage stops at stage approvals (`skills/meta/checkpoint-protocol.md`); continue with
  `--resume <session> --message "Đã duyệt, tiếp tục"`. Logs: `~/assembly-data/openmontage-runs/`.
- Live board: `cd ~/assembly-data/openmontage && .venv/bin/python -m backlot open <project-id>`.

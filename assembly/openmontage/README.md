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
- Live board **Backlot** (read-only, ported whole from upstream OpenMontage `2e003e6`, not in our `4f682c8` pin):
  worktree `~/assembly-data/openmontage-backlot` of the donor cache, own venv `.venv-backlot` (fastapi, uvicorn,
  watchfiles, pyyaml, jsonschema, pydantic, pillow, python-dotenv); donor tests `tests/backlot/test_state.py`,
  `test_server.py`, `test_gate_scenarios.py`: 54 passed. Runs as user unit `openmontage-backlot` on
  http://127.0.0.1:4750 with `OPENMONTAGE_PROJECTS_DIR=~/assembly-data/openmontage/projects`.
  Limit: our pin writes checkpoints to `pipelines/<id>/`, so the stage rail shows "no pipeline state" until the
  OpenMontage pin moves to a commit that writes them under `projects/<id>/` (after the running ad probe).

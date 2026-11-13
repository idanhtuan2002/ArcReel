#!/usr/bin/env bash
# Local MMAudio ambience server for ArcReel (data disk, port 8002).
set -euo pipefail
ROOT=/mnt/arcreel/D/ArcReel
cd "$ROOT/mmaudio"
export HF_HOME="$ROOT/ace-step-cache/hf"
export ARCREEL_MMAUDIO_VARIANT="${ARCREEL_MMAUDIO_VARIANT:-large_44k_v2}"
export ARCREEL_MMAUDIO_DTYPE="${ARCREEL_MMAUDIO_DTYPE:-float16}"
exec "$ROOT/mmaudio/.venv/bin/python" -m uvicorn mmaudio_ambience_server:app --app-dir "$ROOT" --host 127.0.0.1 --port 8002

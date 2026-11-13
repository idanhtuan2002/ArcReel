#!/usr/bin/env bash
# Local face-identity server for ArcReel (data disk, CPU, port 8003).
set -euo pipefail
ROOT=/mnt/arcreel/D/ArcReel
exec "$ROOT/faceid/.venv/bin/python" -m uvicorn faceid_server:app --app-dir "$ROOT" --host 127.0.0.1 --port 8003

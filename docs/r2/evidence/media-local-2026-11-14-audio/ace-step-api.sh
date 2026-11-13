#!/usr/bin/env bash
# Local ACE-Step 1.5 REST API for ArcReel music beds (DiT only, CPU offload, data disk).
set -euo pipefail
ROOT=/mnt/arcreel/D/ArcReel
cd "$ROOT/ace-step"
export HF_HOME="$ROOT/ace-step-cache/hf"
export ACESTEP_CHECKPOINTS_DIR="$ROOT/ace-step/checkpoints"
export ACESTEP_TMPDIR="$ROOT/ace-step-cache/tmp"
export ACESTEP_CONFIG_PATH=acestep-v15-turbo
export ACESTEP_INIT_LLM=false
export ACESTEP_OFFLOAD_TO_CPU=true
export ACESTEP_OFFLOAD_DIT_TO_CPU=true
export ACESTEP_API_HOST=127.0.0.1
export ACESTEP_API_PORT=8001
mkdir -p "$ACESTEP_CHECKPOINTS_DIR" "$ACESTEP_TMPDIR"
exec "$ROOT/ace-step/.venv/bin/acestep-api"

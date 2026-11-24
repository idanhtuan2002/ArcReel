#!/bin/bash
# Bring DramaClaw up from its pinned checkout with its own release compose file (ASSEMBLY_PLAN M0).
set -euo pipefail
CHECKOUT=${DRAMACLAW_CHECKOUT:-$HOME/.cache/r2-donors/dramaclaw-full}
HERE=$(cd "$(dirname "$0")" && pwd)
DATA=${ASSEMBLY_DATA:-$HOME/assembly-data}/deploy/dramaclaw
mkdir -p "$DATA"
PIN=1277795607f6d9f7e98ea6ae89fdec52d9fff68b  # DramaClaw v2.1.3
[ "$(git -C "$CHECKOUT" rev-parse HEAD)" = "$PIN" ] || { echo "DramaClaw checkout is not at v2.1.3 ($PIN)" >&2; exit 1; }
if [ ! -f "$DATA/.env" ]; then
  sed "s/__random__/$(openssl rand -hex 16)/" "$HERE/env.example" > "$DATA/.env"
  chmod 600 "$DATA/.env"
fi
[ $# -gt 0 ] || set -- up -d
exec docker compose --project-directory "$DATA" --env-file "$DATA/.env" \
  -f "$CHECKOUT/docker-compose.release.yml" -f "$HERE/override.yml" "$@"

#!/usr/bin/env bash
# Run one M8-B parity harness on both sides and write the two observation files.
#
#   tools/parity/dramaclaw/run.sh <harness> <out-dir>
#
# <harness> is a file name under tools/parity/dramaclaw/ (for example graph.parity.test.ts).
# The donor checkout (DONOR_DIR, default ~/.cache/r2-donors/dramaclaw-full) must be at the
# pinned commit with frontend dependencies installed. The harness is copied into the donor's
# frontend/src/__parity__/ and removed afterwards; no donor file is modified.
set -euo pipefail

HARNESS="$1"
OUT="$(realpath -m "$2")"
ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
DONOR_DIR="${DONOR_DIR:-$HOME/.cache/r2-donors/dramaclaw-full}"
PIN="b299bfd9f6fc3e4a1eacc580cc03d5868c2e6e83"
NAME="${HARNESS%.parity.test.ts}"
FIXTURES="$ROOT/frontend/src/features/creative-canvas/__fixtures__/parity/${NAME}.json"

[ "$(git -C "$DONOR_DIR" rev-parse HEAD)" = "$PIN" ] || { echo "donor is not at $PIN" >&2; exit 2; }
[ -z "$(git -C "$DONOR_DIR" status --porcelain --untracked-files=no)" ] || { echo "donor checkout is modified" >&2; exit 2; }
mkdir -p "$OUT" "$DONOR_DIR/frontend/src/__parity__"
cp "$ROOT/tools/parity/dramaclaw/$HARNESS" "$DONOR_DIR/frontend/src/__parity__/$HARNESS"
trap 'rm -rf "$DONOR_DIR/frontend/src/__parity__"' EXIT

(cd "$DONOR_DIR/frontend" && PARITY_FIXTURES="$FIXTURES" PARITY_OUT="$OUT/${NAME}.donor.json" \
  npx vitest run "src/__parity__/$HARNESS")
# The port side records its observations as a file snapshot next to the fixtures; the second,
# non-updating run must reproduce it byte for byte (determinism).
PORT_SNAPSHOT="$ROOT/frontend/src/features/creative-canvas/__fixtures__/parity/${NAME}.port.json"
(cd "$ROOT/frontend" && npx vitest run "src/features/creative-canvas/__parity__/${NAME}.parity.test.ts" --update)
cp "$PORT_SNAPSHOT" "$OUT/${NAME}.port.json"
(cd "$ROOT/frontend" && npx vitest run "src/features/creative-canvas/__parity__/${NAME}.parity.test.ts")
cp "$PORT_SNAPSHOT" "$OUT/${NAME}.port.rerun.json"
echo "wrote $OUT/${NAME}.donor.json, $OUT/${NAME}.port.json and $OUT/${NAME}.port.rerun.json"

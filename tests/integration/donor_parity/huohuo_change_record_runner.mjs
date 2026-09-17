// Test-only R2-DEC-031 parity runner: executes the UNMODIFIED pinned Huohuo
// change-record source and emits one normalized result record per fixture case.
// Never shipped, imported, or started by the ArcReel runtime.
//
// Usage: node --import tsx huohuo_change_record_runner.mjs <cases.jsonl>
// Reads the donor pin + source SHA-256 from R2_M5C_DONOR_BASELINE.json and refuses
// to run if the vendored file's hash does not match.

import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(HERE, "..", "..", "..");

const manifest = JSON.parse(
  readFileSync(resolve(REPO_ROOT, "docs/r2/evidence/R2_M5C_DONOR_BASELINE.json"), "utf8"),
);
const entry = manifest.ports.huohuo_change_record;
const sourcePath = resolve(HERE, "vendor", entry.vendored_path);
const actualSha = createHash("sha256").update(readFileSync(sourcePath)).digest("hex");
if (actualSha !== entry.source_sha256) {
  console.error(
    `donor source hash mismatch for ${entry.vendored_path}: expected ${entry.source_sha256}, got ${actualSha}`,
  );
  process.exit(2);
}

const mod = await import(pathToFileURL(sourcePath).href);

const casesPath = process.argv[2];
if (!casesPath) {
  console.error("usage: node --import tsx huohuo_change_record_runner.mjs <cases.jsonl>");
  process.exit(2);
}
const cases = readFileSync(resolve(REPO_ROOT, casesPath), "utf8")
  .split("\n")
  .map((line) => line.trim())
  .filter(Boolean)
  .map((line) => JSON.parse(line));

const out = [];
for (const testCase of cases) {
  const input = testCase.input;
  out.push({
    id: testCase.id,
    canonicalize: mod.canonicalizeChangeRecordHeaders(input),
    split_structured: mod.splitStructuredBlockAndTrailingProse(input),
    is_structured: mod.isStructuredChangeRecordBlock(input),
    peel_orphan: mod.peelOrphanedStructuredFromProse(input),
    normalize: mod.normalizeChangeRecordArtifacts(input),
    split_prose: mod.splitProseAndChangeRecord(input),
    strip_echo: mod.stripLengthAdjustInstructionEcho(input),
  });
}
process.stdout.write(JSON.stringify(out));

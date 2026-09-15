// Test-only R2-DEC-031 parity runner: executes the UNMODIFIED pinned Take
// shot-vocabulary source and emits one normalized result record per fixture case,
// plus one ordered-vocabulary-dump record per group. Never shipped, imported, or
// started by the ArcReel runtime.
//
// Usage: node --import tsx take_shot_vocabulary_runner.mjs <cases.json>
// Reads the donor pin + source SHA-256 from R2_M6_DONOR_BASELINE.json and refuses
// to run if the vendored file's hash does not match.

import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(HERE, "..", "..", "..");

const manifest = JSON.parse(
  readFileSync(resolve(REPO_ROOT, "docs/r2/evidence/R2_M6_DONOR_BASELINE.json"), "utf8"),
);
const entry = manifest.ports.take_shot_vocabulary;
const sourcePath = resolve(HERE, "vendor", entry.vendored_path);
const actualSha = createHash("sha256").update(readFileSync(sourcePath)).digest("hex");
if (actualSha !== entry.source_sha256) {
  console.error(
    `donor source hash mismatch for ${entry.vendored_path}: expected ${entry.source_sha256}, got ${actualSha}`,
  );
  process.exit(2);
}

const mod = await import(pathToFileURL(sourcePath).href);

const GROUPS = {
  shot_size: mod.SHOT_SIZES,
  camera_angle: mod.CAMERA_ANGLES,
  camera_movement: mod.CAMERA_MOVEMENTS,
};

const casesPath = process.argv[2];
if (!casesPath) {
  console.error("usage: node --import tsx take_shot_vocabulary_runner.mjs <cases.json>");
  process.exit(2);
}
const cases = JSON.parse(readFileSync(resolve(REPO_ROOT, casesPath), "utf8"));

const out = [];
for (const [group, members] of Object.entries(GROUPS)) {
  out.push({ id: `__${group}__`, group, members: [...members] });
}
for (const testCase of cases) {
  const members = GROUPS[testCase.group];
  if (!members) {
    console.error(`unknown group ${JSON.stringify(testCase.group)} in case ${testCase.id}`);
    process.exit(2);
  }
  out.push({
    id: testCase.id,
    group: testCase.group,
    candidate: testCase.candidate,
    valid: members.includes(testCase.candidate),
  });
}
process.stdout.write(JSON.stringify(out));

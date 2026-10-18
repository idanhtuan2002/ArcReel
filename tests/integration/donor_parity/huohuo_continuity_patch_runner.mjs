// Test-only R2-DEC-031 parity runner: executes the UNMODIFIED pinned Huohuo continuity-patch
// source (its model and database imports stubbed, see huohuo_stub_loader.mjs) and emits
// applyContinuityPatches / buildConflictExcerptBlock results per fixture case.
// Never shipped, imported, or started by the ArcReel runtime.
//
// Usage: node --import tsx huohuo_continuity_patch_runner.mjs <cases.jsonl>

import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { register } from "node:module";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(HERE, "..", "..", "..");

const baseline = JSON.parse(
  readFileSync(resolve(REPO_ROOT, "docs/r2/evidence/R2_STORY_DONOR_BASELINE.json"), "utf8"),
);
const vendored = baseline.surfaces.find((s) => s.id === "S07_span_local_repair").vendored;
for (const [relative, expected] of Object.entries(vendored.files)) {
  const actual = createHash("sha256").update(readFileSync(resolve(REPO_ROOT, vendored.root, relative))).digest("hex");
  if (actual !== expected) {
    console.error(`donor source hash mismatch for ${relative}: expected ${expected}, got ${actual}`);
    process.exit(2);
  }
}

register(pathToFileURL(resolve(HERE, "huohuo_stub_loader.mjs")).href);
const mod = await import(pathToFileURL(resolve(REPO_ROOT, vendored.root, vendored.entry)).href);

const casesPath = process.argv[2];
const cases = readFileSync(resolve(REPO_ROOT, casesPath), "utf8")
  .split("\n")
  .map((line) => line.trim())
  .filter(Boolean)
  .map((line) => JSON.parse(line));

const out = cases.map((testCase) => {
  const row = { id: testCase.id };
  if (testCase.patches) row.apply = mod.applyContinuityPatches(testCase.content, testCase.patches);
  if (testCase.conflicts) {
    row.excerpt = testCase.max_chars === undefined
      ? mod.buildConflictExcerptBlock(testCase.content, testCase.conflicts)
      : mod.buildConflictExcerptBlock(testCase.content, testCase.conflicts, testCase.max_chars);
  }
  return row;
});
process.stdout.write(JSON.stringify(out));

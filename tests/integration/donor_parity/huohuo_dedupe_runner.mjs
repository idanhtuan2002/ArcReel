// Test-only R2-DEC-031 parity runner: executes the UNMODIFIED pinned Huohuo intra-chapter
// dedupe source and emits findIntraChapterNearDuplicate's result per fixture case.
// Never shipped, imported, or started by the ArcReel runtime.
//
// Usage: node --import tsx huohuo_dedupe_runner.mjs <cases.jsonl>
// Reads every vendored file's SHA-256 from R2_STORY_DONOR_BASELINE.json (S08) and refuses
// to run if any vendored file differs.

import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(HERE, "..", "..", "..");

const baseline = JSON.parse(
  readFileSync(resolve(REPO_ROOT, "docs/r2/evidence/R2_STORY_DONOR_BASELINE.json"), "utf8"),
);
const vendored = baseline.surfaces.find((s) => s.id === "S08_intra_chapter_dedupe").vendored;
for (const [relative, expected] of Object.entries(vendored.files)) {
  const actual = createHash("sha256").update(readFileSync(resolve(REPO_ROOT, vendored.root, relative))).digest("hex");
  if (actual !== expected) {
    console.error(`donor source hash mismatch for ${relative}: expected ${expected}, got ${actual}`);
    process.exit(2);
  }
}

const mod = await import(pathToFileURL(resolve(REPO_ROOT, vendored.root, vendored.entry)).href);

const casesPath = process.argv[2];
if (!casesPath) {
  console.error("usage: node --import tsx huohuo_dedupe_runner.mjs <cases.jsonl>");
  process.exit(2);
}
const cases = readFileSync(resolve(REPO_ROOT, casesPath), "utf8")
  .split("\n")
  .map((line) => line.trim())
  .filter(Boolean)
  .map((line) => JSON.parse(line));

const out = cases.map((testCase) => ({
  id: testCase.id,
  hit: mod.findIntraChapterNearDuplicate(testCase.input, testCase.min_fingerprint ?? 36),
}));
process.stdout.write(JSON.stringify(out));

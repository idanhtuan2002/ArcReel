// Test-only R2-DEC-031 parity runner: executes the UNMODIFIED pinned Novel Studio
// hardRules source and emits one normalized result record per fixture case.
// Never shipped, imported, or started by the ArcReel runtime.
//
// Usage: node --import tsx novel_hard_rules_runner.mjs <cases.jsonl>

import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(HERE, "..", "..", "..");

const manifest = JSON.parse(
  readFileSync(resolve(REPO_ROOT, "docs/r2/evidence/R2_M5C_DONOR_BASELINE.json"), "utf8"),
);
const entry = manifest.ports.novel_studio_hard_rules;
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
  console.error("usage: node --import tsx novel_hard_rules_runner.mjs <cases.jsonl>");
  process.exit(2);
}
const cases = readFileSync(resolve(REPO_ROOT, casesPath), "utf8")
  .split("\n")
  .map((line) => line.trim())
  .filter(Boolean)
  .map((line) => JSON.parse(line));

const out = [];
for (const testCase of cases) {
  const { contextPack, draftText, modelReport } = testCase.input;
  const hardIssues = mod.runHardRuleChecks(contextPack, draftText);
  out.push({
    id: testCase.id,
    hard_issues: hardIssues,
    merged: mod.mergeContinuityReports(modelReport, hardIssues),
  });
}
process.stdout.write(JSON.stringify(out));

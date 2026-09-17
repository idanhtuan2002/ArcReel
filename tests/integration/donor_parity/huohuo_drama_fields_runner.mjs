// Test-only R2-DEC-031 parity runner: executes the UNMODIFIED pinned Huohuo
// outline-drama-fields source and emits one normalized result record per fixture
// case, plus one shuang_type-vocabulary-dump record. Never shipped, imported, or
// started by the ArcReel runtime.
//
// Usage: node --import tsx huohuo_drama_fields_runner.mjs <cases.jsonl>
// Reads the donor pin + every vendored file's SHA-256 from R2_M6_DONOR_BASELINE.json
// and refuses to run if any vendored file's hash does not match.

import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = resolve(HERE, "..", "..", "..");

const manifest = JSON.parse(
  readFileSync(resolve(REPO_ROOT, "docs/r2/evidence/R2_M6_DONOR_BASELINE.json"), "utf8"),
);
const entry = manifest.ports.huohuo_drama_fields;

let entrySourcePath = null;
for (const file of entry.vendored_files) {
  const sourcePath = resolve(HERE, "vendor", file.vendored_path);
  const actualSha = createHash("sha256").update(readFileSync(sourcePath)).digest("hex");
  if (actualSha !== file.sha256) {
    console.error(`donor source hash mismatch for ${file.vendored_path}: expected ${file.sha256}, got ${actualSha}`);
    process.exit(2);
  }
  if (file.vendored_path === entry.entry_vendored_path) {
    entrySourcePath = sourcePath;
  }
}
if (!entrySourcePath) {
  console.error(`entry_vendored_path ${entry.entry_vendored_path} not found among vendored_files`);
  process.exit(2);
}

const mod = await import(pathToFileURL(entrySourcePath).href);

const casesPath = process.argv[2];
if (!casesPath) {
  console.error("usage: node --import tsx huohuo_drama_fields_runner.mjs <cases.jsonl>");
  process.exit(2);
}
const lines = readFileSync(resolve(REPO_ROOT, casesPath), "utf8").split("\n").filter((l) => l.trim());
const cases = lines.map((l) => JSON.parse(l));

const SHUANGWEN_LABELS = new Set(["恨", "爽", "急", "盼", "爽型"]);

const out = [];
out.push({ id: "__shuang_type_set__", members: [...mod.OUTLINE_SHUANG_TYPE_SET] });

for (const testCase of cases) {
  const section = mod.sliceOutlineChapterSection(testCase.outline, testCase.chapter_number);
  const result = mod.assertOutlineChapterFields(testCase.outline, testCase.chapter_number);
  out.push({
    id: testCase.id,
    section,
    hate: mod.extractTagBlock(section, "恨"),
    shuang: mod.extractTagBlock(section, "爽"),
    ji: mod.extractTagBlock(section, "急"),
    pan: mod.extractTagBlock(section, "盼"),
    shuang_type_raw: mod.extractTagBlock(section, "爽型"),
    ok: result.ok,
    missing: (result.missing || []).filter((m) => SHUANGWEN_LABELS.has(m)),
    invalid: (result.invalid || []).filter((m) => m.startsWith("爽型:") || m.startsWith("赌注错位:")),
    fields_hate: result.fields?.hate ?? null,
    fields_shuang: result.fields?.shuang ?? null,
    fields_ji: result.fields?.ji ?? null,
    fields_pan: result.fields?.pan ?? null,
  });
}
process.stdout.write(JSON.stringify(out));

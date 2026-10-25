# Pure artifact identity and metadata seams

> **For agentic workers:** Use superpowers:executing-plans serially with TDD. This is preparatory host maintenance, not release of an M10 implementation packet.

**Goal:** Expose existing artifact identity/metadata behavior without importing credential-loading host initialization, preserving legacy consumers and wire/schema bytes.

**Architecture:** Extract the existing raw artifact-key codec and leaf validators to r2/artifact_identity.py. Legacy manifest/host modules re-export/delegate to those same functions. Move existing metadata model definitions to r2/contracts/artifact_metadata.py and retain old production-path aliases to the same class objects. Do not change lib/__init__.py or env_init.py.

**Tech Stack:** Existing Python/Pydantic models, standard-library codec, pytest subprocess import guards, Ruff/type/import/dependency gates.

**Source basis:** deployed V2.0.8 /14565f9d8a181654be272267a097ddafe2c87c79. The separate M10 candidate4987526405bd13cc83a950eac9db7a906276baea failed import-purity review; it remains preserved and unaccepted.

## Global constraints

- No M10 QualityProfile/Run/Disposition implementation or acceptance record, DB/schema/migration, credential configuration, provider call or production deployment.
- Preserve legacy lib dotenv initialization for existing callers. New pure entrypoints must not load lib/server/dotenv or mutate environment/project files.
- One canonical codec and one set of metadata class definitions; old names remain usable aliases. Raw codec behavior for existing/unknown key kinds stays unchanged.
- Existing ArtifactKey family validation and metadata normalization remain unchanged. New episode-video convenience helpers have explicit strict/canonical behavior and do not narrow legacy parsing.
- Exact public JSON schema, dump and key-encoding compatibility are measured before extraction and checked afterward. Version/schema labels stay unchanged.
- Work on refactor/r2-pure-artifact-seams in the existing isolated worktree; M10 design branch, M9 and running V2 stay untouched.

## Review focus

- A supposedly pure leaf must not transitively import a host package initializer.
- Re-exports must preserve class identity and old callable names; no parallel model/kernel copies.
- Unicode, unusual generic video IDs, unknown raw key kinds and malformed encodings must retain old behavior.
- Metadata sorting/conflict/aware-time behavior must be unchanged.
- Import purity is tested in a cold process, not a parent process that already cached lib initialization.

## P1: Extract identity kernel

Create r2/artifact_identity.py and tests/unit/r2/test_artifact_identity.py; modify lib/artifact_manifest.py and r2/m3/host_integration.py only to reuse/re-export.

- [x] Capture baseline wire vectors and module/source hashes.
- [x] RED tests for raw encode/decode/unknown kind, old/new function identity, legacy factory wire equivalence, safe M3 target-ref behavior and canonical episode-video decoding.
- [x] Move exact existing codec/parts/number/nonempty/target validators; add pure video convenience functions sharing those primitives. No lib import in the new module.
- [x] GREEN old manifest/deliverable/migration and new identity tests; inspect every semantic delta rather than changing golden values.

## P2: Extract metadata definitions

Create r2/contracts/artifact_metadata.py and mirrored unit tests; modify r2/production/artifact_metadata.py to legacy re-exports.

- [x] Freeze existing four models' schema hashes and representative serialized metadata before code changes.
- [x] RED old/new class identity, schema/dump equality, existing normalization/conflict/missing-basis/aware-time tests.
- [x] Move definitions unchanged, using pure contract-relative imports; no host/production/lib initializer import.
- [x] GREEN metadata and host consumer regressions. Preserve mutable legacy model semantics; M10 later wraps metadata in immutable canonical JSON rather than changing host models.

## P3: Prove purity and integrated compatibility

Create tests/integration/r2/test_pure_artifact_imports.py. No changes to dependency/configuration files.

- [x] RED cold-process probes with trapped load_dotenv, environment mutation, project filesystem writes, process/network authority calls; include all proposed pure M10 dependency entrypoints.
- [x] GREEN: imports complete, environment unchanged, lib/server/env_init absent. Legacy entrypoints keep existing behavior.
- [ ] Run affected tests, test audit and backend static gates. Because shared identity/metadata has broad callers, run the full backend non-E2E gate before final acceptance; do not infer whole-backend health from a few fixtures.
- [ ] One independent critical source/compatibility review; fix material findings with RED/GREEN, then seal exact candidate evidence. No deploy/tag/push.
- [ ] Only after this preparatory seam is reviewed/verified may it be incorporated into the separate M10 design branch and its bounded candidate re-frozen/re-reviewed. No M10 gate is bypassed by this maintenance work.

## Verification checkpoint

- Base remains released V2.0.8 commit `14565f9d8a181654be272267a097ddafe2c87c79`; this branch is local preparatory source work.
- Targeted regression command: existing V2 venv Python, `pytest tests/unit/r2/test_artifact_identity.py tests/unit/r2/contracts/test_pure_artifact_metadata.py tests/integration/r2/test_pure_artifact_imports.py tests/unit/lib/test_artifact_manifest.py tests/unit/r2/production tests/unit/r2/m3 -q -n 0`: **179 passed**, one existing warning.
- Ruff check/format, dependency check and all 23 import contracts passed. Basedpyright with the existing V2 venv: **0 errors, 0 warnings**.
- Independent source review PASS at `7d53046be8526bde910b4c8ca46c76e44a041197`; full non-E2E backend gate is NOT accepted. No acceptance or deployment is claimed.
- The first test collection failed because the new metadata test shared a basename with an existing non-package test module; renamed the new file to `test_pure_artifact_metadata.py`. A source check caught and corrected an underscore/hyphen mismatch in the new video convenience helper; the legacy raw codec and its frozen unknown-kind vectors remain unchanged.
- Successful targeted logs and JUnit: `.superpowers/sdd/2026-10-25-r2-pure-artifact-seams/targeted-verified.log` and `targeted-verified.xml`. The original `targeted.log/xml` were overwritten by the interrupted sandbox run and contain 179 setup errors; they are failed execution evidence, not the passing result. Sandbox Python discovery/process startup stalled; executing the affected local tests and type check outside that sandbox resolved it. No configuration or dependency changes were made.

## Integrated gate result and resume

Full backend was interrupted after 29m48s to inspect existing failures rather than continue repeated ~800s-per-pair M6 renders. Result: **17721 passed,177 skipped,5failed,10unfinished**. This is not a passing or completed gate. Exact unfinished node IDs, hashes, failure attribution and isolated baseline results are recorded in `docs/r2/evidence/R2_PURE_ARTIFACT_SEAMS_REVIEW_2026-10-25.json`.

Three failures reproduce on a disposable archive of released V2.0.8: story Canon authority boundary, story master approval call allowlist, and missing `story:gemini-aistudio` inventory evidence. The scheduler failure passes in isolation on both release and candidate but remains unresolved under load. The M7 scope failure was caused by this session writing checkpoint docs while the cleanliness assertion ran; recheck after committing this checkpoint. Do not loosen authority tests or fabricate route qualification to get green.

Resume this maintenance branch first. Do not merge it into M10 or create an M10 acceptance while its integrated gate remains unqualified. M9 remains paused; released V2 and the rejected M10 design branch remain unchanged. Preserve failed/successful logs separately. No test/render process from the interrupted suite remains active.

## Final source-compatibility checkpoint

The derived local source is verified in docs/r2/evidence/R2_PURE_ARTIFACT_SEAMS_VERIFICATION_2026-10-25.json. Both reported sensor defects are independently FIXED/PASS at a61b1a85d307d9a518bd5f09ff8ab6a92760b0a2; all10 previously unfinished media nodes passed. Focused repair52, consumer48, clean scope1 and pure179 passed. The original interrupted/failed full run remains preserved, not relabeled as PASS. Combined coverage qualifies the unchanged extraction runtime source, not all backend features or M10 runtime. No new provider or deployment is enabled.

# R2-M10 Quality Evidence and Export Packaging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax. Use test-driven development for every behavior change.

**Goal:** Produce authority-separated quality evidence, Human Final Cut dispositions, immutable package selections and deterministic export-only bundles for exact ApprovedMasters.

**Architecture:** A host-integrated M10 deep module separates observation, decision, package selection and local materialization. It reuses accepted predecessor identity, execution, candidate and factual seams only after A0 verifies them on the exact implementation base; PostgreSQL owns metadata and every external tool runs behind a bounded adapter.

**Tech Stack:** Python 3.12+, Pydantic 2.12+, SQLAlchemy 2 async, Alembic, PostgreSQL, FastAPI, React 19, TypeScript, FFmpeg/ffprobe, pytest, Ruff, BasedPyright, import-linter and deptry.

**Spec:** `docs/superpowers/specs/2026-09-16-r2-m10-quality-packaging-design.md`

**ADR:** `docs/adr/0082-m10-quality-evidence-and-export-packaging.md`

**Research:** `docs/research/2026-09-16-r2-m10-quality-evidence-packaging.md`

## Global constraints

- Implementation requires separately accepted M10 design and exact accepted M9/M8/M7/Factual predecessor evidence. Proposed documents authorize planning only.
- The design-acceptance bootstrap is repository-read-only until every
  prerequisite passes. Failure prints a structured diagnostic and may write
  `/tmp/r2-m10-stop.json`; it creates no repository path or dirty Git state.
- Public contracts are frozen, extra-field-forbid Pydantic v2 models using the exact accepted predecessor canonical JSON and digest behavior.
- Every public read/mutation scopes `(user_id, project_name)`; authenticated principal equals `actor_id`; foreign and unknown IDs are indistinguishable.
- Mutations use exact request-digest replay, scoped command-key guard, stable lock order, expected-version CAS, append-only receipts and transactional outbox.
- Probe/model/donor adapters only emit typed evidence. Only the Human custodian issues `PASS`, `REWORK` or `WAIVE`.
- `WAIVE` is reasoned, allowed-scope-only and at most 24 hours. It cannot waive identity, authority, integrity, closure or stale-evidence failures.
- Packaging targets only `PACKAGING_SLOT`; M10 cannot write `ARTIFACT_SLOT`, replace an ApprovedMaster or invoke Production Authority.
- Export is local and deterministic. No packet receives credentials or a network publishing port.
- Tests use deterministic clocks/UUIDs and disposable PostgreSQL for locks, CAS, replay, concurrency and migration evidence. SQLite-only evidence is insufficient.
- Donor acceptance uses exact-pin reachable-surface, same-fixture and defect-fixture evidence with all applicable rows `PARITY` or `IMPROVED` and no required skip/material unknown.
- Each behavior task runs RED → minimal implementation → GREEN → affected regression → test audit → owned-path commit. Zero collected tests fails the task.
- Each packet stops at a clean candidate HEAD for independent review. No next packet begins from an unaccepted predecessor.
- License research and gates are excluded.
- No plan authorizes live migration, credentials, provider/network calls, paid generation, deployment, deletion of production data, publication or Production Approval.

## Fixed file and interface map

| File | Responsibility |
|---|---|
| `r2/contracts/quality.py` | M10-A profile, subject, typed observation, run and disposition contracts |
| `r2/contracts/packaging.py` | M10-B-only package, selection and export contracts frozen after seam revalidation |
| `r2/quality/digests.py` | versioned canonical digest domains |
| `r2/quality/errors.py` | stable stop-code mapping |
| `r2/quality/ports.py` | probe, evidence, custodian, predecessor, packaging and export seams |
| `r2/quality/profiles.py` | profile revisions, publication and CAS heads |
| `r2/quality/parity.py` | pure donor-parity fold |
| `r2/quality/probes.py` | bounded probe orchestration and typed receipts |
| `r2/quality/runs.py` | observation closure and validity projection |
| `r2/quality/dispositions.py` | authorization lease, decision and current-head projection |
| `r2/quality/packaging.py` | package candidate evolution, preview and selection |
| `r2/quality/export.py` | deterministic bundle prepare/materialize/finalize |
| `lib/db/models/quality.py` | M10 SQLAlchemy rows |
| `lib/db/repositories/quality.py` | scoped repositories and unit of work |
| `server/services/quality.py` | host composition and adapters |
| `server/routers/quality.py` | authenticated, migration-gated HTTP interface |
| `frontend/src/features/quality-desk/` | projection-only Quality Desk |
| `scripts/r2/verify_m10_scope.py` | prerequisite, lineage, seam and no-network verifier |
| `scripts/r2/verify_m10_bootstrap.py` | design-acceptance-owned, hash-bound repository-read-only eligibility verifier; exists before M10-A |
| `tests/unit/scripts/r2/test_verify_m10_bootstrap.py` | bootstrap envelope, Git-object, prerequisite and no-repository-write tests |
| `scripts/r2/verify_m10_parity.py` | parity recomputation |
| `scripts/r2/verify_m10_evidence.py` | packet evidence verifier |

Public names and invariants in the spec are normative. A0 may record mechanical
import-path differences; authority, digest, target, validity or lock-order drift
stops `POST_M8_BASE_SEAM_CHANGED` or `M10_SCHEMA_CHANGE_REQUIRED`.

## Design-acceptance bootstrap gate

This gate belongs to the proposed design candidate, not to M10-A implementation.

- [ ] Author `verify_m10_bootstrap.py` and its tests before requesting design
  acceptance. The verifier reads the M10 acceptance contract/schema and all
  candidate/review artifacts from Git objects, rejects duplicate JSON keys and
  fails closed on malformed timestamps, hashes, parents or dirty owned paths.
- [ ] Make `--preflight` verify accepted M9/M8/M7/Factual lineage, singleton
  Alembic head and owned-path cleanliness without creating a repository file.
  Diagnostics go to stdout and optionally `/tmp/r2-m10-stop.json`.
- [ ] Bind exact bootstrap/verifier-test hashes in the M10 design acceptance
  contract and require the acceptance custodian to run the Git-object entrypoint.
- [ ] Prove with a repository snapshot before/after each failing test that no
  tracked or untracked repository path is created or modified.
- [ ] Do not mark ADR-0082 accepted or release M10-A until this gate and the
  independent design-review envelope pass on the same candidate HEAD.

## Packet sequence

| Packet | Independently testable deliverable |
|---|---|
| M10-A | complete profile/probe/run/disposition quality-evidence foundation |
| M10-B | packaging candidate/selection, deterministic export and three export-only pilots |
| M10-C | conditional integrated acceptance without new authority |

Only M10-A is authored now in
`2026-09-16-r2-m10a-quality-evidence-foundation.md`. M10-B/C remain
sequence-locked so their exact integration paths are derived from accepted code.

## Task A: Quality-evidence foundation

**Consumes:** Accepted M10 design and accepted M9/M8/M7/Factual lineage.

**Produces:** Frozen M10 contracts/digests/errors, append-only profile
publication, bounded probes, typed run closure, validity projection, Human
disposition, pure parity fold and M10-A evidence.

- [ ] Execute the M10-A packet A0–A7 sequentially.
- [ ] Stop at its clean evidence HEAD for independent review.

## Task B: Packaging, deterministic export and utility evidence

- [ ] Verify accepted M8 exposes the required schema-evolution path; otherwise stop without modifying M8.
- [ ] Author and independently accept the M10-B contract/digest amendment only
  after that verification; do not reuse provisional §4.2 shapes as frozen code.
- [ ] Add `PackagingCandidate` and closed `PACKAGING_SLOT` only through accepted evolution and differential predecessor tests.
- [ ] RED-test mutable payloads, duplicate assets, stale master/disposition, target confusion, preview expiry, package-head CAS and command conflicts.
- [ ] Implement candidate revision, preview and Human package selection with no Production Authority write port.
- [ ] Port OpenMontage chapter/layout and Kalinga SEO/variant fixtures behind R2 contracts; recompute parity.
- [ ] RED-test unsafe paths, duplicate/case-colliding names, missing assets, byte drift, disk-full, interruption before/after rename and replay.
- [ ] Implement staging with relative normalized paths, per-entry digest/size/media type, canonical manifest, fsync and atomic visibility.
- [ ] Revalidate current selection/disposition before prepare and at finalize; record M7 execution and immutable receipt.
- [ ] Prove deterministic manifests across two clean roots and recovery for every crash cut.
- [ ] Preregister corpora, reviewer qualification/independence, rubrics, smallest useful effect and resource envelope.
- [ ] Implement projection-only profile/run/finding/disposition/package/export views with all supported i18n keys.
- [ ] Test empty, partial, failed, stale, waived, superseded and invalidated states with keyboard/focus/reduced-motion and axe-core.
- [ ] Run Western explainer, vertical factual Short and native `zh-shuang` export-only pilots in that order; do not use provider APIs.
- [ ] Record correction usefulness, disagreement, false-positive/negative review, runtime/RSS/storage and bundle determinism against preregistered baselines.
- [ ] Prove static/runtime absence of network and credential seams; run affected gates, seal M10-B with no required skips/material unknowns and stop.

## Task C: Conditional integrated acceptance

- [ ] Create this packet only if repository acceptance convention cannot bind the accepted M10-A and M10-B evidence directly.
- [ ] Verify exact accepted parent heads, reversible migration chain, parity, resource and three-pilot evidence at one clean integrated HEAD.
- [ ] Add no new contract, authority, adapter or product surface; any such need returns to design review.
- [ ] Seal integrated evidence and stop for final M10 acceptance.

## Completion boundary

M10 is complete only after A/B (and conditional C) are independently accepted
on an exact parent chain, migrations form one reversible lineage, selected donor surfaces pass,
three pilot dossiers pass and the no-network/no-Production-write proof is clean.
Completion permits local export packages only; it does not authorize M11,
credentials, uploads, publication or deployment.

# R2-M10-A Quality-Evidence Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` task-by-task. Use test-driven development for every behavior change.

**Goal:** Establish implementation eligibility and a complete quality-evidence
foundation: frozen contracts/digests, versioned profile authority, bounded probes,
typed run closure, validity/readiness and Human Final Cut disposition.

**Architecture:** A read-only preflight first binds accepted predecessor evidence
and actual seams. The packet then deepens secure local media probing into typed
evidence and keeps profile publication, evidence closure and Human disposition
as separate authorities; it contains no packaging, export or network behavior.

**Tech Stack:** Python 3.12+, Pydantic 2.12+, SQLAlchemy 2 async, Alembic, PostgreSQL, pytest, Ruff, BasedPyright, import-linter and deptry.

**Spec:** `docs/superpowers/specs/2026-09-16-r2-m10-quality-packaging-design.md`

## Global constraints

- Inherit every umbrella-plan constraint.
- A0-preflight is not Task A0 implementation: the hash-bound bootstrap verifier
  belongs to design acceptance, already exists before M10-A and runs before any
  owned production path is created.
- Profile publication is Human-custodian-authorized, append-only and CAS-protected. Adapters/models cannot publish policy.
- The first migration revision/down-revision is derived and frozen from the accepted singleton predecessor; no guessed revision is committed.
- Subprocesses exist only behind the fixed local Quality Probe seam and M7
  execution receipts. This packet exposes no filesystem-export, network,
  credential, Production Authority or packaging write seam.

## Owned paths

| Action | Path |
|---|---|
| Create | `r2/contracts/quality.py` |
| Create | `r2/quality/__init__.py` |
| Create | `r2/quality/digests.py` |
| Create | `r2/quality/errors.py` |
| Create | `r2/quality/ports.py` |
| Create | `r2/quality/profiles.py` |
| Create | `r2/quality/parity.py` |
| Create | `r2/quality/probes.py` |
| Create | `r2/quality/runs.py` |
| Create | `r2/quality/dispositions.py` |
| Create | `lib/db/models/quality.py` |
| Create | `lib/db/repositories/quality.py` |
| Create | accepted-head-derived Alembic revision |
| Create | `scripts/r2/verify_m10_scope.py` |
| Create | `scripts/r2/verify_m10_parity.py` |
| Create | corresponding unit/integration tests and `docs/r2/evidence/R2_M10_A_CANDIDATE.json` |
| Modify | contract/model/repository registries only where exact accepted seams require registration |

## A0-preflight gate

- [ ] Run the acceptance-hash-bound `scripts/r2/verify_m10_bootstrap.py`; verify
  `R2_M10_DESIGN_ACCEPTANCE.json` against its schema and Git-bound
  candidate/review/bootstrap identities. Absent/invalid evidence exits
  `M10_DESIGN_NOT_ACCEPTED`.
- [ ] Verify exact accepted M9/M8/M7/Factual ancestry, clean owned paths and
  singleton Alembic head. Failure prints a structured receipt and may write only
  `/tmp/r2-m10-stop.json`; it makes no repository mutation.
- [ ] Resolve actual canonical JSON/digest, candidate evolution, artifact identity, execution receipt and Factual read seams with source/test evidence; compare to spec.
- [ ] Record exact HEAD, migration predecessor, qualified symbols, signatures, coverage limits and allowed paths in the A0 evidence record.
- [ ] Verify no owned production path already contains conflicting work. Stop rather than overwrite.

Run:

```bash
uv run python scripts/r2/verify_m10_bootstrap.py --preflight
git status --short
```

Expected: preflight reports `IMPLEMENTATION_ELIGIBLE`, exact predecessor/head
identities and no dirty path inside the owned allowlist. Otherwise stop.

## Task A0: Scope verifier

**Produces:** A deterministic verifier that recomputes lineage, seams, migration
head, owned-path allowlist and forbidden dependency surfaces.

- [ ] Write RED tests for missing acceptance, wrong ancestor, dirty owned path,
  multiple migration heads, changed digest behavior, unavailable M8 evolution,
  Production Authority import and network/credential import.
- [ ] Run the focused tests and confirm each fails for the named stop code.
- [ ] Implement pure Git/evidence readers with duplicate-key JSON rejection and
  Git-object reads for acceptance-bound files. Do not trust caller-supplied hashes.
- [ ] Implement AST/import checks that permit subprocess creation only inside the
  bounded probe adapter and forbid export/network/credentials/Production writes
  everywhere in M10-A; confirm allowed predecessor ports.
- [ ] Run focused tests, Ruff, BasedPyright for the verifier and `audit_tests.py --check`.
- [ ] Commit only verifier, tests and A0 evidence; stop if the worktree contains
  an overlapping unrelated edit.

## Task A1: Frozen contracts and digest domains

**Produces:** `QualityPolicyV1`, `QualityProfileRevision`, `AssessedSubject`, the
closed M10-A observation union, assessment requirements/slots, run/disposition/
command contracts and M10-A-only domain-separated digest helpers.

- [ ] Write RED tests for extra fields, mutation, naive timestamps, malformed
  digests, duplicate/empty requirement or slot IDs, non-contiguous profile parent,
  invalid requirement counts/independence, invalid waiver bindings and contract
  round trips. Assert packaging/export types are absent from this module.
- [ ] Write digest vectors proving key-order independence and sensitivity to each
  normative field for every spec §5.1 M10-A domain; assert every §5.2 reserved
  M10-B tag is rejected by the M10-A registry.
- [ ] Implement only the spec contracts plus exact accepted canonical JSON reuse;
  no repository or adapter imports are allowed.
- [ ] Run contract/digest tests twice and compare serialized vectors byte-for-byte.
- [ ] Run affected contract regression tests, Ruff and BasedPyright; commit owned paths.

## Task A2: Stop codes, ports and parity fold

**Produces:** Stable typed errors, minimal foundation ports and pure parity verdict recomputation.

- [ ] RED-test every spec stop code maps to exactly one public error and unknown
  internal exceptions do not leak provider/media/reviewer payloads.
- [ ] Prove profile-publication authorization failures map specifically to
  `M10_PROFILE_PUBLICATION_UNAUTHORIZED`, never to disposition authorization.
- [ ] RED-test parity with empty rows, unbound integrated HEAD, required skips,
  material unknowns, `UNVERIFIED`, invalid `EXCLUDED` and mixed dimensions.
- [ ] Implement only profile, probe, run, Factual-read, disposition-custodian and
  evidence-reference ports; defer packaging and export adapters to M10-B.
- [ ] Reuse the accepted predecessor parity shape when byte-compatible; otherwise
  record an additive schema requirement and stop `POST_M8_BASE_SEAM_CHANGED`.
- [ ] Run focused and affected predecessor parity tests; commit owned paths.

## Task A3: Profile persistence and publication

**Produces:** One reversible migration, scoped repository, profile authorization
lease, append-only revisions, CAS head and transactional receipts/outbox.

- [ ] Derive the revision ID/down-revision from A0 and write upgrade/downgrade/
  upgrade tests on disposable PostgreSQL before the migration implementation.
- [ ] RED-test genesis race, stale CAS, skipped/non-contiguous revision, command
  replay/conflict, cross-user/project access, policy-digest mismatch, authorization
  expiry/revision mismatch and crash cuts around receipt/outbox commit.
- [ ] RED-test `HISTORICAL_ONLY` preserves current readiness until normal expiry,
  while an applicable `REEVALUATE_CURRENT` revision stales it without rewriting
  historical runs or dispositions.
- [ ] Implement preflight authorization outside the transaction. Lease binds
  actor, command, profile/revision/policy digest and admits by DB time within 30s.
- [ ] Implement receipt-first replay, scoped command advisory guard, head lock,
  final authorization recheck, revision/head/receipt/outbox append and commit.
- [ ] Prove advisory-hash collision still serializes only the guard while command
  identity remains the receipt authority.
- [ ] Run disposable-PostgreSQL integration tests plus affected repository tests;
  run migration round trip, Ruff, BasedPyright, import-linter and deptry.
- [ ] Commit the migration/profile slice only after the exact commands are recorded.

## Task A4: Bounded deterministic probes

**Produces:** M7-receipted probe attempts and typed technical observations for
profile-required container/stream, decode, interval, loudness, caption and
reference-valid perceptual checks.

- [ ] RED-test executable/argv allowlists, shell prohibition, local-file-only
  protocol, traversal/symlink policy, input/output/runtime/process ceilings,
  malformed/truncated output, timeout, nonzero exit and unavailable required tool.
- [ ] RED-test profile-specific black/freeze/silence/loudness parameters and
  prove detector intervals remain evidence rather than automatic disposition.
- [ ] RED-test VMAF without named reference, content/timing/geometry comparability,
  exact model/config or bounded alignment; require `M10_REFERENCE_INVALID`.
- [ ] Implement prepare → M7 execution → finalize without a database transaction
  across subprocess I/O. Persist exact tool/build/config/parser/input identities.
- [ ] Prove same-input determinism, exact replay, restart reconciliation and
  declared CPU/runtime/RSS/output ceilings on deterministic fixtures.
- [ ] Run focused probe tests, host `audio_utils` regressions, Ruff and
  BasedPyright; commit only probe-owned paths.

## Task A5: Multi-assessor run closure and validity

**Produces:** Typed observation persistence, complete `QualityRun` closure and
`CURRENT/STALE/EXPIRED/SUPERSEDED/INVALIDATED` projections over an exact master.

- [ ] RED-test missing/duplicate requirement slots, invalid N-of-M/independence
  counts, Human-plus-model combinations, disagreement escalation, invalid `INAPPLICABLE`,
  `INDETERMINATE`, mixed subject/profile, stale tool/config, withdrawn/corrected
  factual evidence, producer conflict, unqualified reviewer and cohort leakage.
- [ ] Implement the Factual Authority read adapter returning exact projection,
  correction head, withdrawal state, digest and validity receipt; add no write port.
- [ ] Implement sorted closed observation unions and recompute all subject,
  observation and run digests rather than trusting caller-provided values.
- [ ] Enforce profile qualification/independence, accessibility/language and
  disagreement rules; model evidence cannot satisfy an independent-Human row.
- [ ] Prove subject/profile/run/tool supersession and deletion invalidation
  preserve historical reads while fail-closing operational readiness.
- [ ] Run focused tests plus current factual/contract regressions; commit only
  run/validity-owned paths.

## Task A6: Human disposition authority

**Produces:** Append-only `PASS/REWORK/WAIVE`, CAS head, readiness projection,
authorization/command receipts and outbox evidence.

- [ ] RED-test non-Human/model/probe issuance, actor/scope mismatch, incomplete
  run, subject/profile drift, 30-second lease admission, receipt replay/conflict,
  advisory-hash collision, stale CAS and every crash cut.
- [ ] RED-test mandatory expiry, profile TTL above seven days, waiver above 24
  hours, forbidden waiver scope and attempts to waive identity/integrity/closure.
- [ ] Implement authorization outside the transaction. Lease binds exact actor,
  command, subject, run, decision and policy revision and admits using DB time.
- [ ] Implement receipt-first replay, scoped command guard, stable profile/run/
  subject/disposition lock order, final revalidation and atomic decision/head/
  receipt/outbox append.
- [ ] Implement readiness as a recomputed projection, never a mutable boolean;
  `REWORK` exposes repair routing but has no production mutation port.
- [ ] Prove concurrent first-call convergence, exact retry after commit ambiguity,
  expiry/supersession and restart on disposable PostgreSQL; run affected gates.

## Task A7: Quality fixtures and candidate evidence

**Produces:** Exact-pin Kalinga quality/lint fixtures plus machine-verifiable
M10-A candidate evidence. OpenMontage export/layout parity belongs only to M10-B.

- [ ] Freeze selected Kalinga quality/lint paths, pin, runtime identity, behavior rows,
  fixture digests, intentional differences and resource commands.
- [ ] Port only pure Kalinga profile/lint/parity fixtures needed by M10-A; no donor runtime,
  pipeline, filesystem authority or self-score crosses the seam.
- [ ] Run same-fixture and donor-defect tests; require each applicable dimension
  `PARITY` or `IMPROVED`, zero required skips and zero material unknowns.
- [ ] Run all M10-A tests, affected contract/repository tests, test audit, Ruff,
  format check, BasedPyright, import-linter, deptry and `git diff --check`.
- [ ] Generate `R2_M10_A_CANDIDATE.json` from the clean candidate tree with exact
  HEAD parent, file hashes, commands/results, migration proof, parity, resource
  evidence, dirty paths and explicit forbidden-surface proof.
- [ ] Commit only owned paths, rerun the evidence verifier from the candidate
  commit and stop for independent review. Do not begin M10-B.

## Completion boundary

M10-A is complete only after separate acceptance binds its clean candidate HEAD,
all required commands pass with nonzero test selection, migration restoration is
proved, donor parity has no skip/unknown and the forbidden-surface verifier finds
no export, network, credential, packaging or Production write route. Probe
subprocesses must be reachable only through the accepted bounded adapter.

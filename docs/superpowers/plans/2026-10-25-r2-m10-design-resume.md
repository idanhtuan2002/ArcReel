# M10 V2 design completion plan

> **For agentic workers:** Use superpowers:executing-plans for this bounded design packet. Keep original M10-A A0-A7 intact; this plan does not release that implementation packet.

**Goal:** Resume the remediated M10 design on deployed V2.0.8 and prepare an executable design-freeze candidate without discarding prior research.

**Architecture:** Reuse original contracts and host authority seams. Complete the design-owned eligibility bootstrap before product code. M9 stays paused; original architecture acceptance stays immutable.

**Tech Stack:** Git-object reads, JSON evidence, Python verifier/tests, existing PostgreSQL/M7/M8 contracts as dependencies.

**Spec:** `docs/superpowers/specs/2026-09-16-r2-m10-quality-packaging-design.md` plus proposed `docs/superpowers/specs/2026-10-25-r2-m10-v2-rebase.md`.

## Global constraints

No acceptance fabrication, M9 edits, provider calls, production mutations, migration or package/export implementation. Restore originals at their audited exact hash; record additive changes in the rebase document. Human auth leases remain action-bound, at most30 seconds; WAIVE at most24 hours; ordinary dispositions at most7 days. All seven typed observations and stable assessment requirements remain. A cannot freeze B contract/digest domains.

## Review focus

- A release label and passing host tests must not be mistaken for M10 acceptance.
- An admin login must not become a Human profile/disposition lease.
- A fixture ClaimLedger must not become a durable factual currentness receipt.
- A receipt replay must not assert fresh operational readiness.
- A bootstrap failure must leave both tracked and untracked repository bytes unchanged.

## Task D1: Restore and revalidate current base

- [x] Preserve final V2.0.8 production evidence without private project data.
- [x] Merge deployed V2.0.8 locally into isolated M10 branch, preserving history.
- [x] Restore five original documents from50f1e9b41 and compare all audited hashes.
- [x] Refresh checkpoint hashes and run six existing-seam test files;93 tests pass.
- [x] Confirm singleton Alembic head without migration.
- [x] Draft explicit responses to10 audit findings and six builder questions; retain unproved conditions as pending.
- [x] Independent preliminary gap review at9a58b602: two confirmed defects and one applicability risk; repaired in one pass. This is not a normative PASS.

## Task D2: Complete concrete acceptance dependencies

- [ ] Read the canonical master identity/transaction seam and freeze explicit MasterBinding fields and domain vectors; test full source closure movement and mismatched approval identity.
- [ ] Record the narrowly scoped sequencing amendment needed for paused M9; name its reviewer/acceptance boundary without editing old accepted evidence.
- [ ] Bind concrete profile/disposition custodian requests/leases and qualified host adapter; identify exact allowed action/scope and revocation/currentness checks.
- [ ] Bind the durable Factual read adapter and receipt, or keep operational factual profile admission blocked. Do not rewrite its requirement as an optional slot.
- [ ] Derive concrete migration predecessor and exact owned allowlist from accepted base. No migration runs in this packet.

- [ ] Test the authority/lifecycle matrix: HISTORICAL_ONLY preserves readiness, alternative runs do not revoke Human disposition, explicit policy/evidence/disposition changes invalidate only their declared bindings. Include PostgreSQL interleavings.

## Task D3: Design-owned bootstrap

Files: `scripts/r2/verify_m10_bootstrap.py`, mirrored unit/integration tests, acceptance contract/schema under `docs/r2/evidence/`.

- [x] Draft strict acceptance JSON Schema; meta-schema check passes and rejects empty/status-only records. Distinct reviewer identities, exact Git custody and prerequisites still require the executable verifier; schema validity is not acceptance.

- [ ] RED: missing acceptance, changed candidate/review/test hash, duplicate JSON key, invalid timestamp, wrong acceptance parent, same-author reviewer, mismatched predecessor, dirty owned path and multiple migration heads.
- [ ] Implement Git-object envelope reads and strict schema/identity validation. Verifier reads do not execute candidate imports. Diagnostic output is sanitized; no repository writes on failure.
- [ ] GREEN: fixture-only accepted envelope is valid only with exact synthetic Git lineage and every dependency; a test success grants no real acceptance.
- [ ] Integration: before/after tracked/untracked snapshots on every refusal; exact source invocation from Git object; nonzero tests, static checks and test audit.
- [ ] Bind verifier/test/schema/source hashes to one clean design candidate.

## Task D4: Normative freeze

- [ ] Two qualified independent blind reviews on the same candidate; max one background reviewer at a time, no fan-out. Author is neither reviewer.
- [ ] Repair findings; changed normative bytes require reviews of the changed candidate. Do not call a preliminary gap review a normative PASS.
- [ ] Separate custodian acceptance commit binds hashes, exact reviewed HEAD, review records, empty required skips/material unknowns and eligible prerequisite chain.
- [ ] Run read-only bootstrap from the committed entrypoint; only IMPLEMENTATION_ELIGIBLE releases original M10-A A0.

D1 source/test refresh is complete. D2-D4 are not complete. The next implementation task remains original A0 only after this design gate; M10-B is not released.

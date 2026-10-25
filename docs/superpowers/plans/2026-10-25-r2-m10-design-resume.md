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

- [x] Read canonical host identity/transaction seams; propose explicit MasterBinding fields and encoding vectors in2026-10-25-r2-m10-foundation-bindings.md and R2_M10_MASTER_BINDING_VECTORS.json. Eight bound-field changes alter the digest; key order does not.
- [ ] Normatively freeze those contracts and prove identity-mismatch refusal/full transitive currentness in A1/A5; encoding vectors alone do not establish this.
- [x] Record scoped sequencing proposal and reviewer/acceptance boundary in the concrete bindings document; old acceptance unchanged. Original predecessor policy remains enforced until separately accepted amendment.
- [x] Bind separate publication/disposition requests,30-second DB-time leases and current revocation checks. Existing Showrunner reader is not an M10 action adapter.
- [ ] Qualify concrete action-specific host adapter before operational admission; no such qualification is claimed.
- [x] Specify exact durable factual receipt/transaction requirements and keep operational factual admission blocked; no fixture substitution or optional-slot conversion.
- [x] Bind observed predecessor918c4a0e0001 and deterministic proposed revision derivation; bootstrap forbids migration graph drift. No migration created/executed.
- [ ] Freeze final exact production migration/registry allowlist on the accepted base before A0; original owned-path list remains the source.

- [ ] Test the authority/lifecycle matrix: HISTORICAL_ONLY preserves readiness, alternative runs do not revoke Human disposition, explicit policy/evidence/disposition changes invalidate only their declared bindings. Include PostgreSQL interleavings.

## Task D3: Design-owned bootstrap

Files: `scripts/r2/verify_m10_bootstrap.py`, mirrored unit/integration tests, acceptance contract/schema under `docs/r2/evidence/`.

- [x] Draft strict acceptance JSON Schema; meta-schema check passes and rejects empty/status-only records. Distinct reviewer identities, exact Git custody and prerequisites still require the executable verifier; schema validity is not acceptance.

- [x] RED observed: module absent initially; subsequent regression cases expose ignored owned/uncommitted migration omissions, candidate-scope/stop-code omissions and schema remote resolution. Other listed refusal cases covered by focused tests.
- [x] Implement structural Git-object envelope, artifact/parent/review/prerequisite/schema/graph checks. No candidate imports, migration execution, external schema references, diff drivers or repository writes.
- [x] GREEN: complete synthetic closure accepted; invalid closure refused. Qualification/independence/blindness declarations still require substantive review; fixture success grants no real acceptance.
- [x] Integration: before/after complete repository snapshots on every refusal; exact source extracted from Git object;94 affected tests pass, Ruff/type checks/import contracts/dependency check/test audit pass. See bootstrap candidate evidence for exact scope/results.
- [x] Bind source/test/schema hashes in R2_M10_BOOTSTRAP_CANDIDATE_2026-10-25.json. Bounded code review found4 defects; all repaired in one RED/GREEN pass. This does not freeze/accept the design.

## Task D4: Normative freeze

- [ ] Two qualified independent blind reviews on the same candidate; max one background reviewer at a time, no fan-out. Author is neither reviewer.
- [ ] Repair findings; changed normative bytes require reviews of the changed candidate. Do not call a preliminary gap review a normative PASS.
- [ ] Separate custodian acceptance commit binds hashes, exact reviewed HEAD, review records, empty required skips/material unknowns and eligible prerequisite chain.
- [ ] Run read-only bootstrap from the committed entrypoint; only IMPLEMENTATION_ELIGIBLE releases original M10-A A0.

D1 source/test refresh and D3 structural bootstrap tooling are complete as development work, not normative acceptance. D2 has concrete proposals but its contract/concurrency/qualification freeze remains incomplete; D4 remains incomplete. The next implementation task remains original A0 only after this design gate; M10-B is not released.


## Bounded contract sequencing proposal

The operational D2 prerequisites above are not constructor prerequisites. See
2026-10-25-r2-m10-contract-foundation.md and its contract-packet spec/manifest.
This proposed A0/A1-only ceremony requires two independent reviews and a distinct
acceptance record; it cannot mark this full-M10 D4 complete or qualify any runtime
adapter. The original four-owner/default bootstrap remains enforced. Do not
implement the bounded product files before its separate envelope is accepted.

## Pure-source preparation and bounded re-review

The legacy-import candidate4987526405bd13cc83a950eac9db7a906276baea is withdrawn after FAIL, not accepted. Verified local maintenance base dda0f273e035615e1c10a67f8712279d23b7053c descends from released V2.0.8 and exposes the shared identity/metadata definitions without host initialization. See R2_PURE_ARTIFACT_SEAMS_VERIFICATION_2026-10-25.json for exact source/review/combined-test evidence and limits. It does not qualify M10 runtime or change the release.

The bounded proposal now pins that separate implementation base and proof, the27 observed pure import files, project configuration/lockfile bytes and regular-file modes. Dirty imported siblings are relevant dependencies. M7/M8 proofs still bind the released ancestor; the nine-path A0/A1 scope and original full gate remain unchanged. Freeze a fresh normal single-parent candidate after affected verifier/type/audit checks and live refusals, then obtain two new blind reviews of that same candidate. Do not reuse earlier FAILs or maintenance review PASS as M10 design acceptance.

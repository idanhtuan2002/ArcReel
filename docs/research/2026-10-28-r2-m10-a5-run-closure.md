# M10 A5 research: multi-assessor run closure and validity

Date: 2026-10-28. Base: A4 source candidate `a57d7c631` (branch `design/r2-m10-a5-run-closure`).
Status: research only. Nothing below is an accepted decision.

## Source task

`docs/superpowers/plans/2026-09-16-r2-m10a-quality-evidence-foundation.md` Task A5 produces typed
observation persistence, complete `QualityRun` closure and `CURRENT/STALE/EXPIRED/SUPERSEDED/INVALIDATED`
projections over an exact master. It must:

- reject missing/duplicate slots, invalid N-of-M/independence counts, Human+model mixes, unescalated
  disagreement, invalid `INAPPLICABLE`/`INDETERMINATE`, mixed subject/profile, stale tool/config,
  withdrawn/corrected factual evidence, producer conflict, unqualified reviewer and cohort leakage;
- implement a Factual Authority **read** adapter (exact projection, correction head, withdrawal, digest,
  validity receipt) with no write port;
- recompute subject/observation/run digests from closed sorted unions;
- enforce qualification/independence, accessibility/language and disagreement rules; model evidence
  never satisfies an independent-Human row;
- keep historical reads while fail-closing operational readiness under supersession/deletion.

The A4 spec (§Purpose) also hands A5: dependency and content-basis currentness of the master binding,
original A3 readiness, accessibility and factual admission.

## Facts (verified in this tree)

1. Frozen A1 contracts already define the closure shapes: `AssessmentRequirement` (ALL / N_OF_M,
   `minimum_satisfied_slots`, disagreement policy, acyclic escalation), `AssessmentSlot`
   (kind, assessor class, qualification policy id/digest, rule ids), `AssessmentSlotResult`
   (SATISFIED / NOT_APPLICABLE / FAILED / INDETERMINATE, parallel refs/digests, distinct independence
   groups, escalation refs), `QualityRun` (closure invariants: primary refs equal observation refs,
   sorted execution refs) and `CompleteRunCommand` (`r2/contracts/quality.py`). Digest domains include
   `m10.observation-closure.v1` and the per-type observation domains (`r2/quality/digests.py`).
2. Observation types: TECHNICAL (A4 producer exists), FACTUAL, NARRATIVE, CONTINUITY,
   PERCEPTUAL_REGRESSION, ACCESSIBILITY. Assessor classes: DETERMINISTIC, AUTHORITY, MODEL, HUMAN.
3. The only persisted observation producer today is A4 (`m10_quality_probe_observations`). No table
   stores Human/model/authority observations.
4. No Factual Authority store exists. `ClaimLedger` / `ResearchPack` are contracts used only by the
   M3 fixture loader (`r2/m3/factual_fixture.py`); there is no persisted correction head or withdrawal
   state. ADR-0092 Gate B "script lock" records digests only, not claims.
5. The M10 design (§4 QualityRun) requires, for the first profile, deterministic media inspection,
   deterministic package-integrity/metadata checks and an **authenticated Human semantic rubric**;
   automated semantic/model adapters are outside the first packet. §6 fixes the writer lock order:
   M10 command advisory key → candidate head → preview → master authority rows (sorted) →
   profile head, run head, disposition head.
6. Reusable seams: `QualityProfileRepository.get_revision` (A3), `MasterAuthorityRepository.get_current`
   (M7), interactive JWT reauthentication pattern (A3 custodian, A4 service), A4 probe receipts with
   full-chain replay, `pg_advisory_xact_lock` command guards, append-only trigger migration pattern.

## Inferences

- A5 needs one new authenticated write path for Human (and later model) observations; A4 is the only
  technical producer, so run sealing consumes A4 observations by stored reference, never caller bodies.
- Factual requirements cannot be satisfied without an accepted Factual Authority. Fail-closed
  (`M10_REQUIRED_EVIDENCE_MISSING` for any FACTUAL slot) is consistent with the A4 flag
  `factual_admission_qualified=false` and with "add no write port".
- Validity states are projections recomputed at read time from immutable rows plus current heads
  (master authority, profile head, tool/config catalog, freshness rules); none is a stored boolean.

## Unknowns

- U1 Whether the sponsor wants a Factual Authority owner built before M10-A acceptance (scope decision).
- U2 Exact qualification-policy resolution for Human reviewers (which registry proves a reviewer is
  qualified for a slot's `qualification_policy_id`); no qualification store was found yet.
- U3 Accessibility observation producer (captions/audio description) beyond A4 caption timing.
- U4 Whether CONTINUITY / PERCEPTUAL observations are in the first packet (design §4 says model
  adapters are out; these may stay unsatisfiable like FACTUAL).

## Options for the Factual adapter

- F1 (default proposed): read port present, resolver returns required-evidence-missing until an
  accepted authority exists; FACTUAL slots never satisfy. No new authority, no write port.
- F2: build a minimal Factual Authority store now. Out of A5 scope; needs its own design and sponsor
  approval.
- F3: treat M3 fixture ledgers as authority. Rejected: fixtures confer no authority.

## Next

Write the A5 design spec (owned paths, tables, lock order, closure algorithm, validity projection,
Human observation submission, qualification resolution) and resolve U2–U4 against code before freeze.

## Extended research (2026-10-28, after sponsor asked for research-backed decisions)

### Factual authority — sources reviewed

- Frozen responsibility matrix `docs/r2/R2_02_FROZEN_RESPONSIBILITY_MATRIX.md`: factual claim truth is owned
  by `FactualAuthorityService` (R2 Factual Authority: source capture, research synthesis, claims). M10 is a
  consumer, never an owner (rule A forbids Claim → Canon writes; quality may only reference).
- Decided expansion order `docs/r2/R2_V2_CAPABILITY_AND_V3_BOUNDARY.md` §V3: (1) M9 research with factual
  authority and Gate A, then (2) M10, "one authority packet at a time, in the decided order".
- M10 design (2026-10-23) §1: M9 paused; M10 consumes approved-master/candidate infrastructure only and is
  prohibited from consuming any planned M9 call surface; acceptance gate "Sequencing" repeats this.
- A2 reuse research (2026-10-26): `r2/contracts/factual.py` ResearchPack/ClaimLedger are mutable objects,
  not a durable current-authority reader; they must not enter frozen M10 ports.
- Code: no `FactualAuthorityService` in this tree; paused M9 branches `impl/r2-m9a-*` (04b1b9218),
  `impl/r2-m9b-*` (b0de59b22) and `design/r2-m9-v2-revalidation` (39b9c5dab) contain only the same
  contracts, M3 fixtures and opportunity ports — no persisted correction head or withdrawal state.
- M10 design §4/§5: the first (export-only) profile requires deterministic media/package checks and an
  authenticated Human semantic rubric; factual assessment is not a first-packet requirement.

### Reviewer qualification — sources reviewed

- Existing authority: signed governance grant events with role `HUMAN_SHOWRUNNER` scoped by
  user/project/principal (`r2/governance/grant_transition.py`), read through
  `CheckpointedShowrunnerGrantReader` with governance-activated startup; A3 profile publication already
  depends on it (`server/services/quality_profile_custodian.py`).
- M10 design §4: the Human rubric is recorded by an authenticated Human; "the same human may later issue
  the disposition explicitly" — one accountable Human operator per project in the first packet.
- Donors: OpenMontage review data carries one `ReviewerType` and a timestamp, no qualification binding
  (2026-09-16 research); Kalinga quality fixtures concern lint/profile parity, not reviewer identity.
  Neither offers a stronger qualification mechanism to reuse.
- No other reviewer/qualification registry exists in code or ADRs.

### Decisions (main adjudication, research-backed)

- D1 Factual: A5 ships the `FactualReadPort` consumer seam with **no authoritative implementation**; every
  FACTUAL slot fails closed with `M10_REQUIRED_EVIDENCE_MISSING` and cannot satisfy, waive or be marked
  INAPPLICABLE. No Factual Authority, write port or M3/M9 fixture data is introduced. Factual admission
  becomes possible only after M9's Factual Authority is accepted (decided order). This does not block the
  first export-only profile, which has no factual requirement.
- D2 Human qualification: a HUMAN slot is qualified only by a current signed `HUMAN_SHOWRUNNER` grant for
  the exact user/project/principal, read under governance-activated startup through the existing reader,
  bound by a code-embedded qualification policy (`m10.qualification.human-showrunner.v1`) whose digest the
  slot's `qualification_policy_digest` must equal. MODEL and AUTHORITY slots have no qualified adapter in the
  first packet and fail closed; model evidence never satisfies a HUMAN slot. DETERMINISTIC slots are
  satisfied only by A4 receipts.
- Consequence for U3/U4: ACCESSIBILITY beyond A4 caption timing, CONTINUITY and PERCEPTUAL slots have no
  qualified producer in the first packet and fail closed the same way.

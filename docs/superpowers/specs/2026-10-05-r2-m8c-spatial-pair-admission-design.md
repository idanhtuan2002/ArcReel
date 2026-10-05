# M8-C spatial pair admission: bounded design packet

**Status:** proposed, 2026-10-05. This narrows ADR-0102 for the first Take-derived `LOCATION` binding. A two-frame binding alone is not suitable or live READY.

## Source state and decision

At code HEAD `e78ec434`, `LocationBindingCreationService` creates a current Shot/Scene binding from two verified M7-derived frame receipts. `CurrentLocationBindingSnapshotReader` rechecks target, binding, receipts, parent masters and PNG bytes. Neither assigns `MASTER`/`REVERSE` roles or judges geometry. M4 `ProductionReadinessEvaluator` is pure: a matching binding makes the role READY using a caller-supplied snapshot ref. It cannot be exposed as live spatial readiness authority yet.

ADR-0102 and the pinned donor comparison require an accountable human decision that both views depict the same target location from one camera point with approximately opposite directions. The existing `m8c_source_digest_vectors.json` APPROVE/REJECT cases use placeholder authorization and evidence digests. They prove serialization only. The adaptation decision kernel supplies a reusable exact-command authorization pattern: a trusted port returns typed authorization, and the kernel checks current authenticated principal, action and command identity hash. A caller-authored reviewer string or digest is insufficient.

Choose a separate versioned `SpatialPairAdmission` head keyed by scoped binding ID. Retain the existing binding body and source claims. The pair head is a revocable suitability decision, not media approval or geometric proof.

## Command and decision contract

The server-internal command receives trusted `(user_id, project_name, authenticated_principal)`, command ID, expected current Shot ref, expected current binding version/envelope digest, two exact receipt ID/digest pairs assigned once each to `MASTER` and `REVERSE`, decision `APPROVE` or `REJECT`, and reviewed evidence. Scene `location_ref` and binding `semantic_ref` must match. Pair ID derives from scoped binding ID under a named domain; the command cannot choose an unrelated pair or target.

Reviewed evidence needs inspectable content for view coverage, common camera center and yaw relation. The first packet should store a typed immutable human observation body, including exact frame refs and the reviewer’s findings, within the decision record and digest it. External evidence refs are admissible only with a tested scoped immutable resolver. The existing opaque `ev-*` vector refs cannot authorize approval. REJECT needs a reason and is a first-class decision. A trusted authorization port binds principal, scope, `HUMAN_SHOWRUNNER` role, action, command digest and authentication receipt; only its result may be stored. No public route is included here.

The immutable decision stores pair ID/version, exact target and Scene refs, stable binding core digest, role-assigned receipt refs, decision, evidence and its digest, reviewer, exact authorization and its digest, decision time, command digest and decision digest. Stable core covers scope, binding ID, target refs, semantic/production/asset refs and both source claim digests. It omits binding version, body digest and spatial-set fields so a later spatial promotion can advance the binding version without changing the human suitability judgment. A target, core-ref or source-claim change alters core digest and requires a new pair decision. The current pair head points to one decision; REJECT replaces APPROVE as current and removes suitability immediately.

## Transaction and current read

The command checks prior receipt integrity, then locks/revalidates current screenplay admission, Scene, Shot, binding head, pair head and sorted M7 parent heads in that order. It verifies receipts, parent projections, candidates and PNG bytes in the same transaction before appending a decision and advancing the pair head with expected-version CAS. An absent pair head uses insert-if-absent genesis claim and locked reread. Command receipt inserts last; a unique-key loser rolls back and reads the winner in a new transaction. Exact replay rechecks current target, binding core and sources. A historical APPROVE receipt cannot prove current suitability after REJECT or upstream advance.

A transaction-bound current pair reader follows the same admission → target → binding → pair → M7 order. It rehashes stored decision/evidence/authorization and checks current binding core, role assignment and bytes. It returns an approved typed pair snapshot only when current decision is APPROVE; absent, REJECT, stale and corrupt states fail closed. A separate live readiness adapter will read pair and binding snapshot in one authority transaction, then feed the pure M4 evaluator. Until that adapter exists, generation/promotion may not treat caller-supplied bindings as live READY.

## Verification and open choices

Freeze Preparation-canonical vectors for pair identity, stable core, exact command, evidence, authorization, decision and result. Keep earlier M8 pair vectors as synthetic examples. Test APPROVE→REJECT, role swap, duplicate/foreign frames, stale target/core/receipt/parent, media tamper, wrong reviewer scope, changed-body replay, command race and late rollback. Force PostgreSQL interleavings and record exact blocker PIDs. Independently review exact HEAD. Pair authority remains separate from M8 promotion, spatial constraint storage, generation routing and release acceptance.

Before implementation, select the trusted human authorization port and authenticated route context; fix typed observation fields and size limits against the actual reviewer workflow; and design a shared transaction-bound reader so standalone snapshot reads do not reacquire earlier locks after the pair head. The adaptation decision family does not currently include pair admission.

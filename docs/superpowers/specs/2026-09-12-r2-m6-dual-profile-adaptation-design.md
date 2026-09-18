# R2-M6 Dual-Profile Adaptation and TakeDirector Design

**Date:** 2026-09-12

**Status:** accepted design; implementation is not authorized by this document

**Prerequisite:** final accepted M5C handoff at an exact clean implementation
HEAD; the currently observed dirty M5C worktree is research evidence only.

**Authoritative decision:**
`docs/adr/0077-dual-profile-adaptation-lineage-and-policy-evidence.md`

**Research:**
`docs/research/2026-09-12-r2-m6-dual-profile-adaptation-research.md`

## 1. Goal

M6 implements the smallest auditable fiction-adaptation path that can produce
and compare both requested drama forms:

```text
one exact Canon parent
  -> WESTERN_GENERIC AdaptationBranch
  -> CN_SHORT_DRAMA_SHUANGWEN AdaptationBranch
  -> independent maps, evaluations, approvals and locked screenplays
  -> shared TakeDirector contract
  -> typed ShotSpecV2
  -> existing readiness, production candidate and ApprovedMaster boundaries
  -> two separately reviewable Golden B slices
```

The design preserves the frozen distinction between Canon truth, adaptation
divergence, screenplay approval, direction, and production approval. It adds no
second Canon writer and grants no authority to profiles, rules, donors, Agents,
providers, directors, or projections.

## 2. Final decisions

1. M6 v1 uses one sibling `AdaptationBranch` per profile, pinned to the same
   immutable parent Canon version for the Golden B comparison.
2. A branch binds exactly one `profile_id`, `profile_version`, and
   `policy_pack_digest`. Changing any of them creates a new branch.
3. Frozen `adaptation_policy` remains only the fidelity stance. It does not carry
   profile identity.
4. Profile-specific outputs are typed immutable sidecars. Shared authority binds
   their exact digests when it relies on them, but never stores their rule bodies.
5. The nine frozen adaptation operations remain closed for v1. An unclassifiable
   change is rejected for review rather than mislabeled.
6. One Human Showrunner map-approval decision binds the exact complete map
   version/hash after all entry review evidence is present. Every relied-on
   report resolves in scope, binds the exact map hash, and its ordered sidecar
   ref/digest exactly matches the map's ordered `profile_analysis_refs`. Each
   sidecar identity is derived from exact artifact ID/version plus profile, resolves
   in scope, and passes semantic hash recomputation.
7. One Human Showrunner screenplay-admission command atomically appends the
   approval decision and advances the locked screenplay head for the exact
   screenplay/map/profile/evaluation tuple.
8. Shared integrity findings are never waivable. A Human Showrunner may waive a
   profile finding only with an exact report/rule/finding/artifact/policy binding
   and rationale. Matching bytes or a same-named finding in another report is not
   identity. Semantic or policy change invalidates applicability.
9. Every Human authorization binds the canonical command hash. A screenplay
   `REVOKE` clears effective use authority, and every approved-screenplay read
   revalidates the locked authoritative head and complete decision fold. `REVOKE`
   targets the current effective ADMIT's exact immutable context without requiring
   its historical dependencies to remain current. Reader authorization is checked
   at read time; it is not an in-flight execution-cancellation lease.
10. `ShotSpecV2` adds Take-derived typed shot vocabulary. v1 remains byte/hash
   stable; reads accept v1 and v2, new Take output writes v2, and unknown legacy
   strings require explicit Human mapping.
11. Golden B contains two 60–120-second slices from one pinned Canon source. It
    is a controlled isolation/comparison fixture, not evidence of universal
    Western form or a native Chinese benchmark.

## 3. Domain boundaries and authority

| State | Classification | Sole writer | Cannot do |
|---|---|---|---|
| Profile pack and source manifest | immutable configuration/provenance | release/configuration process | approve content or mutate Canon |
| Adaptation branch/map/screenplay proposal | immutable proposal evidence | `AdaptationEvidenceService` | advance an authority head |
| Profile analysis and report | immutable diagnostic evidence | pure evaluator wrapped by evidence service | approve, waive, lock, or rewrite content |
| Map approval, policy waiver, screenplay approval/lock | append-only Human decision authority | `AdaptationAuthorityService` | mutate Canon or approve production master |
| Adaptation effective heads | rebuildable lock/index projections | internal authority kernel only | independently confer authority |
| SceneSpec/ShotSpec | provider-neutral direction output | `TakeDirectorAdapter` through existing Director execution | create jobs or approve candidates |
| Production candidate/master | existing Production evidence/authority | existing M4 services | change adaptation or Canon authority |

All public reads and writes are scoped by `(user_id, project_name)`. Unknown and
cross-scope opaque IDs have the same public not-found shape. Global ID collision
returns a non-disclosing identity conflict.

## 4. Contract model

### 4.1 Profile identity

```text
AdaptationProfileRef
  profile_id: WESTERN_GENERIC | CN_SHORT_DRAMA_SHUANGWEN
  profile_version: non-empty immutable version
  policy_pack_digest: sha256 digest of canonical manifest bytes
```

The manifest records every rule ID/version/disposition, source identity, donor
revision/path/SHA where applicable, applicability scope, and evaluator version.
Runtime code resolves by exact ref and verifies the digest. There is no `latest`,
inheritance, hot reload, arbitrary rule DSL, or third-party execution in M6 v1.

### 4.2 Versioned adaptation contracts

M6 introduces successor schemas rather than reinterpreting frozen fields:

```text
AdaptationBranchV2
  frozen AdaptationBranch fields
  profile_ref: AdaptationProfileRef

AdaptationMapV2
  frozen AdaptationMap fields
  content_hash
  profile_analysis_refs[]

ScreenplayArtifactV2
  frozen ScreenplayArtifact fields
  content_hash
  adaptation_map_ref
  profile_analysis_refs[]
```

`branch_id` is the stable logical head key and the caller-supplied genesis retry
identity. Separate branch IDs may intentionally carry the same parent/profile
tuple for distinct experiments. Reusing one branch ID with a different complete
genesis tuple is an identity conflict.

Every successor serializer uses an explicit schema selector. Content hashes
include the complete semantic payload, exact parent/map refs, profile ref, and
ordered sidecar refs. Audit timestamps and storage IDs not named by the contract
remain outside content identity.

### 4.3 Typed profile sidecars

```text
WesternDramaAnalysis
  artifact_ref, profile_ref, evaluator_version
  format_findings[]
  rubric_observations[]
  evidence_locations[]

ShuangwenAnalysis
  artifact_ref, profile_ref, evaluator_version
  source_scope: chapter/index metadata
  hen, shuang, ji, pan evidence
  shuang_type: one of the six pinned Huohuo values when applicable
  findings[]

ProfileEvaluationReport
  report_id, schema_version, artifact_ref, artifact_content_hash
  profile_ref, evaluator_version, sidecar_ref, sidecar_digest
  findings[] ordered by stable finding key
  report_digest, created_at
```

Each finding contains stable rule ID/version, disposition, applicability,
severity, target path/source span, evidence refs, and message parameters.
Messages are rendered outside semantic identity.

Disposition is one of:

- `INTEGRITY_BLOCK`: shared lineage, schema, reference, approval, Canon,
  epistemic, state, continuity, duration/cast/shot-count, or replay failure;
- `PROFILE_BLOCK`: an applicable named profile requirement failed;
- `ADVISORY`: evidence-dependent craft observation; or
- `NOT_APPLICABLE`: rule was evaluated but its declared scope did not apply.

`INTEGRITY_BLOCK` is never waivable. `PROFILE_BLOCK` requires correction or an
applicable Human waiver. `ADVISORY` is preserved for review and never silently
promoted to a universal hard rule.

### 4.4 Authority decisions

```text
AdaptationMapApprovalDecision
  decision_id, branch_id, map_id/version/content_hash
  expected_predecessor_id, action, actor, approval_receipt
  profile_ref, relied_report_ids/digests, created_at

ProfileFindingWaiverDecision
  decision_id, branch_id, artifact_ref/content_hash
  exact finding IDs/rule versions, profile_ref, rationale
  expected_predecessor_id, actor, approval_receipt, created_at

ScreenplayDirectionAdmissionDecision
  decision_id, branch_id, screenplay_id/version/content_hash
  exact effective map approval, report and waiver refs
  expected_predecessor_id, actor, approval_receipt, created_at
```

The final command consumes exact proposal version N and atomically appends
version N+1 of the same screenplay ID with `approval_status=APPROVED` and
`locked_for_direction=true`, together with the admission decision selecting the
N+1 hash. Every other semantic field must equal N; a content edit requires a new
proposal before admission. No existing artifact row is updated and no
intermediate state can be used for direction. Historical decisions remain
immutable; current authority requires authoritative-chain applicability plus
the projected head.

## 5. Profile behavior

### 5.1 Shared rules

Both profiles enforce exact Canon/branch/map lineage, source/target reference
closure, allowed adaptation operations, ordered scene/shot identity, KnowledgeState
and secret constraints, state/prop/location continuity, screenplay approval and
lock, content/profile digests, candidate/master currentness, and all frozen
Golden B exit constraints.

A profile request can never weaken a shared rule. When profile advice conflicts
with Canon, knowledge, state, or continuity, the shared invariant wins and the
report records the conflict.

### 5.2 `WESTERN_GENERIC`

Hard checks are limited to named screenplay surface grammar plus shared rules:
scene-heading structure, action/dialogue separability, visible/audible action
surface, reference integrity, and delivery constraints explicitly selected by
the versioned pack.

Problem, goal/action, opposition, stakes, cause/effect, escalation, revelation,
reversal, and resolution are rubric observations with evidence locations. M6 v1
sets no universal numeric score or fixed beat timestamp and does not auto-reject
a valid slow-burn, tragic, or unresolved excerpt merely for missing a heuristic.

### 5.3 `CN_SHORT_DRAMA_SHUANGWEN`

The donor-derived surface is restricted to pure field parsing, validation, the
six `爽型` values, and deterministic prompt-block helpers from the exact pinned
Huohuo revision. It passes baseline manifest, branch-complete corpus, same-fixture
source parity, and exact-HEAD evidence before acceptance.

Huohuo-compatible `恨/爽/急/盼` and `爽型` requirements apply only under the
pinned chapter 1–8 scope. A Golden B slice is not assumed to equal a chapter.
Any R2 slice-level requirement is a separate local rule with its own version and
measured corpus; M6 v1 does not introduce one. Completion/repair orchestration,
LLM calls, donor persistence, and donor authority are excluded.

## 6. Adaptation flow

1. Resolve exact Canon branch/version and exact profile ref.
2. Create the profile-specific branch with opaque branch ID and exact genesis
   tuple; append only, no Canon copy or mutation.
3. Append map proposal versions. Each entry uses one frozen operation and exact
   source/target refs.
4. Evaluate shared rules and the branch's exact profile pack; persist immutable
   typed sidecar and report.
5. Human Showrunner approves the exact whole map version/hash. Entry statuses are
   evidence within that aggregate, not independent writers.
6. Append screenplay proposal bound to the effective map approval and exact
   profile evidence.
7. Re-evaluate screenplay proposal N. Human resolves waivable profile findings,
   then atomically appends approved/locked N+1 plus the admission decision that
   selects its exact hash for direction; all other semantic fields equal N.
8. Existing `DirectorRoutingPolicy` selects TAKE for fiction. The adapter reads
   only exact approved/locked screenplay and emits provider-neutral SceneSpec and
   ShotSpecV2.
9. Existing readiness/admission, candidate generation, approval, and
   `ApprovedMaster` semantics remain in force. There is no automatic route
   fallback and no “latest candidate wins.”

## 7. ShotSpecV2 and Take boundary

`ShotSpecV2` retains stable shot, scene, duration, dialogue, continuity and basis
fields and adds typed `shot_size`, `camera_angle`, and `camera_movement` using the
exact pinned Take vocabulary. Provider, model, endpoint, seed, retry, job, cost,
candidate, and runtime status remain forbidden.

Migration rules:

- v1 serializers and content fingerprints remain byte-for-byte unchanged;
- selector-dispatched readers accept v1/v2, and new Take output writes v2;
- a logical shot lineage never downgrades from v2 to v1;
- an upgrader maps only exact recognized legacy strings;
- unknown or compound legacy values return a typed manual-mapping requirement;
- approved v1 masters are historical and are never silently reclassified;
- Director, registry/neutrality, fingerprint, readiness, approval, Golden A and
  affected M4 tests rerun at the retrofit checkpoint.

## 8. Persistence, concurrency, and retry

Use append-only evidence/decision rows and rebuildable typed heads. PostgreSQL
correctness uses short `READ COMMITTED` transactions with the accepted M5C order:

1. validate immutable input shape and resolve exact retry before head writes;
2. prepare genesis using unique insertion rather than locking an absent row;
3. lock the named branch/map/screenplay or decision head;
4. repeat exact-retry lookup;
5. compare expected latest/effective predecessor and exact profile digest;
6. through the same transaction-bound repository, load and validate the complete
   typed decision chain, fold latest/effective state, compare every locked-head
   field, and prove the effective decision selects the exact artifact;
7. re-resolve every approval/report/waiver dependency under lock;
8. append immutable rows and advance one head atomically;
9. commit once.

Multiple heads lock by authority family and then canonical UTF-8 key. Parent
Canon is an immutable exact-version read; M6 does not hold a cross-authority
Canon/adaptation transaction. Same opaque ID plus the complete same tuple returns
the original historical receipt even after supersession. Any tuple mismatch is
an identity conflict. Currentness is a separate query.

The fold is a pure function shared by online guards and offline integrity checks.
An online guard receives the already active repository and already locked head;
it never creates a nested or second UoW. A standalone checker may open a read-only
UoW for audit/rebuild, but its result cannot authorize a later write. Local FK and
check constraints supplement this proof and never replace action/predecessor
folding.

## 9. Failure semantics

- Schema/reference/profile/digest/lineage mismatch: fail closed, write nothing.
- Stale predecessor or stale dependency: typed conflict, write nothing.
- Locked head disagrees with its authoritative chain, points effectively to a
  rejection, or selects a different artifact: typed integrity error, write
  nothing and never repair the head.
- Unknown legacy shot vocabulary: manual-mapping required, no guessed v2 shot.
- Failed evaluator execution: immutable failed-attempt evidence may exist, but no
  successful report or approval capability is created.
- Blocking finding without applicable waiver: proposal/lock denied.
- Waiver mismatch after artifact or policy change: waiver is historical only.
- Provider partial/ambiguous result: existing Director failure semantics; no
  partial normalized success and no automatic cross-route fallback.
- Failed/rejected/stale production candidate: existing promotion rejects it and
  preserves the prior ApprovedMaster.
- Transaction failure before commit: no partial authority row or head change.

## 10. Golden B evidence

The acceptance fixture pins one Canon branch/version containing at least two
characters, a location transition, a prop/state transition, and a secret encoded
through the accepted epistemic model. It creates two sibling profile branches and
produces two independent 60–120-second, 5–10-shot slices.

Each slice must show exact source-map lineage, approved map, applicable report and
waivers, approved/locked screenplay, TAKE routing, ShotSpecV2, readiness evidence,
at least one multi-candidate shot, explicit ApprovedShotMasters, final assembly,
and passing continuity checks. Mutation tests swap profile evidence, policy
digests, parent versions, approvals, secrets, shot order, candidate status, and
legacy mappings; every mutation must fail at the owning boundary without changing
the other profile's branch or current master.

Mutation evidence also includes FK-valid corrupted heads: an effective pointer
to a rejected decision, an accepting decision for the wrong selected artifact,
mismatched latest/effective generations, and supersession racing admission. Each
must fail inside the same locked transaction before consuming evidence is appended.

Golden B records document/profile/policy/donor hashes, exact implementation HEAD,
database identity for PostgreSQL concurrency evidence, commands and exit codes,
fixture IDs, artifact fingerprints, approval chain, and final outputs. It does
not claim cultural representativeness.

## 11. Checkpoints

- **M6-A — contracts and pins:** successor contracts, serializers/hashes,
  profile manifests, Take/Huohuo source pins, migrations and v1 compatibility.
- **M6-B — adaptation authority:** branch/map evidence, aggregate map approval,
  retry/OCC, scope isolation, integrity/rebuild and PostgreSQL races.
- **M6-C — screenplay and profiles:** typed sidecars, both evaluators, governed
  waivers, atomic screenplay approval/lock and dual-profile isolation.
- **M6-D — Take and ShotSpec retrofit:** Take adapter, ShotSpecV2/upgrader,
  Director/readiness integration and full affected M4/Golden A regression.
- **M6-E — Golden B:** production/candidate integration, two shared-source slices,
  adversarial mutations, full gates and independent review.

Every checkpoint freezes a clean exact HEAD, runs focused and cumulative gates,
receives independent Codex review, and adds evidence only after code review. No
checkpoint authorizes production activation.

## 12. Out of scope

- `AdaptationBrief` fields, approval, or authority until a separate decision
  closes the frozen-package gap;
- dynamic profile composition/inheritance, marketplace, hot reload, user rule
  DSL, arbitrary plugins, policy auto-migration, or in-place profile switching;
- automatic branch rebase/merge/cherry-pick or independently mutable overlays;
- universal Western beat enums/scores, automatic craft approval, or a universal
  seconds-to-chapter/`恨爽急盼` mapping;
- new adaptation operation values;
- Huohuo generation/repair orchestration or donor persistence;
- culturally native benchmark expansion, production policy UI/analytics, and
  inter-rater calibration;
- 3D/world/spatial direction, provider-specific fields in ShotSpec, production
  deployment, migration execution, provider calls, push, or worker activation.

## 13. Design self-review

- **Authority:** each mutable head has one writer; evidence and profiles cannot
  approve; Canon and Production authority remain unchanged.
- **Identity:** no `latest` dependency; retries bind full tuples; v1 bytes/hashes
  remain stable; profile and policy digests enter semantic provenance.
- **Concurrency:** absent-head genesis, lock order, stale predecessor, rollback,
  cross-profile isolation, and retry-after-supersession have explicit behavior.
- **Research fidelity:** Western craft stays advisory; Huohuo keeps exact bounded
  applicability; donor orchestration is excluded; analogy limits are not treated
  as authority.
- **Scope:** every frozen Golden B criterion has an evidence path; unresolved
  `AdaptationBrief`, native corpora and policy administration are excluded rather
  than guessed.
- **Adversarial coverage:** cross-profile contamination, overlay masking, silent
  rebase, secret leakage, waiver laundering, approval-lock races, ambiguous v1
  upgrades and rejected-candidate promotion all fail closed.

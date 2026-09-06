# R2-M2 Artifact Bridge Design

**Project:** Content & Narrative Production OS
**Milestone:** R2-M2 — Artifact Bridge
**Date:** 2026-09-06
**Status:** DESIGN APPROVED / SPEC REVIEW REQUIRED
**Architecture baseline:** R2.1–R2.7 frozen
**Depends on:** R2-M1 Contract Kernel — COMPLETE

---

## 1. Goal

Connect the R2 Contract Kernel to the existing ArcReel Artifact Manifest and version/activation subsystem without creating a parallel artifact registry or a second source of artifact truth.

R2-M2 adds:

1. an R2 metadata extension to existing ArcReel artifact entries;
2. direct dependency snapshots;
3. content-fingerprint-based selective invalidation;
4. explicit ApprovedMaster promotion over existing ArcReel versions;
5. dependency resolution interfaces for R2 contracts and ArcReel artifacts;
6. compatibility behavior for legacy non-R2 ArcReel artifacts.

The central invariants are:

```text
Runtime State ≠ Artifact Truth
Artifact Truth ≠ Canon Truth
GenerationCandidate ≠ ApprovedMaster
content_fingerprint ≠ execution_fingerprint
failed regeneration preserves prior ApprovedMaster
```

---

## 2. Selected architecture

R2-M2 extends the **existing ArcReel Artifact Manifest** through an optional R2 metadata namespace.

Selected approach:

```text
R2 domain contracts
      │
      ▼
R2ArtifactBridge
      │
      ▼
Existing ArcReel Artifact Manifest / version / activation subsystem
```

Rejected approaches:

### 2.1 Parallel PostgreSQL artifact registry

Rejected because it would create two competing artifact truths:

```text
ArcReel Artifact Manifest
vs
R2 artifact tables
```

### 2.2 Sidecar `.r2_artifacts.json`

Rejected because it would create a second project-local manifest and violate the frozen single-authority model.

### 2.3 Replacing ArcReel Artifact Manifest

Rejected because R1.8 and M0 already verified ArcReel's artifact storage, version preservation, currency behavior, restart/recovery behavior, and deterministic manifest semantics.

---

## 3. Authority boundary

ArcReel remains authoritative for:

```text
artifact key
artifact file/version storage
active host version
native artifact provenance
native artifact currency projection
manifest persistence
artifact activation
runtime task state
```

R2 provides:

```text
R2 contract reference
ContentBasis snapshot
direct dependency snapshots
R2 content fingerprint
ApprovedMaster semantic selection metadata
dependency resolution
R2-specific currency input
```

R2-M2 must not create:

```text
R2ArtifactRegistry
R2ArtifactDatabase
parallel artifact manifest
independent artifact currency state machine
independent media/version store
```

---

## 4. Target package

New R2 code belongs under:

```text
r2/production/
├── __init__.py
├── artifact_metadata.py
├── dependency_resolver.py
├── artifact_bridge.py
└── approval_service.py
```

Existing M1 code remains under:

```text
r2/contracts/
```

Tests must follow ArcReel taxonomy:

```text
tests/unit/r2/production/
tests/integration/r2/production/
```

Do not create:

```text
tests/architecture/
tests/contracts/
```

---

## 5. ArcReel seam

M2 must integrate through the existing ArcReel artifact subsystem rather than bypassing it.

The implementation plan must first inspect the pinned local ArcReel v0.29.0 source and identify the exact public/internal seams corresponding to:

```text
artifact manifest storage
artifact manifest read/update
artifact activation/version selection
artifact currency projection
artifact provenance
```

The intended logical seam is represented by the existing ArcReel modules around:

```text
lib/artifact_manifest.py
lib/artifact_currency.py
lib/artifact_provenance.py
lib/artifact_activation.py
```

Exact function/class names are implementation discoveries, not frozen architecture.

If the pinned source names differ, the implementation must adapt to the real source without changing this design.

---

## 6. R2 artifact metadata

Each R2-aware ArcReel artifact entry may carry one optional metadata envelope:

```text
r2:
  metadata_schema_version

  contract_ref
  content_basis
  direct_dependencies
  content_fingerprint

  approved_master?
```

Legacy ArcReel artifacts without this envelope remain valid and use pre-existing ArcReel behavior.

---

## 7. R2ContractRef

Define an artifact-level contract reference:

```text
R2ContractRef
  contract_type
  id
  version
  schema_version
```

Semantics:

```text
contract_type
= R2 contract type name

id
= stable logical contract identity

version
= object revision

schema_version
= contract schema revision
```

This is a manifest reference to an R2 domain contract, not a copy of the full contract.

---

## 8. ContentBasis persistence

R2 production-boundary artifacts persist the M1 ContentBasis snapshot:

```text
ContentBasis
  basis_type
  basis_version
  refs[]
```

Rules:

- R2-aware production artifact commit requires ContentBasis.
- Missing ContentBasis blocks the R2-aware commit.
- ContentBasis participates in the R2 content fingerprint through the production contract.
- R2-M2 does not resolve Canon, Claim, or Adaptation semantics itself.
- Opaque refs remain valid if a resolver can produce a stable dependency snapshot.

---

## 9. DependencySnapshot

M2 introduces a stable direct dependency snapshot:

```text
DependencySnapshot
  ref
  version
  fingerprint
```

Requirements:

```text
ref         non-empty stable namespaced reference
version     non-empty or stable version token
fingerprint non-empty deterministic dependency fingerprint
```

The snapshot records what the artifact depended on when its content fingerprint was committed.

M2 stores only **direct** dependency edges.

It does not persist a transitive graph.

---

## 10. Namespaced references

Dependency refs must be reversible and collision-resistant.

Examples:

```text
r2:ShotSpec:SH042
r2:ProductionBinding:B01
r2:VisualIdentityProfile:MAYA
artifact:FACE_MASTER:MAYA
claim:CLAIM_104
canon:Event:EVT_19
```

R2-M2 must not parse domain-specific meaning from unknown namespaces.

Unknown refs are delegated to registered resolvers.

---

## 11. DependencyResolver

Define a resolution interface conceptually equivalent to:

```python
class DependencyResolver(Protocol):
    def supports(self, ref: str) -> bool: ...
    def resolve(self, ref: str) -> DependencySnapshot: ...
```

M2 must provide resolver support for:

```text
R2 contracts
ArcReel artifacts/assets
test fixture / opaque externally supplied refs where explicitly configured
```

M2 does not implement production resolvers for:

```text
FactualAuthorityService
CanonTransactionService
NarrativePlanService
AdaptationTransactionService
```

Those arrive with their owning milestones.

---

## 12. Resolver registry

Use a small ordered resolver registry:

```text
DependencyResolverRegistry
  register(resolver)
  resolve(ref)
```

Rules:

- exactly one resolver should claim a ref during normal operation;
- zero resolvers → unresolved dependency;
- multiple resolvers → configuration error / BLOCKED;
- resolver failure must not be silently treated as CURRENT;
- no network/provider lookup is required for M2 tests.

---

## 13. Content fingerprint

M1's `compute_content_fingerprint(...)` remains the semantic fingerprint authority for ShotSpec-level production content.

M2 adds artifact bridge composition around it.

Conceptually:

```text
R2 contract
+
direct dependency snapshots
+
approved semantic source asset refs
        ↓
deterministic content fingerprint
```

The bridge stores the resulting fingerprint in:

```text
manifest_entry.r2.content_fingerprint
```

Execution metadata is excluded.

---

## 14. Execution metadata exclusion

These fields must not affect R2 artifact currency:

```text
provider
model
endpoint
provider_job_id
seed
resolution
generation settings
adapter version
execution fingerprint
```

They may exist in:

```text
ProviderRequest
ExecutionIdentity
GenerationCandidate
native ArcReel provenance/runtime records
```

but changing only those values must not stale a content artifact.

---

## 15. Selective invalidation model

R2-M2 uses **computed direct-dependency invalidation**, not eager recursive stale writes.

At commit time:

```text
resolve direct dependencies
→ persist DependencySnapshot[]
→ compute/store R2 content fingerprint
```

At currency evaluation time:

```text
load stored R2 metadata
→ resolve current versions of direct dependencies
→ recompute current R2 content fingerprint
→ compare
```

Result:

```text
same fingerprint
→ CURRENT

different fingerprint
→ STALE
```

No fan-out write such as:

```sql
UPDATE artifacts SET stale = true ...
```

is introduced by M2.

---

## 16. Selective invalidation invariant

Given:

```text
Artifact A depends on X
Artifact B does not depend on X
```

when:

```text
X version/fingerprint changes
```

required behavior is:

```text
A → STALE
B → remains CURRENT
```

Unrelated dependency changes must not affect artifact currency.

---

## 17. Currency integration

R2 does not create a new currency state machine.

ArcReel continues to expose:

```text
CURRENT
STALE
MISSING
BLOCKED
```

R2 contributes an additional semantic currency signal.

Required projection:

```text
no usable host artifact
→ existing ArcReel MISSING/BLOCKED behavior

usable R2-aware artifact
+ dependencies resolvable
+ fingerprint matches
→ CURRENT

usable R2-aware artifact
+ dependencies resolvable
+ fingerprint differs
→ STALE

usable R2-aware artifact
+ required R2 metadata malformed
→ BLOCKED

usable R2-aware artifact
+ required dependency unresolved
→ BLOCKED
```

A stale artifact remains usable according to existing ArcReel stale semantics.

---

## 18. Legacy compatibility

A legacy ArcReel artifact with no `r2` metadata must preserve existing ArcReel behavior.

M2 must not reinterpret every legacy artifact as:

```text
BLOCKED
STALE
MISSING
```

because it lacks R2 metadata.

Rule:

```text
if artifact is not declared R2-aware
→ use native ArcReel semantics unchanged
```

The bridge must distinguish:

```text
legacy non-R2 artifact
vs
malformed R2-aware artifact
```

---

## 19. R2-aware marker

Presence of a structurally valid `r2` metadata envelope identifies an R2-aware artifact.

If an `r2` envelope is present but incomplete/malformed:

```text
artifact is R2-aware
→ R2 validation applies
→ currency = BLOCKED
```

Do not silently downgrade malformed R2 metadata to legacy behavior.

---

## 20. GenerationCandidate integration

GenerationCandidate remains distinct from the manifest master selection.

Candidate lifecycle:

```text
GENERATED
FAILED
```

Candidate selection:

```text
UNREVIEWED
REJECTED
SELECTED
```

Rules:

- GENERATED does not imply ApprovedMaster.
- FAILED cannot be SELECTED.
- provider execution records do not become artifact truth merely because generation succeeded.
- a successful unapproved candidate must not replace the existing master.

---

## 21. ApprovedMaster metadata

R2-aware artifact metadata may contain:

```text
ApprovedMasterMetadata
  selected_candidate_id
  host_version_ref
  approval_record
  selected_at
  selected_by
```

This is the manifest-level materialization of the M1 `ApprovedMaster` contract over ArcReel's existing version storage.

M2 does not create a parallel media store.

---

## 22. ProductionApprovalService

M2 introduces:

```text
ProductionApprovalService
```

Logical responsibility:

```text
validate candidate
validate candidate output/version
validate selection eligibility
activate ArcReel version
record ApprovedMaster metadata
preserve previous master on failure
```

This service owns production-master promotion semantics for R2.

It does not own Canon approval or factual authority.

---

## 23. Promotion preconditions

Promotion requires all of the following:

```text
candidate exists
candidate.lifecycle_state == GENERATED
candidate output host version exists
candidate target matches artifact target
candidate content fingerprint corresponds to target content context
approval record is non-empty
selected_by is non-empty
selected_at is timezone-aware
```

A candidate may be explicitly changed to SELECTED during the same logical promotion operation if the implementation keeps candidate/master consistency.

The implementation must not derive ApprovedMaster from “latest successful generation”.

---

## 24. Atomic promotion invariant

Promotion is one logical transaction:

```text
validate candidate
→ resolve host version
→ acquire existing manifest/artifact lock
→ activate selected host version
→ write ApprovedMaster metadata
→ atomic manifest persistence
```

Required invariant:

```text
old active version
+
old ApprovedMaster

must either both remain
or both be replaced consistently
```

Forbidden intermediate durable state:

```text
active host version = candidate C
approved master = candidate B
```

---

## 25. Failure preservation

Given:

```text
B = current ApprovedMaster
```

then:

```text
generate C
→ C fails
```

must produce:

```text
B remains ApprovedMaster
B remains selected active usable version
C remains failed candidate evidence
```

Likewise:

```text
generate C successfully
→ no approval
```

must leave B unchanged.

---

## 26. ArcReel activation seam

M2 must reuse ArcReel's existing version activation/manifest update mechanism.

If ArcReel already exposes one operation capable of atomic version activation plus manifest metadata update, use it.

If not, M2 may add one **bounded Host application method** at the existing Artifact Manifest / activation seam.

That method must not create a second persistence transaction system.

---

## 27. ArtifactBridge

Define an application-facing bridge conceptually equivalent to:

```text
R2ArtifactBridge
  commit_r2_metadata(...)
  load_r2_metadata(...)
  evaluate_currency(...)
  refresh_dependency_snapshots(...)
```

Responsibilities:

- translate R2 metadata models to/from ArcReel manifest representation;
- enforce ContentBasis for R2-aware production artifacts;
- resolve direct dependencies;
- compute R2 content fingerprint;
- return semantic currency signal to ArcReel currency projection;
- distinguish legacy vs malformed R2 entries.

It must not:

```text
submit providers
run generation
own runtime tasks
mutate Canon
mutate factual claims
decide creative approval
```

---

## 28. R2 artifact metadata model

Conceptually:

```text
R2ArtifactMetadata
  metadata_schema_version

  contract_ref
  content_basis

  direct_dependencies[]
  content_fingerprint

  approved_master?
```

All fields except `approved_master` are required for an R2-aware production artifact.

---

## 29. Metadata schema version

R2 artifact metadata has its own version:

```text
metadata_schema_version
```

This is independent from:

```text
contract.schema_version
contract.version
ArcReel manifest schema version
ArcReel artifact version
```

M2 must not overload one version field to mean multiple things.

---

## 30. Manifest compatibility strategy

The R2 envelope must be optional and additive.

Preferred representation:

```json
{
  "...native ArcReel fields...": "...",
  "r2": {
    "metadata_schema_version": "1",
    "...": "..."
  }
}
```

The exact ArcReel serialization shape must follow the pinned v0.29.0 manifest implementation discovered during implementation.

Do not rewrite native manifest layout merely to make R2 look cleaner.

---

## 31. Persistence decision

R2-OPEN-001 remains intentionally limited.

M2 resolution:

```text
R2 production artifact bridge metadata
→ existing ArcReel Artifact Manifest

media/version persistence
→ existing ArcReel Host storage

candidate/runtime provenance
→ existing ArcReel Host persistence where applicable
```

M2 must not add:

```text
r2_artifacts SQL table
r2_dependencies SQL table
r2_approved_masters SQL table
```

Factual, Canon, Narrative, and Adaptation authority persistence remains owned by their later milestones.

---

## 32. PostgreSQL

M2 may use the existing PostgreSQL-backed ArcReel host during integration tests where required by the existing subsystem.

M2 does not introduce new R2 SQL schema.

A test requiring the existing ArcReel PostgreSQL baseline does not count as introducing R2 persistence.

---

## 33. Provenance

M2 must preserve existing ArcReel provenance.

R2 metadata adds semantic dependency lineage; it does not replace host provenance.

Required distinction:

```text
host provenance
= how/when/by what execution an artifact/version was produced

R2 dependency lineage
= what semantic content/dependencies the artifact represents
```

Both may coexist.

---

## 34. Error semantics

### 34.1 Missing R2 metadata

If artifact is legacy/non-R2:

```text
use native behavior
```

If artifact is declared R2-aware but required metadata is missing:

```text
BLOCKED
```

### 34.2 Unresolved required dependency

```text
BLOCKED
```

Do not treat unresolved dependency as CURRENT.

### 34.3 Resolver collision

If multiple resolvers claim the same ref:

```text
BLOCKED / configuration error
```

### 34.4 Fingerprint mismatch

```text
STALE
```

not BLOCKED.

### 34.5 Provider failure

Does not itself change content currency or ApprovedMaster.

### 34.6 Promotion failure

Previous active version and previous ApprovedMaster must survive unchanged.

---

## 35. Idempotency

R2 metadata writes should be deterministic.

Given the same:

```text
contract_ref
content_basis
dependency snapshots
content fingerprint
approved master
```

rewriting the artifact metadata should not produce semantically different manifest content.

Promotion of the already-selected candidate/version should be idempotent or return an explicit no-op result.

---

## 36. Concurrency

M2 must reuse ArcReel's existing artifact/manifest locking or atomic-write discipline.

Concurrent operations must not produce:

```text
lost ApprovedMaster
partial R2 metadata
mixed old/new dependency snapshots
active-version/master mismatch
```

M2 does not introduce a new lock manager.

---

## 37. Security / secrets

The R2 manifest metadata must never contain:

```text
API keys
tokens
provider secrets
authorization headers
raw credentials
```

Provider-specific execution payloads are outside R2 artifact metadata.

---

## 38. Dependency snapshot refresh

Refreshing dependency snapshots is allowed only as part of an explicit artifact update/recommit path.

Currency evaluation must not silently mutate stored snapshots merely because current dependencies changed.

Required behavior:

```text
stored snapshot = creation/commit-time truth
current snapshot = evaluation-time observation
```

If they differ:

```text
STALE
```

Do not overwrite the stored snapshot to make the artifact appear CURRENT.

---

## 39. Rebuild semantics

A stale artifact becomes CURRENT only after a new successful artifact commit or explicit accepted update records the new semantic dependency state.

Merely re-running currency evaluation cannot clear staleness.

---

## 40. Accepted master vs currency

ApprovedMaster and currency are orthogonal.

Examples:

```text
ApprovedMaster + CURRENT
ApprovedMaster + STALE
```

are both valid.

A stale ApprovedMaster remains the selected usable master until explicitly replaced.

This prevents:

```text
semantic dependency changes
→ master pointer disappears
```

---

## 41. Candidate vs master vs host version

The following identities remain separate:

```text
GenerationCandidate.id
ArcReel host version ref
ApprovedMaster.id
artifact logical key
```

The bridge records relationships between them; it must not collapse them into one identifier.

---

## 42. M2 unit-test requirements

At minimum unit tests must prove:

1. R2 metadata round-trips.
2. legacy artifact is not treated as malformed R2.
3. malformed R2 metadata is BLOCKED.
4. direct dependency snapshots are deterministic.
5. unrelated dependency changes do not alter artifact currency.
6. related dependency change yields STALE.
7. provider/model/seed-only change does not affect R2 content currency.
8. resolver zero-match behavior is BLOCKED.
9. resolver multi-match behavior is BLOCKED/configuration error.
10. dependency evaluation does not mutate stored snapshots.
11. ApprovedMaster metadata validates timezone-aware timestamps.
12. failed candidate cannot be promoted.

---

## 43. M2 integration-test requirements

At minimum integration tests must prove:

1. R2 metadata can be persisted in the actual ArcReel manifest and loaded back.
2. native legacy manifest behavior is unchanged.
3. failed regeneration leaves old active host version and ApprovedMaster unchanged.
4. successful unapproved candidate leaves old master unchanged.
5. explicit promotion changes both active host version and ApprovedMaster consistently.
6. injected failure during promotion leaves both old values unchanged.
7. restart/reload preserves R2 metadata and master selection.
8. concurrent manifest update path does not corrupt R2 metadata.
9. ArcReel currency projection incorporates R2 STALE/BLOCKED signal without replacing native MISSING behavior.

---

## 44. Regression gate

M2 final verification must retain:

```text
M1 contract suite PASS
M0 R2 regression PASS
frozen registry verifier PASS
host baseline verifier PASS
ArcReel focused Host regression = 349 PASS
audit_tests.py --check = 0 violations
```

If M2 intentionally adds integration tests to an existing focused file, the final ArcReel baseline regression command should still separately prove the original pinned focused suite count of 349 using the same original file set.

M2-specific tests are counted independently.

---

## 45. Source-scope guard

Expected M2 changes are limited to:

```text
r2/production/*
tests/unit/r2/production/*
tests/integration/r2/production/*
minimal bounded changes at existing ArcReel artifact manifest/currency/activation seam
docs/superpowers/specs/*
docs/superpowers/plans/*
docs/r2/evidence/*
```

Forbidden without explicit design reopening:

```text
Canon implementation
FactualAuthority implementation
NarrativePlan implementation
DirectorAdapter implementation
provider execution implementation
UI implementation
new R2 SQL migrations
parallel manifest
new media store
```

---

## 46. Implementation discovery gate

Before code changes, the implementation executor must inspect the local pinned repository.

Required discovery:

```text
Artifact Manifest model/schema
manifest storage/update API
artifact version activation API
artifact currency projection path
artifact provenance path
artifact locking/atomic write mechanism
tests protecting legacy behavior
```

The executor must document the exact seam chosen before modifying ArcReel host files.

This is an implementation discovery, not architecture reopening.

---

## 47. Exact seam acceptance rule

M2 may modify existing ArcReel runtime files only when all are true:

1. no existing extension seam can support the required behavior cleanly;
2. the change is bounded to Artifact Manifest/currency/activation;
3. existing non-R2 behavior remains unchanged;
4. focused existing tests stay green;
5. M2 integration tests prove the new seam;
6. the changed host file is listed in M2 verification evidence.

---

## 48. R2-HOST-001

The known execution identity blocker remains:

```text
R2-HOST-001
OPEN / PRODUCTION_BLOCKER
```

M2 does not fix it.

It is owned by Host hardening M7 unless an implementation dependency proves an earlier fix is necessary.

Provider execution identity remains outside artifact content currency.

---

## 49. M2 exit criteria

R2-M2 is COMPLETE only when every item below is true:

1. R2ArtifactMetadata exists and round-trips.
2. R2 metadata persists through the real ArcReel Artifact Manifest.
3. legacy ArcReel artifacts behave exactly as before.
4. R2-aware artifacts require ContentBasis.
5. direct dependency snapshots are persisted.
6. dependency change on a direct edge produces STALE.
7. unrelated dependency change preserves CURRENT.
8. provider/model/seed-only changes preserve CURRENT.
9. unresolved required dependency produces BLOCKED.
10. malformed R2 metadata produces BLOCKED.
11. currency evaluation does not mutate stored snapshots.
12. stale ApprovedMaster remains selected/usable.
13. failed generation preserves previous ApprovedMaster.
14. successful unapproved candidate preserves previous ApprovedMaster.
15. explicit promotion updates active host version and ApprovedMaster consistently.
16. failed promotion leaves both previous values intact.
17. promotion is idempotent for already-selected candidate/version.
18. no R2 SQL migration is introduced.
19. no parallel artifact registry is introduced.
20. M1 regression passes.
21. M0 regression passes.
22. frozen registry verifier passes.
23. host baseline verifier passes.
24. original ArcReel focused Host regression remains 349 PASS.
25. ArcReel audit gate reports zero violations.
26. working tree is clean.
27. verification evidence is committed.
28. branch is synchronized with `origin/r2/main`.

---

## 50. M2 evidence

On completion create:

```text
docs/r2/evidence/R2_M2_VERIFICATION_<timestamp>.json
docs/r2/evidence/R2_M2_VERIFICATION_<timestamp>.md
```

Minimum evidence:

```text
M2 unit test count
M2 integration test count
M1 contract regression
M0 R2 regression
frozen registry verification
host baseline verification
original 349 ArcReel focused regression
audit zero violations
legacy compatibility
selective invalidation
failed regeneration preservation
unapproved candidate preservation
atomic ApprovedMaster promotion
restart/reload persistence
changed ArcReel host seam files
no R2 SQL migrations
R2-HOST-001 unchanged
```

---

## 51. Next milestone boundary

Only after M2 passes may M3 begin.

R2-M3 owns Golden A general/factual content flow.

M2 must not pre-implement:

```text
ResearchPack
ClaimLedger services
FactualAuthorityService
OpenMontage integration
general-content Director behavior
```

M2 provides only the artifact bridge those later systems consume.

---

# Design conclusion

R2-M2 extends the existing ArcReel Artifact Manifest rather than building another registry.

The design locks five critical properties:

```text
one artifact truth
direct dependency snapshots
computed selective invalidation
explicit ApprovedMaster promotion
legacy ArcReel compatibility
```

The resulting boundary is:

```text
R2 contracts
      ↓
R2ArtifactBridge
      ↓
ArcReel Artifact Manifest
      ↓
native versions / activation / provenance / currency
```

No new R2 SQL artifact registry, no parallel manifest, and no provider-specific content currency are introduced.

**Status: APPROVED DESIGN / WRITTEN SPEC AWAITING USER REVIEW**

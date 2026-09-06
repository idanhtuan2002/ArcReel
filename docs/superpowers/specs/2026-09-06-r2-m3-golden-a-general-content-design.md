# R2-M3 — Golden A / General Content Design

**Project:** Content & Narrative Production OS
**Milestone:** R2-M3 — Golden A / General Content
**Date:** 2026-09-06
**Status:** DESIGN APPROVED / SPEC REVIEW REQUIRED
**Architecture baseline:** R2.1–R2.7 frozen
**Implementation baseline:** R2-M2 complete at `9cc04edd88fe8d96e0610c2d9381f09547da0239`

---

## 1. Purpose

R2-M3 is the first complete executable production vertical slice on top of the
frozen R2 architecture and completed M0–M2 implementation.

Frozen roadmap flow:

```text
ResearchPack
→ ClaimLedger
→ ScriptArtifact
→ OpenMontageDirector
→ SceneSpec / ShotSpec
→ Production Preparation
→ ArcReel
→ ApprovedMaster
→ Remotion/FFmpeg
→ final output
```

M3 must prove one factual/general-content artifact end-to-end, with at least
three production methods, visible claim lineage, and captured cost/provenance.

---

## 2. Non-goals

M3 must not pull M4 forward.

Explicitly out of scope:

- generic `DirectorAdapter` framework;
- generic `MethodRouterService`;
- generic `CapabilityRegistry`;
- generic `PromptCompilerService`;
- generic Jellyfish readiness engine;
- general VisualIdentity subsystem;
- provider qualification;
- paid cloud-provider E2E;
- Canon / Epistemic / Narrative kernel;
- adaptation branch/overlay;
- Golden B;
- closure of `R2-HOST-001`.

Only narrow Golden-A-specific adapters/services may be introduced where needed.

---

## 3. Golden A fixture

Default Golden A topic:

> **Git: Working Tree → Index → Commit hoạt động như thế nào**

Target duration: approximately 60–90 seconds.

Reasons:

- stable technical factual content;
- easy authoritative source/evidence/claim lineage;
- deterministic offline regression is practical;
- no paid cloud generation is required;
- naturally supports mixed production methods.

Regression must not depend on live Internet access. M3 stores a frozen factual
fixture with source identity/provenance, locators/fingerprints, evidence and
claims.

Minimum factual chain:

```text
SourceRecord[]
→ EvidenceRecord[]
→ ResearchPack
→ ClaimLedger
```

The fixture is deterministic test input, not a replacement for a future live
research subsystem.

---

## 4. Authority model

### 4.1 Factual authority

Golden A factual authority uses:

- `SourceRecord`;
- `EvidenceRecord`;
- `ResearchPack`;
- `Claim`;
- `ClaimLedger`.

### 4.2 Production boundary

`ScriptArtifact` enters production with factual `ContentBasis` containing
ResearchPack/Claim/Evidence/Source references as required.

Script sections may carry `claim_refs[]`.

ShotSpec never becomes a store for copied factual truth.

### 4.3 Production authority

ArcReel-derived Host remains authoritative for:

- Artifact Manifest;
- artifact currency;
- version history;
- formal media files;
- candidates;
- ApprovedMaster;
- runtime/recovery;
- existing cost/usage;
- export.

No parallel R2 artifact registry and no second media queue are permitted.

---

## 5. End-to-end data flow

```text
Frozen factual fixture
      ↓
SourceRecord[]
      ↓
EvidenceRecord[]
      ↓
ResearchPack
      ↓
ClaimLedger
      ↓
ScriptArtifact
  ContentBasis = FACTUAL
  section claim_refs
      ↓
GoldenAOpenMontageAdapter
      ↓
SceneSpec[]
      ↓
ShotSpec[]
      ↓
GoldenAProductionPreparation
      ↓
ProductionBinding[]
ProductionReadiness[]
GoldenAMethodAssignment[]
      ↓
local producer(s)
      ↓
GenerationCandidate / produced candidate
      ↓
ProductionApprovalService
      ↓
ApprovedMaster
      ↓
Golden A composition plan
      ↓
Remotion / FFmpeg
      ↓
final MP4
```

---

## 6. OpenMontage director seam

Frozen R2 policy selects OpenMontage for general content.

M3 introduces only this narrow seam:

```text
ScriptArtifact
       ↓
GoldenAOpenMontageAdapter
       ↓
SceneSpec[]
ShotSpec[]
```

Requirements:

1. input is a usable factual `ScriptArtifact`;
2. output is validated provider-neutral `SceneSpec`/`ShotSpec`;
3. no provider/model/endpoint/API payload/provider-job identity enters stable
   scene/shot contracts;
4. source-unit and claim lineage are preserved;
5. donor objects never become R2 authority;
6. if direct OpenMontage execution is not locally callable, seam discovery may
   justify an adapter-compatible deterministic Golden A fixture while keeping
   the same adapter contract.

M3 does not generalize this into M4's full DirectorAdapter framework.

---

## 7. Production preparation

M3 uses a Golden-A-specific preparation profile.

For each shot it computes:

- required production roles;
- resolved `ProductionBinding` entries;
- `ProductionReadiness`;
- allowed production methods;
- one selected Golden A method assignment.

A shot with an unresolved required binding is `BLOCKED` and must not enter a
producer.

ProductionBinding remains the semantic→production bridge.

---

## 8. Production methods

Golden A must use at least three methods.

Required baseline:

```text
REUSE
DETERMINISTIC
COMPOSITE
```

Optional fourth method:

```text
SCREEN_CAPTURE
```

only if Task 0 seam discovery proves a stable reproducible local path.

`GENERATED_VIDEO` and paid cloud generation are not M3 requirements.

M3 preserves “method before provider” conceptually without implementing the
generic M4 Method Router.

---

## 9. Artifact truth and lineage

M3 uses the real M2 Artifact Bridge:

```text
ContentBasis
→ direct DependencySnapshot[]
→ content_fingerprint
→ ArcReel Artifact Manifest entry.r2
→ candidate
→ explicit approval
→ ApprovedMaster
```

The final MP4 must trace back to factual authority:

```text
final.mp4
→ composition/master artifact
→ selected shot masters
→ ShotSpec
→ SceneSpec
→ ScriptArtifact section
→ Claim
→ EvidenceRecord
→ SourceRecord
```

Lineage must be machine-readable in M3 evidence.

---

## 10. Selective invalidation

M3 persists direct dependency snapshots only.

Illustrative graph:

```text
CLAIM-001 → SEC-01 → SC01 → SH01
CLAIM-002 → SEC-02 → SC02 → SH02
                         └→ SH03
CLAIM-003 → SEC-03 → SC03 → SH04

selected shot masters → FINAL-COMPOSITE
```

If only `CLAIM-002` changes version/fingerprint:

```text
SH02              STALE
SH03              STALE
SH01              CURRENT
SH04              CURRENT
FINAL-COMPOSITE   STALE
```

Currency evaluation must not mutate stored dependency snapshots.

No transitive dependency graph is persisted.

---

## 11. Candidate / ApprovedMaster semantics

Golden A must execute this scenario:

```text
candidate B → successful → explicitly approved
candidate C → later production failure
```

Expected:

```text
ApprovedMaster = B
current usable media = B
C remains failed candidate/history
```

Then:

```text
candidate D → successful but unapproved
```

Expected:

```text
ApprovedMaster remains B
```

Only explicit promotion of D may replace B.

This must use the real M2 promotion/version-restore integration.

---

## 12. Composition and final output

M3 must produce a real MP4.

Preferred seam:

```text
approved shot/media masters
→ GoldenA composition/timeline projection
→ existing Remotion/FFmpeg capability
→ final MP4
```

Existing ArcReel/FFmpeg mechanics are reused unless executable blocker evidence
requires a bounded change.

The final media must be inspectable with `ffprobe`.

The binary MP4 does not need to be committed to Git. Evidence records path,
SHA-256, duration and relevant codec/container metadata.

---

## 13. Cost and provenance

Golden A evidence must capture at least:

```text
method
tool / adapter
tool version
content fingerprint
execution fingerprint where applicable
input refs
output ref
output SHA-256
wall time
external_provider_cost
candidate/master refs
```

Baseline:

```text
external_provider_cost = 0
```

Execution identity/cost does not participate in semantic content currency.

---

## 14. Evidence layout

Expected durable evidence shape:

```text
docs/r2/evidence/m3/golden_a/
    factual_snapshot.json
    claim_lineage.json
    script.json
    scenes.json
    shots.json
    production_plan.json
    artifact_lineage.json
    cost_provenance.json
    ffprobe.json
    verification.json
    verification.md
```

The actual MP4 may remain outside Git.

---

## 15. Failure handling

M3 fails closed.

Examples:

- missing required factual basis → production boundary rejected;
- malformed R2 manifest metadata → `BLOCKED`;
- unresolved required binding → `BLOCKED`;
- producer failure → no master replacement;
- composition failure → prior approved output preserved when one exists;
- Manifest CAS conflict → operation fails without split-brain master;
- execution-only change → semantic content does not become stale.

A verified frozen-architecture contradiction stops the milestone for explicit
architecture-change review.

---

## 16. Testing strategy

### Unit

Cover:

- factual fixture/claim validation;
- ScriptArtifact claim refs;
- OpenMontage adapter output validation;
- Golden A readiness/preparation;
- method assignment constraints;
- lineage projection;
- cost/provenance output;
- architecture boundaries.

### Integration

Cover:

- factual basis → script → scene/shot;
- scene/shot → real Artifact Manifest R2 metadata;
- candidate → explicit ApprovedMaster;
- failed regeneration preserves master;
- successful unapproved candidate preserves master;
- direct-claim selective invalidation;
- final-composite invalidation;
- restart/reload;
- deterministic/local production;
- final Remotion/FFmpeg composition.

### Golden runner

One single-command runner must:

1. create an isolated project workspace;
2. load frozen factual fixture;
3. materialize ScriptArtifact;
4. derive SceneSpec/ShotSpec;
5. prepare production;
6. use >= 3 production methods;
7. produce local media;
8. explicitly approve masters;
9. compose a real MP4;
10. validate lineage/currency/failure semantics;
11. emit evidence;
12. avoid repository mutation except during explicit evidence-recording tasks.

---

## 17. Architecture guardrails

M3 mechanically enforces:

1. no parallel R2 artifact registry;
2. no second media queue;
3. no M3 SQL table unless executable blocker evidence is explicitly approved;
4. SceneSpec/ShotSpec remain provider-neutral;
5. ProductionBinding remains semantic→production bridge;
6. direct dependency snapshots only;
7. execution fields excluded from content currency;
8. Golden-A-specific services do not silently become generic M4 authorities;
9. Canon/Narrative modules are not introduced;
10. `R2-HOST-001` remains machine-readable and OPEN.

---

## 18. Host maturity effect

Successful M3 provides evidence for:

```text
DEV → INTEGRATION_READY
```

because R2 contracts/adapters integrate with the Host and Golden A can run.

M3 does not claim:

```text
RECOVERY_VERIFIED
PRODUCTION_CANDIDATE
PRODUCTION_APPROVED
```

`R2-HOST-001` remains a production blocker unless separately closed by its
scheduled hardening process.

---

## 19. M3 exit gates

M3 is technically complete only when all gates pass:

```text
Golden A factual pipeline                         PASS
real final MP4                                    PASS
ResearchPack → Claim lineage                      PASS
Script → Scene → Shot lineage                     PASS
>= 3 production methods                           PASS
ProductionBinding/readiness                       PASS
real ArcReel Artifact Manifest bridge             PASS
explicit ApprovedMaster                           PASS
failed regeneration preserves master              PASS
successful unapproved candidate preserves master  PASS
single-claim selective invalidation               PASS
final composite invalidation                      PASS
cost/provenance                                   PASS
restart/reload                                    PASS
M2 regression                                     PASS
M1 contract regression                            PASS
frozen ArcReel Host regression                    PASS
audit                                             0 violations
no parallel registry/queue                        PASS
no accidental generic M4 subsystem                PASS
H1 / R2-HOST-001                                  OPEN / tracked
working tree                                      CLEAN
```

Final verification records exact test counts rather than silently accepting
test-count drift.

---

## 20. Implementation sequencing constraints

Task 0 must perform exact seam discovery before production code.

It must identify:

- factual/script-like artifact seams already present;
- OpenMontage donor availability/callable surface;
- deterministic visual generation seam;
- Remotion/FFmpeg composition seam;
- suitable ArcReel artifact/version keys;
- cost/provenance extraction seam;
- final export seam;
- restart/reload verification seam.

Implementation then proceeds vertically, not by separately building every future
subsystem.

No production implementation begins until this written spec is reviewed and
approved.

---

## 21. Frozen decisions preserved

This design preserves:

- R2-DEC-010 factual truth and fiction truth remain distinct;
- R2-DEC-011 ArcReel-derived Host is primary runtime;
- R2-DEC-013 no parallel artifact registry;
- R2-DEC-014 no second media queue;
- R2-DEC-015 OpenMontageDirector for general content;
- R2-DEC-016 readiness distinct from content/runtime state;
- R2-DEC-019 ProductionBinding is semantic→production bridge;
- R2-DEC-020 method before provider;
- R2-DEC-022 PromptPlan separate from ProviderRequest;
- R2-DEC-023 SceneSpec/ShotSpec provider-neutral;
- R2-DEC-024 content fingerprint ≠ execution fingerprint;
- R2-DEC-025 ApprovedMaster requires explicit selection;
- R2-DEC-028 OpenMontage/Remotion primary deterministic composition path;
- R2-DEC-030 / H1 remains tracked.

No R2.1–R2.7 architecture decision is reopened.

---

## 22. Approval state

The Human Showrunner approved the in-chat R2-M3 design on 2026-09-06.

This written spec still requires explicit review/approval before implementation
planning.

**Next allowed step after written-spec approval:** create the R2-M3
implementation plan. Production code remains blocked until that plan exists.

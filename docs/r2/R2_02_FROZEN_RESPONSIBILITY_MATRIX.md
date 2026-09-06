# R2.2 — Frozen Responsibility Matrix

**Project:** Content & Narrative Production OS  
**Phase:** R2 — Architecture Freeze  
**Date:** 2026-09-06  
**Status:** **FROZEN v1**  
**Approval:** Human Showrunner approved R2.2 on 2026-09-06  
**Depends on:** `R2_01_FROZEN_ARCHITECTURE.md`

---

# 1. Purpose

R2.2 freezes responsibility and authority boundaries.

The central rule is:

> **Every authoritative state class has exactly one commit authority.**

Other systems may:
- read;
- propose;
- validate;
- recommend;
- prepare;
- execute;

but cannot silently commit into an authority they do not own.

This document is authoritative for:
- ownership;
- mutation rights;
- proposal/approval/commit boundaries;
- donor exclusions;
- adapter responsibilities;
- cross-plane write restrictions.

---

# 2. Permission vocabulary

Every subsystem capability is described using four write/read levels:

```text
READ
→ PROPOSE
→ APPROVE
→ COMMIT
```

## READ

May consume authoritative state or a projection of it.

READ does not imply ownership.

## PROPOSE

May create:
- candidate;
- draft;
- change set;
- recommendation;
- requested transition.

A proposal cannot become authoritative without a valid approval/commit path.

## APPROVE

May approve/reject a candidate transition according to policy.

Approval alone does not necessarily mutate storage.

## COMMIT

The only permission that mutates authoritative state.

Each authoritative state class must have exactly one formal commit service/authority.

---

# 3. Authoritative commit authorities

| Authoritative State | Sole Commit Authority |
|---|---|
| Factual claim truth | `FactualAuthorityService` |
| Fiction Canon | `CanonTransactionService` |
| Epistemic state | `CanonTransactionService` via epistemic operations |
| Narrative Plan | `NarrativePlanService` |
| Creative Policy | `CreativePolicyService` |
| Adaptation branch | `AdaptationTransactionService` |
| Production Artifact truth | ArcReel Artifact/Application Services |
| Runtime Task truth | ArcReel task/queue services |
| Approved production master | R2 Approval service over ArcReel version storage |
| Distribution record | Distribution service |
| Learning recommendations | Learning Engine |
| Governance policy | Governance/Showrunner approval service |

No donor-local file/database may bypass this table.

---

# 4. Frozen responsibility matrix

| Domain | Authority Owner | Implementation / Donor | Allowed Direct Writes | Explicitly Forbidden |
|---|---|---|---|---|
| Research source capture | R2 Factual Authority | OpenMontage-derived | Source/Evidence ingestion | Canon writes |
| Research synthesis | R2 Factual Authority | OpenMontage-derived | ResearchPack proposal | production runtime mutation |
| Claims | R2 Factual Authority | OpenMontage + R2 | Claim proposal/review | silent approved-claim rewrite |
| Fiction facts/events | R2 Canon Kernel | R2 custom core | CanonDelta commit only | donor direct mutation |
| Character knowledge/belief | R2 Epistemic Engine | R2 custom core | CanonDelta epistemic ops | Writer/StoryBox mutation |
| Narrative hierarchy | NarrativePlanStore | Novel Studio/Shenbi strategies | Plan transactions | treating future plan as fact |
| Creative/style policy | CreativePolicyService | Human + Novel/Shenbi patterns | approved policy transactions | analytics direct mutation |
| Simulation | Candidate plane | StoryBox | SimulationScenario/Event | Canon commit |
| Draft prose | Candidate plane | writers/models | DraftCandidate | Canon commit |
| Narrative state extraction | Proposal plane | Huohuo/Novel/Shenbi-derived | NarrativeChangeSet | truth mutation |
| Narrative QA | Review plane | Shenbi/Huohuo/R2 validators | ReviewReport | Canon commit |
| CanonDelta construction | R2 Core | CanonDeltaCompiler | CanonDelta proposal | direct commit |
| Canon transaction | R2 Canon Kernel | CanonTransactionService | CanonVersion N+1 | bypass validation |
| Adaptation planning | R2 Adaptation Authority | Huohuo-derived | AdaptationMap proposal | source Canon mutation |
| Adaptation branch | R2 Adaptation Authority | R2 Core | branch overlay commit | parent overwrite |
| General-content Director | R2 Director abstraction | OpenMontageDirector | SceneSpec/ShotSpec proposal | provider runtime |
| Fiction Director | R2 Director abstraction | TakeDirector | SceneSpec/ShotSpec proposal | task/runtime ownership |
| Shot preparation | R2 Production Preparation | Jellyfish-derived | readiness/binding proposal | generation execution |
| Visual identity | R2 Production Binding | ai-short-film-derived | approved identity refs/variants | Canon-character mutation |
| Production method | R2 Method Router | R2 Core | MethodDecision | provider chooses business method |
| Prompt compilation | R2 Generation Preparation | Butterfly-derived | PromptPlan | ShotSpec ownership |
| Capability normalization | R2 CapabilityRegistry | ArcReel/DC-Media/OpenMontage adapters | normalized capability view | multiple competing business catalogs |
| Provider execution | ArcReel Host | ArcReel | tasks/provider jobs/results | creative truth mutation |
| Runtime recovery | ArcReel Host | ArcReel | task/checkpoint recovery | artifact/canon mutation |
| Artifact truth | ArcReel Host | ArcReel + R2 content-basis extension | manifest/version/currency/provenance | Canon mutation |
| Generation candidate | Production Authority | ArcReel + R2 candidate semantic | candidate persistence | auto-master promotion |
| Approved production master | Production Authority | R2 approval over ArcReel | ApprovedMaster selection | overwrite by failed candidate |
| Creative Canvas | Exploration plane | DramaClaw | CanvasCandidate | direct production commit |
| Composition | Production layer | Remotion/FFmpeg/ArcReel | EditTimeline/render outputs | upstream truth rewrite |
| Distribution | Distribution layer | adapters | DistributionRecord | Canon/policy mutation |
| Analytics | Learning plane | R2 Learning Engine | PerformanceReport/recommendation | authority mutation |
| Learning promotion | Governance plane | Human/Policy | approved policy/plan proposal | silent auto-optimization |

---

# 5. Agent permission examples

## 5.1 Candidate Writer

```text
READ:
- NarrativeContextPack
- SceneContract
- CreativePolicy projection

PROPOSE:
- DraftCandidate
- optional self-critique metadata

APPROVE:
- NO

COMMIT:
- NO
```

A Writer never receives a direct Canon write API.

---

## 5.2 Narrative State Extractor

```text
READ:
- accepted/reviewed narrative revision
- base CanonVersion
- evidence/source spans

PROPOSE:
- NarrativeChangeSet

APPROVE:
- NO

COMMIT:
- NO
```

Shenbi `state-settling`, Novel Studio memory extraction and Huohuo Change Record are normalized into this role.

---

## 5.3 CanonDeltaCompiler

```text
READ:
- NarrativeRevision
- NarrativeChangeSet
- CanonVersion
- author decisions

PROPOSE:
- CanonDelta
- conflict metadata

APPROVE:
- NO

COMMIT:
- NO
```

---

## 5.4 CanonTransactionService

```text
READ:
- CanonVersion
- CanonDelta
- policy
- validation reports

PROPOSE:
- conflict/validation outcome

APPROVE:
- consumes approval result

COMMIT:
- YES
```

Only this service may create the next authoritative CanonVersion.

---

## 5.5 StoryBox Simulation

```text
READ:
- epistemically filtered SimulationScenario

PROPOSE:
- SimulationEvent[]

APPROVE:
- NO

COMMIT:
- NO
```

Simulation cannot see hidden global truth beyond its allowed projection.

---

## 5.6 TakeDirector

```text
READ:
- ScreenplayArtifact
- ContentBasis
- CreativePolicy
- director constraints

PROPOSE:
- BeatPlan
- ShotDraft
- SceneSpec
- ShotSpec

APPROVE:
- NO

COMMIT runtime:
- NO

COMMIT Canon:
- NO
```

Take jobs/providers are excluded from the authoritative runtime path.

---

## 5.7 OpenMontageDirector

```text
READ:
- ScriptArtifact
- ContentBasis
- content profile
- production constraints

PROPOSE:
- SceneSpec
- ShotSpec or deterministic production units

APPROVE:
- NO

COMMIT runtime:
- NO
```

---

## 5.8 ShotPreparationService

```text
READ:
- ShotSpec
- production asset inventory
- continuity requirements
- VisualIdentityProfile

PROPOSE:
- ProductionBinding[]
- ProductionReadiness

APPROVE:
- readiness gate result

COMMIT provider task:
- NO
```

---

## 5.9 Method Router

```text
READ:
- ShotSpec
- ProductionBindings
- budget
- quality tier
- CapabilityRegistry

PROPOSE:
- MethodDecision

APPROVE:
- policy may auto-approve low-risk decisions

COMMIT provider task:
- NO
```

Provider selection happens only after method selection.

---

## 5.10 PromptCompiler

```text
READ:
- ShotSpec
- ProductionBindings
- VisualIdentity
- CreativePolicy
- continuity anchors

PROPOSE:
- PromptPlan

APPROVE:
- NO

COMMIT provider execution:
- NO
```

---

## 5.11 ArcReel Provider Worker

```text
READ:
- production request
- provider request
- task/runtime state

PROPOSE:
- GenerationCandidate/result
- cost/usage
- task transitions

APPROVE creative output:
- NO

COMMIT runtime:
- YES

COMMIT production artifact state:
- through ArcReel application/artifact services

COMMIT Canon:
- NEVER
```

---

## 5.12 Learning Engine

```text
READ:
- PerformanceReport
- cost
- QA
- method/provider outcomes
- historical decisions

PROPOSE:
- routing recommendation
- content hypothesis
- experiment
- policy suggestion

APPROVE:
- NO by default

COMMIT Canon/Plan/Policy:
- NO
```

---

# 6. Cross-authority mutation rules

## Rule A — Factual → Production

Allowed:

```text
Claim/Evidence
→ ScriptArtifact
→ ContentBasis
→ SceneSpec/ShotSpec
```

Forbidden:

```text
Claim
→ Canon Fact
```

unless an explicit separate import/adaptation workflow exists.

---

## Rule B — Narrative → Production

Allowed:

```text
Canon/NarrativePlan
→ ScreenplayArtifact
→ SceneSpec/ShotSpec
```

Forbidden:

```text
Generated Shot
→ Canon Event
```

without a Canon proposal/transaction.

---

## Rule C — Production → Narrative

Production results may inform:
- continuity review;
- adaptation proposal;
- authorial revision.

They cannot directly mutate Canon.

Example:

```text
Actor/visual constraint discovered
→ AdaptationChangeProposal
→ human review
→ AdaptationTransaction
```

not:

```text
rendered video
→ rewrite Canon automatically
```

---

## Rule D — Analytics → Authority

Allowed:

```text
PerformanceReport
→ Recommendation
→ Human/Policy review
→ explicit transaction
```

Forbidden:

```text
CTR down
→ silently rewrite CreativePolicy
```

---

# 7. Donor state/runtime systems explicitly excluded

The following donor-local systems may be used as reference implementations or adapter-internal working state, but are not authoritative R2 stores.

## Novel Studio
Excluded as authority:
- local SQLite Canon/memory store;
- acceptance memory DB as final Canon truth.

Retained:
- workflow UX;
- context patterns;
- hierarchy;
- hard-rule patterns.

## Shenbi
Excluded as authority:
- truth files as source-of-truth;
- pre-audit state-settling commit.

Retained:
- skills;
- audits;
- snapshots;
- extraction/import patterns.

## Huohuo
Excluded as authority:
- four-layer memory as Canon;
- runtime/batch authority.

Retained:
- causal Change Record;
- adaptation logic.

## StoryBox
Excluded as authority:
- simulation world as Canon.

Retained:
- simulation/event generation.

## take
Excluded:
- provider jobs;
- generation runtime;
- job log as R2 runtime truth.

Retained:
- domain core;
- shot language;
- validation;
- Director skill.

## Jellyfish
Excluded:
- Celery/runtime task authority;
- provider runtime.

Retained:
- readiness semantics;
- shot-preparation checks.

## ai-short-film
Excluded:
- local project/queue authority.

Retained:
- identity/look-lock/continuity patterns.

## Butterfly
Excluded:
- storyboard/video/voice/editor task runtime.

Retained:
- PromptCompiler semantics.

## DramaClaw
Excluded:
- project DB as production authority;
- in-process task engine;
- canvas state as truth;
- Story Graph as Canon.

Retained:
- canvas;
- promotion semantics;
- spatial workbench;
- optional transport gateway.

## OpenMontage
Excluded:
- checkpoints as authoritative workflow state;
- any duplicate production queue.

Retained:
- research/content engine;
- Director;
- tools;
- Remotion;
- capability metadata.

---

# 8. Single-authority commit map

```text
Factual Truth
    COMMIT → FactualAuthorityService

Narrative Plan
    COMMIT → NarrativePlanService

Creative Policy
    COMMIT → CreativePolicyService

Canon/Epistemic
    COMMIT → CanonTransactionService

Adaptation Branch
    COMMIT → AdaptationTransactionService

Production Artifact State
    COMMIT → ArcReel Artifact/Application Services

Runtime Task State
    COMMIT → ArcReel Task/Queue Services

Approved Master
    COMMIT → R2 ProductionApprovalService
              using ArcReel version storage

Distribution Record
    COMMIT → DistributionService

Learning Recommendation
    COMMIT → LearningEngine
             (recommendation plane only)
```

---

# 9. Approval semantics

Approval is domain-specific.

Do not use one overloaded `status` field for all planes.

Examples:

## Creative artifact approval

```text
DRAFT
PROPOSED
REVIEW_REQUIRED
APPROVED
REJECTED
```

## Artifact currency

```text
CURRENT
STALE
MISSING
BLOCKED
```

## Runtime task

```text
QUEUED
RUNNING
CANCELLING
SUCCEEDED
FAILED
CANCELLED
```

These status families are orthogonal.

A task can:
- `FAILED`

while the previous artifact remains:
- `CURRENT`
- `APPROVED`

---

# 10. Escalation and override

Human Showrunner may override:
- creative approval;
- adaptation decisions;
- routing preference;
- quality ladder;
- policy.

But Human override must still be represented as an explicit transaction/audit record.

Human authority does not mean bypassing provenance.

---

# 11. R2.2 invariants

1. Exactly one commit authority per authoritative state class.
2. Donor working state cannot silently become R2 truth.
3. Agent/model outputs are proposals until committed through the correct authority.
4. Production runtime cannot mutate creative/narrative authority.
5. Analytics cannot silently mutate authority.
6. Approval and runtime success are not equivalent.
7. Failed runtime tasks cannot erase usable approved artifacts.
8. Cross-plane promotion is explicit, attributable and auditable.
9. Canvas/simulation/branch experiments are non-authoritative until promoted.
10. Every adapter must declare its READ/PROPOSE/APPROVE/COMMIT rights.

---

# 12. Adapter registration requirement

Every integration adapter implemented later must declare:

```text
adapter_name
source_system
reads[]
proposes[]
approves[]
commits[]
authoritative_store_access[]
forbidden_operations[]
```

CI/architecture tests should reject adapters that claim forbidden authority.

---

# 13. R2.2 exit criteria

R2.2 is complete when:
- Human Showrunner approves the responsibility matrix;
- one commit authority exists for every authoritative state family;
- no donor has conflicting commit rights;
- adapter permissions can be tested mechanically;
- R2.3 schemas can be mapped to an owner unambiguously.

**Status: COMPLETE / FROZEN v1**

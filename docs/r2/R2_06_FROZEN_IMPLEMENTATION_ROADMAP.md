# R2.6 — Frozen Implementation Roadmap

**Project:** Content & Narrative Production OS  
**Phase:** R2 — Architecture Freeze  
**Date:** 2026-09-06  
**Status:** **FROZEN v1**  
**Approval:** Human Showrunner approved R2.6 on 2026-09-06  
**Depends on:** R2.1–R2.5

---

# 1. Delivery strategy

Implementation proceeds by executable vertical milestones, not by wholesale donor merge.

Each milestone must:
- leave runnable software;
- preserve the R2 authority model;
- add regression tests;
- define explicit exit gates;
- avoid introducing later-phase components early.

---

# 2. Milestones

## R2-M0 — Host Fork Foundation

Goal:
- fork/pin ArcReel v0.29.0;
- PostgreSQL-first R2 development baseline;
- upstream synchronization strategy;
- import frozen R2 architecture evidence;
- architecture/decision gates;
- baseline regression;
- register H1/R2-HOST-001 as a known production blocker.

Explicitly out of scope:
- Canon;
- OpenMontage integration;
- take integration;
- UI redesign;
- Method Router;
- CapabilityRegistry implementation;
- Artifact Manifest extension implementation.

Exit:
- pinned baseline is reproducible;
- PostgreSQL migration passes;
- upstream focused tests pass;
- R2 architecture registry tests pass;
- working tree clean;
- H1 known blocker is machine-readable and cannot be silently forgotten.

---

## R2-M1 — R2 Contract Kernel

Goal:
- implement frozen R2 provider-neutral contracts.

Primary output:
- ContentBasis;
- SceneSpec;
- ShotSpec;
- ProductionBinding;
- VisualIdentityProfile;
- ProductionReadiness;
- MethodDecision;
- PromptPlan;
- state enums;
- fingerprints;
- contract registry enforcement.

Exit:
- schema validation passes;
- forbidden provider fields rejected;
- fingerprint separation tests pass.

---

## R2-M2 — Artifact Bridge

Goal:
- integrate R2 lineage into ArcReel Artifact Manifest without creating a second artifact authority.

Primary output:
- ContentBasis manifest metadata;
- direct dependency edges;
- content fingerprint integration;
- ApprovedMaster semantic over ArcReel versions;
- selective invalidation.

Exit:
- changed direct dependency stales only affected artifact;
- execution-only changes do not stale content;
- failed regeneration preserves selected master.

---

## R2-M3 — Golden A / General Content

Goal:
- first complete production workflow.

Flow:

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

Exit:
- one real factual/general-content artifact end-to-end;
- at least three production methods;
- claim lineage visible;
- cost/provenance captured.

---

## R2-M4 — Production Intelligence

Goal:
- complete the reusable production-preparation spine.

Primary output:
- DirectorAdapter;
- Jellyfish-derived readiness;
- VisualIdentity;
- Method Router;
- CapabilityRegistry;
- PromptCompiler.

Exit:
- 12-shot mixed-method fixture passes;
- no unresolved required binding reaches expensive generation;
- method decision occurs before provider selection.

---

## R2-M5 — Canon & Narrative Kernel

Goal:
- implement R2 custom narrative authority.

Primary output:
- CanonBranch/Version;
- Entity/Fact/Event;
- KnowledgeState;
- Epistemic Engine;
- NarrativePlan;
- SceneContract;
- NarrativeContextCompiler;
- NarrativeChangeSet;
- CanonDeltaCompiler;
- CanonTransactionService.

Exit fixture:
- 30 scenes;
- 8 characters;
- 3 locations;
- 2 hidden identities;
- 2 false beliefs;
- injury/object/time-jump/relationship/thread constraints.

Hard exit:
- Canon contradiction = 0;
- epistemic leakage = 0;
- timeline violation = 0;
- rejected candidate contamination = 0;
- failed transaction corruption = 0.

---

## R2-M6 — Adaptation + Golden B

Goal:
- source narrative/IP to cinematic production.

Flow:

```text
Canon
→ AdaptationBranch
→ AdaptationMap
→ ScreenplayArtifact
→ TakeDirector
→ ShotSpec
→ readiness
→ production
→ ApprovedShotMasters
→ final drama
```

Exit:
- 60–120 second drama;
- 2+ characters;
- 5–10 shots;
- location change;
- prop/state change;
- secret/knowledge constraint;
- at least one shot with multiple candidates;
- continuity checks pass.

---

## R2-M7 — Host Production Hardening

Goal:
- R2 fork re-earns production runtime maturity after extensions.

Primary scope:
- H1–H8;
- execution identity;
- idempotency;
- atomic promotion;
- restart recovery;
- backup/restore;
- observability;
- upstream compatibility gates.

Exit:

```text
RECOVERY_VERIFIED
→ PRODUCTION_CANDIDATE
```

---

## R2-M8 — Advanced Canvas / Learning / Multi-format

Goal:
- add non-core creative leverage after both Golden workflows are stable.

Scope:
- DramaClaw canvas;
- explicit PROMOTE;
- advanced spatial/Director World experiments;
- analytics;
- Learning Engine recommendations;
- additional output formats.

Exit:
- no authority violation;
- measurable workflow/quality utility;
- recommendations remain non-authoritative until promoted.

---

# 3. Frozen dependency order

```text
M0
↓
M1
↓
M2
↓
M3
↓
M4
↓
M5
↓
M6
↓
M7
↓
M8
```

Skipping forward requires explicit milestone-gate approval.

---

# 4. Target namespace

Long-term target:

```text
content-production-os/
├── host/
├── r2/
│   ├── contracts/
│   ├── authority/
│   ├── production/
│   ├── adapters/
│   └── governance/
├── tests/
│   ├── architecture/
│   ├── contracts/
│   ├── golden/
│   └── fault/
└── docs/
```

This is a target namespace, not a mandate to scaffold every directory in M0.

Only create directories/files required by the current milestone.

---

# 5. Task governance

Every implementation task must specify:

```text
Goal
Inputs
Outputs
Dependencies
Acceptance Criteria
Tests
Out of Scope
```

Engineering workflow:

```text
codebase-memory / symbol-impact analysis
→ targeted reads
→ failing test
→ minimal implementation
→ focused tests
→ regression tests
→ diff review
```

For small tasks, do not spawn subagents unnecessarily.

---

# 6. Roadmap invariants

1. Do not rebuild proven ArcReel queue/artifact/runtime machinery without blocker evidence.
2. Do not introduce Canon before the production spine is validated by Golden A.
3. Do not merge donor repositories wholesale.
4. Do not build provider-specific fields into stable R2 contracts.
5. Do not allow later milestone features to become hidden M0/M1 scope.
6. Each milestone must remain independently reviewable and revertible.

**Status: COMPLETE / FROZEN v1**

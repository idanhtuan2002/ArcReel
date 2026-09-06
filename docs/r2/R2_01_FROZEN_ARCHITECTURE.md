# R2.1 — Frozen Architecture

**Project:** Content & Narrative Production OS  
**Phase:** R2 — Architecture Freeze  
**Date:** 2026-09-06  
**Status:** **FROZEN v1**  
**Approval:** Human Showrunner approved R2.1 on 2026-09-06  
**Host baseline:** ArcReel v0.29.0 / `6ddedc775e7fe5f398b10081ab741985f7dceda7`

---

# 1. Purpose

R2.1 freezes the top-level architecture after R1.1–R1.8 repository and target-Ubuntu verification.

This document is authoritative for:
- architectural layers;
- authority boundaries;
- subsystem ownership;
- cross-stack convergence points;
- core invariants;
- donor placement;
- host role;
- what may and may not mutate authoritative state.

Later R2 documents may refine schemas, interfaces and implementation sequencing, but must not silently change these boundaries.

Any change to a frozen R2.1 decision requires:
1. explicit architecture-change proposal;
2. evidence of a real blocker or materially superior design;
3. blast-radius analysis;
4. Human Showrunner approval.

---

# 2. North Star production loop

```text
DISCOVER
→ RESEARCH
→ CREATE / CANON
→ ADAPT / SCRIPT
→ DIRECT
→ PREPARE
→ PRODUCE
→ EVALUATE
→ PACKAGE / DISTRIBUTE
→ MEASURE / LEARN
→ next iteration
```

The same IP/content system may eventually produce:
- novel/story;
- screenplay;
- storyboard/previz;
- YouTube long-form;
- Shorts/TikTok;
- podcast/audio drama;
- short drama;
- film;
- future media formats.

---

# 3. Frozen top-level architecture

```text
                         HUMAN SHOWRUNNER
                                │
        ┌───────────────────────┴───────────────────────┐
        │                                               │
        ▼                                               ▼
 FACTUAL AUTHORITY                              FICTION/IP AUTHORITY
 ResearchPack                                   Canon Kernel
 ClaimLedger                                    Epistemic Engine
 Evidence                                       Canon Lineage
        │                                       Adaptation Branch
        │                                               │
        └───────────────────┬───────────────────────────┘
                            ▼
                    AUTHORIAL INTENT
                    NarrativePlan
                    CreativePolicy
                            │
                            ▼
                ScriptLikeArtifact
         ScriptArtifact / ScreenplayArtifact
                            │
                            ▼
                     DirectorAdapter
       OpenMontageDirector / TakeDirector / fallback
                            │
                            ▼
                  SceneSpec → ShotSpec
                            │
                            ▼
                 ShotPreparationService
                   Jellyfish-derived
                            │
                            ▼
                   ProductionBinding
          VisualIdentity / Continuity / References
                            │
                            ▼
                     Method Router
 REUSE | STOCK | CAPTURE | DETERMINISTIC | IMAGE | VIDEO | COMPOSITE
                            │
                            ▼
                  Capability Registry
                            │
                            ▼
                    PromptCompiler
                  when generation requires AI
                            │
                            ▼
                 ARCREEL-DERIVED HOST
 ┌─────────────────────────────────────────────────────────────┐
 │ PostgreSQL | Tasks | Queue | Provider execution            │
 │ Artifact Manifest | Currency | Provenance | Versions        │
 │ Recovery | Idempotency | Cost | Review | Export            │
 └─────────────────────────────────────────────────────────────┘
                            │
                            ▼
               GenerationCandidate[]
                            │
                            ▼
                  ApprovedMaster
                            │
                            ▼
               Remotion / FFmpeg / Edit
                            │
                            ▼
              Distribution / Analytics
                            │
                            ▼
                    Learning Engine
```

---

# 4. Five authoritative state planes

R1's earlier “three state planes” is superseded by this five-authority model.

## 4.1 Factual Authority

Owns evidence-backed truth for factual/general content.

Primary concepts:
- `ResearchPack`
- `ClaimLedger`
- `Claim`
- `Evidence`
- `Source`
- claim confidence/status
- evidence lineage

Used by:
- documentary;
- explainer;
- YouTube factual content;
- educational content;
- current-affairs content;
- research-driven media.

It is **not** Canon.

---

## 4.2 Narrative Authority

Owns in-world fictional truth.

Primary concepts:
- `CanonBranch`
- `CanonVersion`
- `Entity`
- `Fact`
- `Event`
- temporal/causal relations
- entity states
- `KnowledgeState`
- relationship state
- plot-thread truth
- adaptation lineage

The `Epistemic Engine` determines who knows, suspects, falsely believes, or does not know each relevant proposition over time.

Only the R2 Canon transaction path may mutate this plane.

---

## 4.3 Authorial Intent

Owns what the author/showrunner intends to build, not what is already true in-world.

Primary concepts:
- `StoryFrame`
- `VolumePlan`
- `ArcPlan`
- `EpisodePlan`
- `ChapterPlan`
- `SceneContract`
- `ThreadPlan`
- `PromisePayoffLedger`
- `CreativePolicy`
- `StyleGuide`
- `GenrePolicy`
- `POVPolicy`
- `PacingPolicy`

A plan can be revised without rewriting historical Canon.

---

## 4.4 Production Authority

Owned primarily by the ArcReel-derived Host.

Primary concepts:
- Artifact Manifest
- artifact provenance
- artifact currency
- version history
- production assets
- candidate generations
- selected/approved masters
- edit timeline
- quality reports
- formal media state
- cost/usage records

Production truth never becomes narrative truth automatically.

---

## 4.5 Runtime Authority

Owned by the ArcReel-derived Host.

Primary concepts:
- tasks;
- durable generation batches;
- provider jobs;
- execution checkpoints;
- submitted provider/base URL;
- retry/recovery state;
- cancellation state;
- queue state;
- SSE/runtime delivery state.

Runtime state does not determine whether an artifact is CURRENT/STALE and does not determine Canon truth.

---

# 5. Frozen hard invariants

These invariants are architecture-level constraints.

```text
Runtime State ≠ Artifact Truth
Artifact Truth ≠ Canon Truth
NarrativePlan ≠ Canon Truth
Research Claim ≠ Canon Truth
SimulationEvent ≠ Canon Event
DraftCandidate ≠ Canon
GenerationCandidate ≠ ApprovedMaster
Agent Memory ≠ Canon
Vector Memory ≠ Canon
Canvas State ≠ Production Truth
Provider Configuration ≠ Content Currency
```

Additional invariants:

1. **Candidate ≠ Canon**
   - No writer, simulator, reviewer or extraction agent may mutate Canon directly.

2. **Candidate ≠ ApprovedMaster**
   - Generation attempts remain candidates until selection/approval.

3. **Failed regeneration preserves usable prior output**
   - A failed new generation cannot erase or demote a still-valid selected prior artifact.

4. **Method before provider**
   - Choose `REUSE/STOCK/CAPTURE/DETERMINISTIC/IMAGE/VIDEO/COMPOSITE` before choosing a model/provider.

5. **Content fingerprint ≠ execution fingerprint**
   - Provider/model/seed/resolution changes create a new execution candidate, not automatic content staleness.

6. **Agent chat ≠ authoritative state**
   - Agent conversation/history may inform work but cannot silently own project truth.

7. **Story Bible is a composed view**
   - `StoryBibleView = Canon + NarrativePlan + CreativePolicy`.

8. **Adaptation cannot silently mutate source Canon**
   - Novel→screenplay or other medium transformations use an explicit adaptation branch/overlay.

9. **Selective invalidation**
   - Only declared direct content-basis changes may propagate staleness.

10. **Learning cannot silently rewrite authority**
    - Analytics/Learning may recommend changes but cannot directly mutate Canon, CreativePolicy or governance rules.

---

# 6. Common convergence contract

Factual and fiction systems intentionally remain different above production.

They converge here:

```text
FACTUAL
ResearchPack
→ ClaimLedger
→ ScriptArtifact
        \
         \
          → ScriptLikeArtifact
         /
        /
FICTION
Canon / NarrativePlan
→ ScreenplayArtifact
```

Then:

```text
ScriptLikeArtifact
→ DirectorAdapter
→ SceneSpec
→ ShotSpec
→ Production
```

This is the primary cross-media seam.

---

# 7. ContentBasis

Every script/scene/shot that enters production declares a `ContentBasis`.

## 7.1 FACTUAL

References:
- ResearchPack version;
- Claim IDs;
- Evidence IDs;
- Source IDs where needed.

## 7.2 NARRATIVE

References:
- Canon branch;
- Canon version;
- Fact/Event/Entity IDs;
- NarrativePlan version.

## 7.3 ADAPTATION

References:
- parent Canon branch/version;
- AdaptationBranch;
- AdaptationMap;
- adaptation overlay version.

Production layers do not need to know which donor generated the upstream content.

---

# 8. Canon lineage and adaptation

Frozen lineage model:

```text
                     IP ROOT
                        │
                  MAIN CANON BRANCH
                        │
                   CanonVersion N
                    /          \
                   /            \
                  ▼              ▼
        SCREEN ADAPTATION   AUDIO ADAPTATION
             branch             branch
```

## Branch types

### NarrativeBranch
Used for actual alternate continuity:
- what-if;
- alternate ending;
- interactive branch;
- spinoff with changed history.

### AdaptationBranch
Used for medium transformation:
- novel→screenplay;
- novel→short drama;
- novel→audio drama.

A branch:
- references immutable parent version;
- stores explicit divergence/overlay;
- is versioned;
- is auditable;
- does not duplicate the full parent Canon unless implementation later proves that necessary.

---

# 9. AdaptationMap

Adaptation lineage is first-class.

Supported transformation semantics include:

```text
PRESERVE
EXTERNALIZE
CONDENSE
COMBINE
SPLIT
OMIT
REORDER
REFRAME_POV
MODIFY_FOR_MEDIUM
```

Each mapping records:
- source refs;
- target refs;
- operation;
- rationale;
- fidelity risk;
- approval.

This distinguishes deliberate adaptation from hallucinated divergence.

---

# 10. Director architecture

`take` is not universal.

Frozen abstraction:

```text
DirectorAdapter
├── TakeDirector
├── OpenMontageDirector
└── ArcReelNativeDirector
```

## TakeDirector
Primary for:
- fiction;
- screenplay;
- drama;
- cinematic sequences;
- camera-heavy work.

Owns creative decomposition:
- beats;
- shots;
- framing;
- camera grammar;
- movement;
- duration intent.

Does **not** own runtime/provider jobs.

## OpenMontageDirector
Primary for:
- explainer;
- screen demo;
- documentary;
- hybrid;
- talking-head;
- clip factory;
- deterministic/motion-graphic content.

## ArcReelNativeDirector
Compatibility/fallback route.

All adapters normalize to:
- `SceneSpec`
- `ShotSpec`

---

# 11. Production preparation

After `ShotSpec`:

```text
ShotSpec
→ ShotPreparationService
→ ProductionBinding[]
→ ProductionReadiness
```

The Jellyfish-derived preparation layer resolves:
- characters;
- production variants;
- location;
- props;
- wardrobe;
- dialogue/speaker;
- voice;
- keyframes;
- reference assets;
- continuity anchors.

Frozen principle:

```text
shot content status
≠ production readiness
≠ runtime task status
```

---

# 12. Visual identity and continuity

Visual identity is a first-class domain concept.

Example:

```text
VisualIdentityProfile
  semantic character ref
  face master
  body master
  profile/side references
  hairstyle lock
  costume locks
  accessory locks
  injury/state variants
  approved reference assets
```

Previous-frame chaining is conditional:

```text
ApprovedShotMaster(N).end_frame
→ PREVIOUS_SHOT binding
→ Shot(N+1)
```

only when:
- continuity segment requires it;
- provider supports it;
- Director allows it;
- it improves rather than constrains the next shot.

---

# 13. Production Method Router

Frozen method choices:

```text
REUSE
STOCK
SCREEN_CAPTURE
DETERMINISTIC
GENERATED_IMAGE
GENERATED_VIDEO
COMPOSITE
```

Reuse-first policy:

```text
approved artifact?
→ existing asset/library?
→ deterministic tool?
→ local model?
→ cheap API?
→ premium generation
```

The Method Router chooses the production method before provider/model selection.

---

# 14. Capability Registry

R2 exposes one normalized capability authority to routing/business logic.

Sources may include:
- ArcReel direct backend capabilities;
- DC-Media gateway catalog;
- OpenMontage tool metadata;
- ComfyUI/local services;
- deterministic tools;
- OBS;
- Remotion;
- FFmpeg.

Low-level provider catalogs remain transport/runtime evidence.

Business logic consumes only the normalized R2 `CapabilityRegistry`.

---

# 15. PromptCompiler

Butterfly-derived PromptCompiler runs only for generative methods that need semantic prompt compilation.

Input:
- `ShotSpec`
- `ProductionBinding`
- `VisualIdentityProfile`
- continuity anchors
- `CreativePolicy`
- capability constraints

Output:
- `PromptPlan`

`PromptPlan` may include:
- semantic instruction;
- positive prompt;
- negative prompt;
- identity tokens;
- style tokens;
- reference binding IDs;
- exclusions.

Provider-specific API syntax remains in the Provider Adapter.

---

# 16. ArcReel Host — LOCKED

R1.8 target-Ubuntu evidence promoted ArcReel from candidate to locked Host.

Pinned verification baseline:

```text
tag: v0.29.0
sha: 6ddedc775e7fe5f398b10081ab741985f7dceda7
```

## Host owns

```text
PostgreSQL
Project Runtime
API / Auth / SSE
Application Services
Generation Queue
Provider Execution
Provider Job Identity
Execution Checkpoints
Task Recovery
Idempotency
Artifact Manifest
Artifact Currency
Production Provenance
Media Versions
Candidate Persistence
Cost / Usage
Workflow Status / Plan
Formal Asset State
Review / Approval Infrastructure
FFmpeg/media mechanics
Editable package export
```

## Host does not own

```text
Fiction Canon
Epistemic truth
NarrativePlan authority
Factual claim/evidence authority
NarrativeContextCompiler
CanonDeltaCompiler
CanonTransactionService
Production Method decision
cross-media learning authority
```

---

# 17. ArcReel Artifact Manifest extension strategy

R2 does not create a second artifact registry.

Extend ArcReel's existing Artifact Manifest upward with R2 content basis.

Example dependency basis:

```text
artifact:
  SceneSpec v7
  ShotSpec v4
  ProductionBinding v2
  FACE_MASTER v4
  Canon Event EVT_19
```

Content provenance excludes execution-only variables such as:
- provider;
- model;
- endpoint;
- seed;
- resolution;
- generation settings;
- prompt-compiler version.

Those are recorded under execution provenance/fingerprint.

---

# 18. Generation candidates and approved masters

Frozen semantics:

```text
ShotSpec SH042
├── Candidate A — REJECTED
├── Candidate B — SELECTED
├── Candidate C — FAILED
└── ApprovedShotMaster → B
```

If D fails later:
- B remains the approved master;
- ShotSpec remains unchanged;
- production history retains D's failure.

`ApprovedShotMaster` is an R2 first-class semantic layered above ArcReel's native version/candidate storage.

---

# 19. Creative Canvas

DramaClaw-derived canvas is an exploration plane.

It may:
- generate;
- branch;
- compare;
- restore;
- group;
- use spatial/360/3D tools.

It may **not** directly mutate authoritative production state.

Required bridge:

```text
CanvasCandidate
→ preview impact
→ PROMOTE
→ ArcReel/R2 production artifact
```

Promotion must be explicit and auditable.

---

# 20. Narrative architecture

Frozen roles:

## Novel Studio AI
Narrative Workbench:
- hierarchical planning UX;
- context-pack patterns;
- draft/continuity/revise/accept workflow.

## Shenbi
Narrative Skill and Quality library:
- genesis;
- architecture;
- planning;
- writing skills;
- audits;
- import;
- drift/snapshot/revision patterns.

Its `state-settling` semantics are reinterpreted as proposal extraction, not Canon mutation.

## Huohuo
Primary donor for:
- causal Change Record;
- `NarrativeChangeSet`;
- novel→screen adaptation.

## StoryBox
Simulation Lab:
- character/environment simulation;
- candidate events;
- event compression/retrieval.

`SimulationEvent ≠ Canon Event`.

---

# 21. NarrativeContextCompiler — R2 Core

The authoritative Context Pack compiler is R2-owned.

Input:
- Canon version;
- Epistemic view;
- NarrativePlan;
- CreativePolicy;
- POV;
- SceneContract;
- recent accepted prose;
- retrieval;
- token budget.

Output:
- `NarrativeContextPack`

It may reuse algorithms from Novel Studio, Shenbi and Huohuo, but authoritative source selection and epistemic filtering belong to R2.

---

# 22. NarrativeChangeSet and CanonDelta

Candidate prose may produce:

```text
NarrativeChangeSet
```

representing:
- trigger;
- process;
- outcome;
- before/after state;
- relationship effects;
- knowledge effects;
- prop/object effects;
- plot-thread effects;
- evidence spans.

Then:

```text
NarrativeRevision
+ NarrativeChangeSet
+ CanonVersion
→ CanonDeltaCompiler
→ CanonDelta
```

Only:

```text
CanonTransactionService
```

may commit:

```text
PROPOSE
→ validate
→ conflict check
→ temporal/causal/epistemic validation
→ approval
→ COMMIT
→ CanonVersion N+1
```

---

# 23. Factual content architecture

General/factual path:

```text
Topic
→ OpenMontage-derived research
→ ResearchPack
→ ClaimLedger
→ ContentBrief
→ ScriptArtifact
→ OpenMontageDirector
→ SceneSpec
→ ShotSpec / deterministic scene units
→ Production
```

Claim-level lineage allows selective invalidation when evidence changes.

Factual evidence is not forced into fiction Canon.

---

# 24. Composition

After approved production artifacts:

```text
ApprovedMaster[]
+ dialogue/narration/music
→ EditTimelineArtifact
→ RenderEngine
```

Preferred roles:
- OpenMontage/Remotion — general-content mixed composition;
- ArcReel/FFmpeg — media mechanics, drama/film assembly;
- HyperFrames — specialized deterministic motion graphics;
- editable export where useful.

No renderer owns upstream truth.

---

# 25. Learning Engine boundary

Learning consumes:
- distribution results;
- performance metrics;
- production cost;
- QA findings;
- method/provider outcomes.

It may produce:
- recommendations;
- experiment proposals;
- routing suggestions;
- content hypotheses.

It may not directly mutate:
- Canon;
- NarrativePlan;
- CreativePolicy;
- Claim truth;
- governance.

Any promotion from learning into authority requires an explicit review/transaction path.

---

# 26. Frozen donor ownership

| System | Frozen role |
|---|---|
| ArcReel | Primary Host / Production Runtime |
| OpenMontage | General-content intelligence, tools, Director, Remotion |
| DramaClaw | Creative Canvas, Visual Workbench, optional DC-Media transport |
| take | Fiction/Cinematic Director / Shot Grammar |
| Jellyfish | Shot Preparation / Readiness |
| ai-short-film | Visual Identity / continuity anchors |
| Butterfly | PromptCompiler / prompt-history patterns |
| Novel Studio AI | Narrative Workbench |
| Shenbi | Narrative skills + quality gates |
| Huohuo | NarrativeChangeSet + adaptation |
| StoryBox | Simulation Lab |
| R2 custom core | Authority, lineage, context, transactions, routing, learning |

---

# 27. Known Host hardening requirement

## R2-HOST-001

Before production allows provider changes during active I2V tasks:

Either:
1. persist actual execution identity at submission and always resume against it; or
2. temporarily reject provider/base-url changes while affected active tasks exist.

This is a production launch blocker, not a Host-selection blocker.

---

# 28. Architecture freeze rules

After R2.1:

1. No new donor becomes a core authority without explicit architecture-change approval.
2. No donor-local memory/project store becomes authoritative merely because an adapter uses it.
3. No parallel queue/artifact registry may be introduced without proving an ArcReel blocker.
4. No provider/model field may enter stable `SceneSpec`/`ShotSpec`.
5. No adaptation may mutate source Canon without a branch transaction.
6. No analytics system may silently mutate authority.
7. Broad donor research is closed; future research is targeted gap resolution or provider qualification.

---

# 29. Superseded assumptions

R2.1 supersedes:

- the old three-state-plane model;
- “take as universal Director”;
- “one flat Canon for every medium”;
- any assumption that Story Bible is one monolithic truth file;
- any plan for a separate custom Artifact Registry;
- any plan for a second general media queue beside ArcReel;
- any design where provider config determines content staleness.

---

# 30. R2.1 exit criteria

R2.1 is complete when:
- Human Showrunner approves the architecture;
- this document is stored in the R2 freeze package;
- R2.2 Responsibility Matrix does not contradict it;
- later contract schemas map unambiguously to these authority planes.

**Status: COMPLETE / FROZEN v1**

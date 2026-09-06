# R2.4 — Consolidated Decision Log

**Project:** Content & Narrative Production OS  
**Phase:** R2 — Architecture Freeze  
**Date:** 2026-09-06  
**Status:** **FROZEN v1**  
**Approval:** Human Showrunner approved R2.4 on 2026-09-06

---

# 1. Decision status model

```text
LOCKED
ACTIVE
SUPERSEDED
DEFERRED
REJECTED
```

`LOCKED` decisions require explicit architecture-change approval to reopen.
`ACTIVE` decisions are current policy but may still be refined by measured implementation evidence without reopening the whole architecture.
`DEFERRED` decisions remain valid but intentionally postponed.
`SUPERSEDED` and `REJECTED` decisions must not be used by implementation agents.

# 2. Reopen gate

A LOCKED decision may be reopened only for at least one of:

- verified implementation blocker;
- upstream breaking change;
- measured unacceptable performance/cost;
- security/data-integrity problem;
- discovered contract contradiction;
- materially superior replacement with executable evidence.

A new repository/model being interesting is not a reopen condition.

# 3. Canonical current decisions

## R2-DEC-001 — Human Showrunner remains final creative/governance authority

**Status:** `LOCKED`  
**Category:** `AUTHORITY_GOVERNANCE`

Human approval/override is explicit, auditable, and cannot be replaced by autonomous agent mutation.

**Rationale:** Prevents silent authority drift while preserving automation.

**Legacy refs:** none mapped

**Affected contracts:** CreativePolicy, CanonDelta, ApprovedMaster

**Affected components:** Governance, CanonTransactionService, ProductionApprovalService

**Reopen conditions:** verified governance blocker, security/data-integrity problem

## R2-DEC-002 — Exactly one commit authority per authoritative state family

**Status:** `LOCKED`  
**Category:** `AUTHORITY_GOVERNANCE`

Every authoritative state family has exactly one formal commit authority; other systems may only read/propose/approve according to R2.2.

**Rationale:** Prevents conflicting stores and multi-agent write races.

**Legacy refs:** none mapped

**Affected contracts:** all authoritative contracts

**Affected components:** all adapters, CI architecture tests

**Reopen conditions:** contract contradiction discovered

## R2-DEC-003 — Five authority planes

**Status:** `LOCKED`  
**Category:** `AUTHORITY_GOVERNANCE`

Freeze Factual Authority, Narrative Authority, Authorial Intent, Production Authority, and Runtime Authority as distinct planes.

**Rationale:** R1 evidence showed the former three-plane model was insufficient for factual truth and authorial-plan separation.

**Legacy refs:** none mapped

**Affected contracts:** ResearchPack, ClaimLedger, CanonVersion, NarrativePlan, Artifact Manifest, Runtime Task

**Affected components:** FactualAuthorityService, Canon Kernel, NarrativePlanService, ArcReel Host

**Reopen conditions:** contract contradiction discovered

## R2-DEC-004 — Candidate is never Canon

**Status:** `LOCKED`  
**Category:** `NARRATIVE`

Drafts, simulations, extracted changes, reviews, and generated candidates remain non-authoritative until an explicit transaction commits them.

**Rationale:** Separates creative exploration from truth mutation.

**Legacy refs:** R2-D48, R2-D54

**Affected contracts:** DraftCandidate, SimulationEvent, NarrativeChangeSet, CanonDelta

**Affected components:** Novel Studio adapters, Shenbi adapters, StoryBox adapters, CanonTransactionService

**Reopen conditions:** none except architecture change approval

## R2-DEC-005 — NarrativePlan is separate from Canon

**Status:** `LOCKED`  
**Category:** `NARRATIVE`

Future authorial intent is stored in NarrativePlan/SceneContract, not as established world truth.

**Rationale:** Prevents planned future events from contaminating current Canon.

**Legacy refs:** R2-D52, R2-D53

**Affected contracts:** StoryFrame, VolumePlan, EpisodePlan, ArcPlan, ChapterPlan, SceneContract, CanonVersion

**Affected components:** NarrativePlanService, StoryBibleView

**Reopen conditions:** contract contradiction discovered

## R2-DEC-006 — KnowledgeState is first-class

**Status:** `LOCKED`  
**Category:** `NARRATIVE`

Who knows, suspects, falsely believes, or does not know a proposition is explicit authoritative state.

**Rationale:** Prevents secret leakage and makes epistemic continuity mechanically testable.

**Legacy refs:** none mapped

**Affected contracts:** KnowledgeState

**Affected components:** Epistemic Engine, NarrativeContextCompiler

**Reopen conditions:** materially superior representation with executable evidence

## R2-DEC-007 — NarrativeContextCompiler is R2 core

**Status:** `LOCKED`  
**Category:** `NARRATIVE`

Authoritative context selection and epistemic filtering belong to the R2-owned NarrativeContextCompiler.

**Rationale:** Donor context systems are useful but cannot define authoritative visibility rules.

**Legacy refs:** R2-D51

**Affected contracts:** NarrativeContextPack

**Affected components:** NarrativeContextCompiler

**Reopen conditions:** verified implementation blocker

## R2-DEC-008 — NarrativeChangeSet is distinct from CanonDelta

**Status:** `LOCKED`  
**Category:** `NARRATIVE`

NarrativeChangeSet describes inferred changes from prose; CanonDelta is the explicit authoritative mutation proposal.

**Rationale:** Separates extraction uncertainty from intended truth mutation.

**Legacy refs:** R2-D49, R2-D54

**Affected contracts:** NarrativeChangeSet, CanonDelta

**Affected components:** Huohuo adapter, CanonDeltaCompiler, CanonTransactionService

**Reopen conditions:** contract contradiction discovered

## R2-DEC-009 — Adaptation uses explicit branch/overlay lineage

**Status:** `LOCKED`  
**Category:** `ADAPTATION`

Medium adaptation never silently mutates source Canon; it uses parent-linked AdaptationBranch plus AdaptationMap.

**Rationale:** Allows screenplay/audio variants while preserving source IP truth.

**Legacy refs:** R2-D57, R2-D58, R2-D59, R2-D60

**Affected contracts:** ContentBasis, AdaptationBranch, AdaptationMap, ScreenplayArtifact

**Affected components:** AdaptationTransactionService, Huohuo adapter

**Reopen conditions:** verified implementation blocker

## R2-DEC-010 — Factual truth and fiction truth remain distinct

**Status:** `LOCKED`  
**Category:** `FACTUAL`

Factual content uses ResearchPack/ClaimLedger/Evidence; fiction uses Canon/Epistemic. They converge only at ScriptLikeArtifact/SceneSpec/ShotSpec.

**Rationale:** Avoids forcing evidence truth into fiction semantics.

**Legacy refs:** R2-D56, R2-D57

**Affected contracts:** ResearchPack, ClaimLedger, ContentBasis, ScriptArtifact, ScreenplayArtifact, SceneSpec, ShotSpec

**Affected components:** FactualAuthorityService, DirectorAdapter

**Reopen conditions:** contract contradiction discovered

## R2-DEC-011 — ArcReel-derived Host is primary runtime

**Status:** `LOCKED`  
**Category:** `HOST_RUNTIME`

ArcReel-derived Host owns PostgreSQL, runtime tasks, queue, provider execution, Artifact Manifest, currency, provenance, recovery, idempotency, cost, review, and export.

**Rationale:** R1.8 target-Ubuntu evidence passed source, PostgreSQL, restart, fault/recovery, idempotency, and backup/restore checks.

**Legacy refs:** R2-D08, R2-D29, R2-D30, R2-D31, R2-D65

**Affected contracts:** ProviderRequest, GenerationCandidate, Artifact Manifest, ApprovedMaster

**Affected components:** ArcReel Host

**Reopen conditions:** verified implementation blocker, upstream breaking change, security/data-integrity problem, measured unacceptable performance/cost

## R2-DEC-012 — Use PostgreSQL from Host fork start

**Status:** `LOCKED`  
**Category:** `HOST_RUNTIME`

The R2 Host fork starts on PostgreSQL rather than SQLite as the production development baseline.

**Rationale:** R1.8 validated PostgreSQL migrations and restart health on the target machine.

**Legacy refs:** none mapped

**Affected contracts:** none

**Affected components:** ArcReel Host, database deployment

**Reopen conditions:** verified deployment blocker

## R2-DEC-013 — Extend ArcReel Artifact Manifest; no parallel artifact registry

**Status:** `LOCKED`  
**Category:** `HOST_RUNTIME`

R2 content lineage extends ArcReel Artifact Manifest instead of introducing a second authoritative artifact registry.

**Rationale:** Avoids dual artifact truth and reuses verified ArcReel currency/provenance machinery.

**Legacy refs:** R2-D29, R2-D65

**Affected contracts:** ContentBasis, SceneSpec, ShotSpec, ProductionBinding

**Affected components:** ArcReel Artifact Manifest

**Reopen conditions:** verified ArcReel manifest blocker

## R2-DEC-014 — No second general media queue

**Status:** `LOCKED`  
**Category:** `HOST_RUNTIME`

Provider execution, durable task recovery, deduplication, and cancellation stay in ArcReel runtime.

**Rationale:** A second queue would duplicate the strongest verified ArcReel capability.

**Legacy refs:** R2-D30, R2-D40, R2-D41

**Affected contracts:** ProviderRequest, GenerationCandidate

**Affected components:** ArcReel Queue, donor runtime adapters

**Reopen conditions:** verified ArcReel queue blocker

## R2-DEC-015 — DirectorAdapter is format-sensitive

**Status:** `LOCKED`  
**Category:** `DIRECTOR`

Use TakeDirector for fiction/cinematic, OpenMontageDirector for general content, and ArcReelNativeDirector as fallback.

**Rationale:** R1.6 showed take is not universal and OpenMontage has stronger general-content scene planning.

**Legacy refs:** R2-D15, R2-D61, R2-D62

**Affected contracts:** ScriptArtifact, ScreenplayArtifact, SceneSpec, ShotSpec

**Affected components:** DirectorAdapter, TakeDirector, OpenMontageDirector

**Reopen conditions:** measured inferior director quality for target format

## R2-DEC-016 — Shot readiness is distinct from content status and runtime task status

**Status:** `LOCKED`  
**Category:** `PRODUCTION`

ShotPreparationService produces ProductionBinding and ProductionReadiness independently of creative approval and runtime tasks.

**Rationale:** Prevents expensive generation with unresolved production prerequisites.

**Legacy refs:** R2-D16, R2-D42, R2-D63

**Affected contracts:** ProductionBinding, ProductionReadiness

**Affected components:** ShotPreparationService

**Reopen conditions:** contract contradiction discovered

## R2-DEC-017 — VisualIdentityProfile is first-class production state

**Status:** `LOCKED`  
**Category:** `PRODUCTION`

Character visual identity, look locks, and production variants are explicit production bindings, separate from Canon identity.

**Rationale:** Improves continuity without contaminating Canon with production asset paths.

**Legacy refs:** R2-D17, R2-D43

**Affected contracts:** VisualIdentityProfile, ProductionBinding

**Affected components:** ai-short-film adapter, ArcReel character variants

**Reopen conditions:** materially superior representation with executable evidence

## R2-DEC-018 — Previous-frame chaining is conditional

**Status:** `ACTIVE`  
**Category:** `PRODUCTION`

Use prior approved end-frame as a continuity binding only when the continuity segment and provider capability justify it.

**Rationale:** Preserves continuity without over-constraining every shot.

**Legacy refs:** R2-D44

**Affected contracts:** ProductionBinding, ShotSpec

**Affected components:** continuity policy, provider adapters

**Reopen conditions:** measured quality evidence

## R2-DEC-019 — ProductionBinding is the semantic-to-production bridge

**Status:** `LOCKED`  
**Category:** `PRODUCTION`

All semantic entities/assets needed for production are connected through ProductionBinding rather than direct asset fields in Canon/ShotSpec.

**Rationale:** Keeps semantic truth and production variants decoupled.

**Legacy refs:** R2-D63

**Affected contracts:** ProductionBinding, ShotSpec, VisualIdentityProfile

**Affected components:** ProductionPreparationService, ArcReel adapters

**Reopen conditions:** contract contradiction discovered

## R2-DEC-020 — Method before provider

**Status:** `LOCKED`  
**Category:** `ROUTING`

Choose REUSE/STOCK/SCREEN_CAPTURE/DETERMINISTIC/GENERATED_IMAGE/GENERATED_VIDEO/COMPOSITE before provider/model selection.

**Rationale:** Encodes reuse-first economics and avoids provider-driven creative architecture.

**Legacy refs:** R2-D33, R2-D34

**Affected contracts:** MethodDecision, ProviderRequest

**Affected components:** MethodRouterService, CapabilityRegistry

**Reopen conditions:** measured unacceptable routing performance

## R2-DEC-021 — One normalized CapabilityRegistry

**Status:** `LOCKED`  
**Category:** `ROUTING`

Business routing reads one R2 CapabilityRegistry normalized from ArcReel, DC-Media, OpenMontage and local/deterministic capabilities.

**Rationale:** Prevents multiple competing provider catalogs in business logic.

**Legacy refs:** R2-D33, R2-D37, R2-D38, R2-D39

**Affected contracts:** MethodDecision, ProviderRequest

**Affected components:** CapabilityRegistry

**Reopen conditions:** verified capability-model blocker

## R2-DEC-022 — PromptPlan is separate from ProviderRequest

**Status:** `LOCKED`  
**Category:** `ROUTING`

Butterfly-derived PromptCompiler produces provider-neutral PromptPlan; provider adapters produce exact ProviderRequest payloads.

**Rationale:** Keeps stable creative semantics independent of vendor API.

**Legacy refs:** R2-D18, R2-D45

**Affected contracts:** PromptPlan, ProviderRequest

**Affected components:** PromptCompilerService, Provider adapters

**Reopen conditions:** contract contradiction discovered

## R2-DEC-023 — SceneSpec and ShotSpec are provider-neutral

**Status:** `LOCKED`  
**Category:** `PRODUCTION`

Stable production semantic contracts cannot contain provider/model/endpoint/API payload/provider job identity.

**Rationale:** Allows routing and runtime changes without rewriting creative semantics.

**Legacy refs:** none mapped

**Affected contracts:** SceneSpec, ShotSpec

**Affected components:** DirectorAdapter, architecture CI

**Reopen conditions:** none except explicit architecture change

## R2-DEC-024 — Content fingerprint is distinct from execution fingerprint

**Status:** `LOCKED`  
**Category:** `PRODUCTION`

Artifact currency uses semantic/content dependencies; provider/model/seed/resolution belong to execution provenance and candidate comparison.

**Rationale:** Provider changes should not automatically stale valid content.

**Legacy refs:** R2-D64

**Affected contracts:** GenerationCandidate, Artifact Manifest

**Affected components:** artifact currency, provider execution

**Reopen conditions:** verified incorrect invalidation behavior

## R2-DEC-025 — ApprovedMaster requires explicit selection

**Status:** `LOCKED`  
**Category:** `PRODUCTION`

A successful generation is not an approved master; selection/approval is explicit and failed later generations preserve the existing master.

**Rationale:** Protects usable production state and separates generation from editorial authority.

**Legacy refs:** R2-D66

**Affected contracts:** GenerationCandidate, ApprovedMaster

**Affected components:** ProductionApprovalService, ArcReel version storage

**Reopen conditions:** contract contradiction discovered

## R2-DEC-026 — Creative Canvas is exploration-only until PROMOTE

**Status:** `LOCKED`  
**Category:** `CREATIVE_CANVAS`

DramaClaw-derived canvas cannot directly mutate production authority; explicit audited PROMOTE creates formal production artifacts.

**Rationale:** Preserves experimentation without state contamination.

**Legacy refs:** R2-D35, R2-D36

**Affected contracts:** CanvasCandidate, ApprovedMaster

**Affected components:** DramaClaw canvas adapter, promotion service

**Reopen conditions:** verified UX blocker requiring a different promotion boundary

## R2-DEC-027 — Director World is deferred advanced spatial planning

**Status:** `DEFERRED`  
**Category:** `CREATIVE_CANVAS`

DramaClaw Director World/3D spatial planning is deferred until advanced creative workbench phase.

**Rationale:** High value but not required for first implementation milestone.

**Legacy refs:** R2-D37

**Affected contracts:** ProductionBinding

**Affected components:** advanced canvas

**Reopen conditions:** R8/advanced creative workbench start

## R2-DEC-028 — OpenMontage/Remotion is primary deterministic composition path

**Status:** `ACTIVE`  
**Category:** `COMPOSITION`

Use Remotion for general mixed compositions; ArcReel/FFmpeg retain media mechanics and drama assembly; HyperFrames stays specialized.

**Rationale:** Matches donor strengths and avoids replacing proven FFmpeg/runtime mechanics.

**Legacy refs:** R2-D19

**Affected contracts:** EditTimelineArtifact

**Affected components:** Remotion, FFmpeg, ArcReel, HyperFrames

**Reopen conditions:** measured composition quality/performance blocker

## R2-DEC-029 — Learning produces recommendations, not authority mutation

**Status:** `LOCKED`  
**Category:** `LEARNING`

Analytics/Learning can recommend experiments, routing or policy changes but cannot directly mutate Canon, Claim truth, NarrativePlan or CreativePolicy.

**Rationale:** Prevents metric optimization from silently rewriting creative/governance authority.

**Legacy refs:** none mapped

**Affected contracts:** PerformanceReport, CreativePolicy, NarrativePlan

**Affected components:** LearningEngine, Governance

**Reopen conditions:** none except explicit governance redesign

## R2-DEC-030 — R2-HOST-001 blocks production provider-reconfiguration during vulnerable I2V recovery

**Status:** `ACTIVE`  
**Category:** `HOST_RUNTIME`

Before production, persist actual execution identity at provider submission or block affected provider/base-url changes while matching active I2V tasks exist.

**Rationale:** Mitigates the known ArcReel recovery identity gap documented during R1.8.

**Legacy refs:** none mapped

**Affected contracts:** ProviderRequest

**Affected components:** ArcReel provider execution, configuration service

**Reopen conditions:** upstream fix merged and verified, equivalent local patch verified

# 4. Superseded / rejected legacy assumptions

## LEGACY-THREE-STATE-PLANES

**Status:** `SUPERSEDED`  
**Replacement:** `R2-DEC-003`  
**Reason:** Factual truth and authorial intent require independent authorities.

## LEGACY-TAKE-UNIVERSAL-DIRECTOR

**Status:** `SUPERSEDED`  
**Replacement:** `R2-DEC-015`  
**Reason:** General content and cinematic fiction require different director adapters.

## LEGACY-ONE-FLAT-CANON-FOR-ALL-MEDIA

**Status:** `SUPERSEDED`  
**Replacement:** `R2-DEC-009`  
**Reason:** Adaptations need explicit branch/overlay lineage.

## LEGACY-STORY-BIBLE-AS-MONOLITHIC-TRUTH

**Status:** `SUPERSEDED`  
**Replacement:** `R2-DEC-005`  
**Reason:** StoryBibleView is a projection of Canon + Plan + Policy.

## LEGACY-CUSTOM-PARALLEL-ARTIFACT-REGISTRY

**Status:** `REJECTED`  
**Replacement:** `R2-DEC-013`  
**Reason:** ArcReel Artifact Manifest is the production artifact authority.

## LEGACY-SECOND-GENERAL-MEDIA-QUEUE

**Status:** `REJECTED`  
**Replacement:** `R2-DEC-014`  
**Reason:** ArcReel queue/recovery/idempotency is verified and should remain authoritative.

## LEGACY-PROVIDER-CONFIG-STALES-CONTENT

**Status:** `REJECTED`  
**Replacement:** `R2-DEC-024`  
**Reason:** Execution configuration belongs to execution fingerprint, not content currency.

# 5. Implementation rule for agents

Implementation agents must read the machine-readable `R2_04_DECISION_REGISTRY.json` first.

If an old handoff, donor document or prior R1 note conflicts with a current `LOCKED` decision, the R2.4 registry wins.

# 6. R2.4 exit criteria

- current decisions have explicit status;
- known superseded assumptions have explicit replacements;
- unresolved items are separated into implementation/provider/deferred decisions;
- architecture is not reopened for ordinary implementation detail;
- machine-readable registry is available for CI/agent bootstrap.

**Status: COMPLETE / FROZEN v1**

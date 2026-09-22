# R2 research — V1 production readiness and V2 deferment

Date: 2026-09-17
Examined checkout: `design/r2-m5b-narrative-context` at
`abc84bc7dac50dc55ebd68c681e7c08c473200f1`.

**Scope.** This is a research and sequencing recommendation for one
self-hosted operator. It does not accept a milestone, authorize a provider
call/spend, alter a frozen boundary, or make a historical test result current
acceptance. License analysis is intentionally outside scope.

**Disposition.** The sponsor accepted the V1-first/V2-from-release-lineage
recommendation and kept all four Human Gates mandatory. The resulting decision
is [ADR-0089](../adr/0089-ship-a-bounded-v1-before-v2-portfolio-automation.md),
with its operational release gates in
[`R2_V1_PRODUCTION_RELEASE_STRATEGY.md`](../r2/R2_V1_PRODUCTION_RELEASE_STRATEGY.md).

## 1. Decision in brief

**Recommendation:** make V1 a deliberately narrow, host-first production
release: an operator can take either an existing factual/explainer script or
an existing narrative source/script, produce a reviewable short video, export
a playable deliverable (and, where applicable, a Jianying draft), and retain
the project/task/version evidence needed to continue work. Four human gates
remain mandatory: A Greenlight, B Narrative Lock, C Final Cut, D Publish
Approval. In V1, Gate D authorizes **manual external publication**; V1 does
not itself upload/schedule/publicly release.

Finish and release that V1 on one clean, tagged lineage. Only then create V2
as a Git fork/branch plus a database/media recovery baseline from that release;
do not copy a working directory. V2 is the place for the multi-pipeline
portfolio control plane and the still-unimplemented R2 discovery, quality,
distribution and learning authorities.

This is not a retreat from the North Star. The frozen architecture already
defines the full loop (`DISCOVER` through `MEASURE / LEARN`) and multiple media
forms [R2.1:36-61](../r2/R2_01_FROZEN_ARCHITECTURE.md#2-north-star-production-loop).
It is a release boundary that makes a real product before expanding the number
of authorities, network side effects, and operational dependencies.

## 2. Evidence and current state

### Facts

* ArcReel already presents itself as a self-hosted workbench for novel/script/
  product material; its documented path is content analysis, assets, episodes,
  storyboard, video/narration, composition and Jianying export
  [README:64-86](../../README.md#L64-L86). It can be started locally with the
  documented database/backend/frontend commands [CONTRIBUTING:13-31](../../CONTRIBUTING.md#L13-L31).
* The host's project model fixes `generation_mode` to `storyboard` or
  `reference_video`, and accepts `novel` or `screenplay` source kinds
  [project manager:100-111](../../lib/project_manager.py#L100-L111). The UI
  routes real source, character, scene, prop, product and episode workspaces
  [StudioCanvasRouter:584-699](../../frontend/src/components/canvas/StudioCanvasRouter.tsx#L584-L699).
* The host has a shared asynchronous queue backed by `TaskRepository`
  [generation queue:1-31](../../lib/generation_queue.py#L1-L31); its workflow
  panel consumes server-provided plans and blockers rather than inventing local
  state [WorkflowPanel:35-85](../../frontend/src/components/workflow/WorkflowPanel.tsx#L35-L85).
* R2's common contract kernel and the production approval adapter are present
  in this checkout. The latter validates generated candidate, target and
  content fingerprint before a host-version promotion
  [common:14-27](../../r2/contracts/common.py#L14-L27),
  [approval service:26-76](../../r2/production/approval_service.py#L26-L76).
* Frozen ownership expressly leaves Production Artifact truth and Runtime Task
  truth with ArcReel Host; each authoritative state has one commit authority
  [R2.2:16-28](../r2/R2_02_FROZEN_RESPONSIBILITY_MATRIX.md#L16-L28),
  [R2.2:82-99](../r2/R2_02_FROZEN_RESPONSIBILITY_MATRIX.md#L82-L99).
* The 2026-09-09 status review records that M3 does not meet its own product
  exit gate, real generated provider execution is waived/deferred, M5C/M6/M7
  were not then accepted, and the DISCOVER/EVALUATE/DISTRIBUTE/LEARN planes
  were unbuilt [status review:72-100](../r2/evidence/PROJECT_STATUS_REVIEW_2026-09-09.md#L72-L100).
  This is historical evidence, not a current acceptance result.
* Live inspection today: `r2/main` is `71a96bd6`; M5C worktree is
  `43ec287a`; M6 is `814761e3`; M7 is `fd976115` and has five untracked source/
  test files (`execution_adapter.py`, `execution.py`, `execution_attempts.py`
  and two tests). The primary checkout is dirty in unrelated M12-E documents.
  No merge or acceptance can be inferred from these worktree facts.
* ADR-0078's accepted direction is to harden the existing queue/manifest/
  provider surfaces, not create a second queue or workflow engine
  [ADR-0078:5-12](../adr/0078-durable-execution-evidence-and-recoverable-production-boundaries.md#L5-L12).
  It requires immutable `ExecutionAttempt` before paid async submission and
  fail-closed reconciliation for ambiguous outcomes [ADR-0078:14-33](../adr/0078-durable-execution-evidence-and-recoverable-production-boundaries.md#L14-L33).
* ADR-0080 assigns discovery, quality/package, distribution and learning to
  M9--M12; it forbids starting a milestone from a planned predecessor
  [ADR-0080:24-76](../adr/0080-post-m8-north-star-closed-loop.md#L24-L76).
  M11 and M12 ADRs are still `proposed` [ADR-0083:1-20](../adr/0083-m11-governed-distribution.md#L1-L20),
  [ADR-0084:1-12](../adr/0084-m12-closed-loop-portfolio-learning.md#L1-L12).

### Inferences

The installed host is a credible V1 substrate, but it is not evidence of a
fully operational R2 closed loop. Its strongest currently observable seam is
operator-controlled production and export, while automatic publishing and
analytics would add unaccepted authority and provider-effect risk. Therefore
V1 should compose existing host capabilities, not make the R2 paper roadmap a
runtime dependency.

### Unknowns to resolve during V1 acceptance

* Which exact paid providers/accounts will be qualified, their limits and the
  required operator spend cap.
* A current end-to-end production proof on the intended machine: actual media,
  not a metadata fixture or historical green suite.
* Whether the M5C/M6/M7 branches satisfy their own exact acceptance contracts
  on a clean integration lineage.
* Operator's measurable definition of acceptable factual/explainer and drama
  quality (duration, intelligibility, continuity and deliverable criteria).

## 3. Mapping the requested operating model

| Requested capability | Classification | V1 treatment / reuse seam | Minimum acceptance evidence and main risk |
|---|---|---|---|
| Human-entered Idea Repository | **APPLY NOW** | Use project creation plus source/script/project metadata as a single-operator idea inbox; do not create a second truth store. | Create/select/retain an idea-to-project link; Gate A receipt/auditable operator decision. Risk: it is not market research. |
| Automated trend/market research and scoring | **DEFER TO V2** | M9 `OpportunityCandidate`/factual authority after accepted M8 lineage. | Immutable snapshots, freshness, source closure and Gate A. Risk: external-source policy and factual authority are unimplemented. |
| Story writing, drafts and editing | **REDUCE/ADAPT FOR V1** | Accept operator-provided novel/screenplay and Agent-assisted drafts only as project source/candidates; use the existing editor/episode workflow. | A short, complete source-to-script run with human B lock. Risk: no accepted commercial-quality narrative lifecycle/Canon QA yet. |
| Canon/Narrative Library and commercial edition | **DEFER TO V2** | M5C + M6 accepted Canon/Narrative/Adaptation authority. | Append-only lifecycle, review, Canon delta and source-immutable adaptation evidence. Risk: bypassing owner services creates duplicate truth. |
| Factual/explainer video | **APPLY NOW, bounded** | Existing narration, storyboard/reference-video, task queue, composition/export. Prefer a short script with operator-owned factual review. | One 60--180s rendered/exported video, readable audio/captions where selected, replayable project and Gate C. Risk: no automated factual verification. |
| Narrative/drama short video | **APPLY NOW, bounded** | Existing novel/screenplay source, character/scene/prop assets, episode/shot workflow and reference-video/storyboard modes. | One short scene with two named characters/assets, reviewable continuity and Gate B/C. Risk: commercial narrative quality and cross-episode Canon continuity are not proven. |
| Long work -> episodes/shorts/trailer/teaser | **REDUCE/ADAPT FOR V1** | Derive each deliverable as an explicitly created project/episode/export; record source and selected asset/version refs. | At least one parent source yielding one main clip plus one manually selected derivative. Risk: no first-class one-to-many product lineage. |
| Media Asset / Production repositories | **APPLY NOW** | ArcReel project filesystem, manifest/version history and host task state are the repositories. | Restore/reopen a completed project and resolve selected media; no shadow registry. Risk: backup/recovery must be drilled. |
| QA/Evaluate | **REDUCE/ADAPT FOR V1** | Operator checklist at Gate B/C and host workflow blockers; do not call it an independent Quality Authority. | Signed/checklisted decision attached to project release evidence. Risk: model/independent assessor evidence is M10 work. |
| Publish / schedule YouTube or TikTok | **DEFER TO V2** | V1 exports a deliverable; operator uploads manually after Gate D. M11 owns future delivery authority. | For V1: exact export digest, manual external publication record. Risk: automated upload has irreversible network/reconciliation/credential scope. |
| Analytics -> learning | **DEFER TO V2** | Manual notes may inform an operator but have no authority; M12 later consumes M11 lineage. | M12 acceptance, consent/custody, observation/recommendation lifecycle. Risk: a dashboard or score becomes shadow learning truth. |
| Many concurrent pipelines / portfolio scheduler | **DEFER TO V2** | V1 may run existing independent host tasks/projects under documented operator capacity limits; no new PipelineRun authority. | Exact isolation/retry/cancel/resource accounting design and tests. Risk: a new scheduler silently becomes a second runtime authority. |
| Shared repositories across pipelines | **REDUCE/ADAPT FOR V1** | Treat existing project/asset/task/version stores as shared read/write seams under their existing owners. | Cross-project reuse and authorization test; no duplicate Canon/analytics database. |
| Four mandatory Human Gates | **APPLY NOW** | A/B/C/D are operator checklists/receipts bound to exact project/source/script/export version. No auto-approval. | Evidence that a drifted source/script/master invalidates the previous decision. Risk: a UI button/fixture claimed as authority. |

## 4. V1 product slice and non-promises

### V1 promise

For one operator on one self-hosted instance, V1 releases a reproducible,
operator-governed path:

```text
idea or supplied factual/narrative source
 -> A: choose project
 -> source/script + assets
 -> B: lock chosen script
 -> storyboard or reference-video generation + narration
 -> compose / selectable version / export
 -> C: approve final cut
 -> D: approve manual external release
 -> archive project, evidence and deliverable
```

The initial acceptance corpus should contain two small but real products: (1)
a 60--180 second factual/explainer, and (2) a 60--120 second narrative/drama
scene. Both must prove the artifact is meaningful media, rather than a coloured
fixture: visible selected media/graphics, intelligible selected audio or an
explicit mute decision, duration, opening playback, selected version, export
digest, and post-restart reopen/preview. The factual product uses operator
source review; it does not assert automatic claim verification.

### V1 deliberately does not promise

No autonomous trend mining, commercial-quality long-form novel generation,
accepted full Canon lifecycle, automatic public upload/scheduling, analytics
acquisition/optimization, portfolio-wide pipeline orchestration, multi-tenant
operation, or provider-agnostic production claims. V1 also does not claim
`PRODUCTION_CANDIDATE` until M7's execution/recovery/provider qualification
evidence is actually accepted; R2.5 calls execution identity a production
blocker [R2.5:56-127](../r2/R2_05_FROZEN_HOST_HARDENING_REQUIREMENTS.md#L56-L127).

## 5. Safe sequencing and gates

### P0 — establish the releasable line before feature expansion

1. Freeze a clean integration candidate from `r2/main` only after recording
   exact parent SHA, dirty-path disposition and migration head. Do not merge
   from the dirty documentation checkout.
2. Re-review M5C `43ec287a` and M6 `814761e3` against their acceptance packets;
   merge only one at a time after clean-tree, migration, targeted + affected
   suite, contract, browser and independent review evidence. Their human
   overrides must be read as evidence, not as an automatic merge right.
3. Finish M7 from `fd976115` by first adding its untracked files deliberately,
   then validating ADR-0078/H1 semantics on the merged base. A lost provider
   response must remain reconciled/fail-closed, never blind retried.
4. Close the existing M3 content acceptance gap with the two V1 products; do
   not substitute a successful unit suite for rendered artefact evidence.
5. Perform an operator recovery drill: restore a clean database/media target,
   open each selected project/master and record the result. ADR-0078 requires
   database and media inventory together [ADR-0078:72-79](../adr/0078-durable-execution-evidence-and-recoverable-production-boundaries.md#L72-L79).

**Gate:** any failed M5C/M6/M7 acceptance, unresolved execution identity,
unqualified provider, migration conflict, or failed media restore stops release
work and returns to the owning packet; it does not get papered over by V1.

### P1 — V1 release candidate

6. Add the smallest operator-facing Gate A--D receipt/checklist surface needed
to bind exact source/script/export selections. It must be a host extension, not
a new R2 governance database.
7. Run the two corpus products through the exact release candidate; verify
manual recovery/reopen, export and operator acceptance.
8. Tag a V1 release only with a clean worktree, exact migration/Alembic head,
qualified provider configuration references (not secrets), backup-set identity,
runbook and current test/browser/evidence outputs.

### P2 — begin V2 only after V1 is stable

9. Create V2 from the V1 **annotated release tag**, not a directory copy.
   Preserve V1 as its own maintenance branch. Create a tested V2 migration
   baseline from a verified V1 database backup plus checksum media inventory;
   restore it into an isolated staging target before any schema evolution.
10. Continue to merge upstream/security fixes by cherry-picking or merging
    through a pinned compatibility candidate into both V1 maintenance and V2,
    then run migration rehearsal and V1/V2 regression evidence. ADR-0078
    already requires pinned compatibility, rehearsal and fault tests for host
    changes [ADR-0078:99-105](../adr/0078-durable-execution-evidence-and-recoverable-production-boundaries.md#L99-L105).
11. In V2, introduce only one new authority packet at a time in the accepted
   dependency order: M5C/M6 completion if not already in V1, then M8, M9,
   M10, M11, M12. The multi-pipeline portfolio control-plane proposal follows
   only once these owners and their exact receipts exist; it must reference,
   not copy, their state.

## 6. Definition of V1 done and V2 trigger

### V1 done

V1 is done only when all are true on one tagged clean lineage:

1. Single operator can create/open a project, provide source/script and assets,
   and independently produce both corpus slices.
2. Both outputs satisfy the stated playback/audio/visible-content/export and
   selected-version evidence; each has an exact A/B/C/D operator record.
3. Task duplicate/restart behavior is proven for every enabled paid provider
   route, or the route is disabled; no ambiguous outcome becomes automatic retry.
4. Database plus media backup restoration is drilled into a clean target and
   proves project/master resolvability.
5. Required affected tests, static checks, migration rehearsal and browser
   workflow checks actually pass at the release SHA; no previous green result is
   reused as acceptance.
6. V1 documentation truthfully lists disabled automation and manual Gate-D
   publication.

### Trigger for V2

Begin V2 only after V1 has a release tag, verified backup/migration baseline,
one observed stable operator release cycle, and a prioritized evidence-backed
gap that V1's existing project/task/asset authority cannot safely represent.
The first V2 design review must decide whether `PipelineRun` is a host runtime
projection or a new authoritative aggregate; it may not be smuggled in as a UI
or scheduler convenience.

## 7. Proposed backlog

| Priority | Work | Exit condition |
|---|---|---|
| P0 | Integrate/accept M5C, M6, M7 safely; resolve M3 media-product gap | Clean exact lineage and owner-specific acceptance evidence. |
| P0 | V1 two-product corpus, four operator gates, export + recovery drill | Definition of V1 done above is satisfied. |
| P1 | Release/tag/runbook/backup baseline and V1 maintenance policy | A restorable tagged V1 is reproducible on a clean target. |
| P1 | V2 research: portfolio identity, capacity, pause/resume and repository projections | Accepted ADR/spec only after V1 evidence identifies the gap. |
| P2 | M9 opportunity research, M10 independent quality/package, M11 governed delivery, M12 learning | Each starts only from accepted predecessor implementation, per ADR-0080. |
| P2 | Autonomous/concurrent pipeline automation | Only after durable identity, resource isolation and the four mandatory human gates are proven end-to-end. |

## 8. Conclusion

The fastest credible route to a real product is not to import the complete R2
roadmap into the running host. It is to close production and recovery truth in
the host, ship a narrow two-product V1 with human governance and manual
publication, preserve an exact recovery baseline, then evolve V2 from that
lineage. This keeps the requested multi-pipeline OS as the destination without
making it a condition for the first operator to create and deliver useful media.

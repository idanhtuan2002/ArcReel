# R2 V1 Production Release and V2 Evolution Strategy

**Status:** ACCEPTED

**Decision:** [ADR-0089](../adr/0089-ship-a-bounded-v1-before-v2-portfolio-automation.md)

**Research basis:** [V1 production readiness and V2 deferment](../research/2026-09-17-r2-v1-production-readiness-v2-deferment.md)

## 1. Purpose and authority

This post-freeze supplement defines release sequencing. The frozen R2.1--R2.6
architecture, ownership, contracts, hardening requirements and milestone
dependencies remain in force. This supplement neither rewrites their registries
nor converts a proposed or unfinished packet into accepted implementation.

## 2. V1 product contract

V1 is a single-operator, self-hosted production release. On one exact release
lineage, the operator can:

```text
idea or supplied factual/narrative source
 -> A: Greenlight
 -> source/script and assets
 -> B: Narrative Lock
 -> storyboard or reference-video production and narration
 -> composition, version selection and export
 -> C: Final Cut
 -> D: Publish Approval
 -> manual external publication and archive
```

V1 must produce both of these as playable, meaningful media:

1. one 60--180 second factual/explainer with operator-reviewed source/script;
2. one 60--120 second narrative/drama scene with at least two named characters
   or explicitly selected narrative assets.

Each product must retain selected source/script/master identities, visible media
or graphics, intelligible selected audio or an explicit mute decision, duration,
successful playback, export digest and post-restart reopen/preview evidence.

## 3. Mandatory Human Gates

All four gates require an explicit human decision. A gate receipt binds the
exact project plus the input/artifact revision being approved; changing that
revision invalidates the affected approval.

| Gate | Minimum binding | Required before |
|---|---|---|
| A — Greenlight | project plus exact idea/source selection | development |
| B — Narrative Lock | exact source and script revision | production |
| C — Final Cut | exact selected master/export candidate | release packaging |
| D — Publish Approval | exact deliverable, platform intent and visibility | manual external publication |

Agents may prepare gate evidence and recommendations. They cannot issue an
approval. In V1, Gate D does not claim that ArcReel uploaded or scheduled the
content and does not produce a platform delivery receipt.

## 4. V1 non-promises

V1 does not promise autonomous trend research, commercial long-form narrative
generation, a fully accepted Canon lifecycle, portfolio-wide scheduling,
automatic YouTube/TikTok upload, analytics acquisition, automatic learning,
multi-tenant operation or provider-agnostic execution. A disabled or manually
operated capability must be shown as such in product and operator documentation.

Existing project, artifact, version, task and media stores remain the shared
repositories for V1. No shadow workflow, Canon, distribution or analytics truth
store may be introduced to make a deferred capability appear complete.

## 5. Ordered delivery backlog

### P0 — establish one releasable lineage

1. Record a clean integration candidate with exact parent SHA, migration head
   and disposition of every dirty path.
2. Re-review and integrate M5C and M6, one at a time, against their exact
   acceptance packets and the resulting lineage.
3. Finish M7 execution identity, idempotency, ambiguous-response reconciliation
   and provider qualification; disable any unqualified paid route.
4. Close the M3 real-media product gap using the two V1 corpus products.
5. Restore database and media inventory into a clean target and prove that both
   selected projects and masters remain resolvable and playable.

Any failed owner acceptance, migration conflict, unresolved execution identity,
unqualified enabled provider or failed restore stops the V1 release candidate.

### P1 — productize and release V1

6. Add the smallest host-owned A--D receipt and operator-control surface that
   binds exact revisions without creating a new governance database.
7. Run both products end to end on the release candidate, including restart,
   reopen, preview, export and all four gates.
8. Run the affected code, static, migration and browser gates at the exact
   candidate SHA; historical results are not acceptance.
9. Produce operator runbook, disabled-capability disclosure, backup identity,
   checksum media inventory and recovery record.
10. Create an annotated V1 release tag only from a clean worktree.

### P2 — open V2 from the release baseline

11. Preserve a V1 maintenance line and create V2 from the annotated V1 tag.
12. Restore the tagged V1 database and media baseline into isolated V2 staging,
    verify it, then rehearse each schema evolution.
13. Research and decide whether `PipelineRun` is a host runtime projection or a
    new authoritative aggregate before implementing a portfolio control plane.
14. Introduce deferred R2 authorities only in accepted dependency order, with
    no more than one new authority packet under acceptance at a time.

## 6. V1 release gate

V1 is complete only when all conditions below hold on the same clean tagged
lineage:

- both real product slices pass the media and restart/reopen criteria;
- every product has valid A, B, C and D human decisions bound to exact revisions;
- enabled paid routes prove duplicate/restart and ambiguous-outcome behavior;
- database plus media restore succeeds into a clean target;
- applicable M5C/M6/M7 owner packets and host gates pass on the integrated SHA;
- the release includes current run, backup, recovery and manual-publication
  instructions and truthfully identifies deferred automation.

## 7. V2 start gate

V2 may start only after:

1. the V1 release gate is complete and the annotated tag exists;
2. the backup/migration/media baseline has been restored and verified;
3. one stable operator release cycle has been observed; and
4. an evidence-backed gap cannot be represented safely by an existing project,
   task, artifact or asset owner.

The first V2 packet addresses portfolio identity, resource isolation,
pause/resume/cancel semantics and repository projections. Automated discovery,
quality authority, delivery and learning continue through their established
M9--M12 dependency packets rather than a cross-cutting shortcut.

## 8. Relationship to the North Star

The North Star remains `Discover -> Create -> Produce -> Publish -> Measure ->
Learn -> Discover again`, with independent concurrent pipelines and shared
logical repositories. V1 proves the production kernel and human-governed
release boundary. V2 expands concurrency and closes the external feedback loop
from the exact V1 operational baseline.

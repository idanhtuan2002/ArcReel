---
status: accepted
date: 2026-09-17
---

# Ship a bounded V1 before V2 portfolio automation

## Context

The product North Star is a continuously operating Content & Narrative
Production OS: discover, create, produce, publish, measure and learn across many
independent pipelines. The current ArcReel host already has useful production
and export surfaces, while several R2 authority packets and their integration
lineage are unfinished or not accepted. Treating the whole North Star as the
first release would make a real product depend on unproven discovery,
distribution, analytics and portfolio-control authorities.

The evidence and apply/adapt/defer analysis are recorded in
[`2026-09-17-r2-v1-production-readiness-v2-deferment.md`](../research/2026-09-17-r2-v1-production-readiness-v2-deferment.md).

## Decision

1. **V1 is a bounded, single-operator production release.** It must let one
   self-hosted operator create or open a project, provide an idea or source,
   develop and lock a script, produce real media, select a final master, export
   a playable deliverable, and retain enough project, task, version and recovery
   evidence to continue safely.
2. **V1 proves two real product slices:** a 60--180 second factual/explainer
   and a 60--120 second narrative/drama scene. Metadata-only fixtures and green
   unit tests are not substitutes for playable product evidence.
3. **Human Gates A--D remain mandatory:** A Greenlight, B Narrative Lock,
   C Final Cut and D Publish Approval. Every decision binds the exact relevant
   project and artifact revision. Automation may prepare evidence or a proposed
   decision; it may not approve a gate. A material revision invalidates the
   affected prior approval.
4. **V1 stops at controlled export.** Gate D authorizes the operator to publish
   the exact approved deliverable manually outside ArcReel. It is neither a
   platform-delivery receipt nor permission for ArcReel to upload, schedule or
   reconcile a public release.
5. **V1 reuses existing owners.** Project, artifact, version, task and media
   state remain with their current host authorities. V1 must not introduce a
   second workflow engine, portfolio scheduler, Canon store, distribution truth
   store or analytics truth store to simulate the North Star.
6. **V1 is not releasable until production truth is closed.** Its exact clean
   lineage must satisfy the applicable M5C/M6/M7 integration and acceptance
   gates, close the real-media product gap, qualify or disable each paid
   provider path, prove restart/ambiguous-outcome behavior, and complete a
   database-plus-media restore drill.
7. **V2 starts from a released identity, not a directory copy.** It begins only
   after an annotated V1 release tag, a verified database/media recovery
   baseline, and one observed stable operator release cycle. V1 receives its
   own maintenance line; V2 branches or forks from the exact tag and rehearses
   restoration into an isolated target before schema evolution.
8. **V2 owns deferred expansion.** Automated opportunity research, commercial
   long-form narrative authority, portfolio-wide multi-pipeline orchestration,
   automatic platform delivery, analytics acquisition and governed learning
   remain V2 work. Each authority enters through its accepted dependency packet,
   one at a time; a dashboard or scheduler may not become shadow authority.

This decision sequences delivery; it does not retract the frozen R2 North Star,
weaken an existing milestone's acceptance contract, or mark any unfinished
milestone accepted.

## Human Gate identities

| Gate | Decision binds | V1 effect |
|---|---|---|
| A — Greenlight | exact project/idea/source selection | permits development work |
| B — Narrative Lock | exact source and script revision | permits production from that revision |
| C — Final Cut | exact selected master/export candidate | permits release packaging |
| D — Publish Approval | exact deliverable, intended platform and visibility | permits manual external publication only |

## Rejected alternatives

- **Build the full multi-pipeline closed loop before shipping:** rejected because
  it couples the first useful product to unfinished high-risk authorities.
- **Call the current host V1 without real products and recovery evidence:**
  rejected because installed surfaces and historical green tests do not prove a
  stable production release.
- **Auto-approve B or C at high confidence:** rejected because the sponsor keeps
  all four Human Gates mandatory. This supersedes the optional B/C auto-approval
  suggestion in the non-authoritative origin vision.
- **Copy the working directory to make V2:** rejected because it loses exact
  source, migration, database and media lineage.
- **Add a new V1 scheduler or repository abstraction:** rejected because the
  current host owners should be reused until evidence demonstrates a missing
  authority that cannot be represented safely.

## Consequences

V1 delivers less automation than the North Star but establishes an operable,
restorable product baseline sooner. External publication and performance
feedback are manual in V1. V2 work cannot begin merely because V1 can render a
video: it requires the exact release and recovery trigger above.

The normative release checklist and backlog are recorded in
[`R2_V1_PRODUCTION_RELEASE_STRATEGY.md`](../r2/R2_V1_PRODUCTION_RELEASE_STRATEGY.md).

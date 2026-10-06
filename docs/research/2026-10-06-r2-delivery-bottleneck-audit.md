# R2 delivery bottleneck audit

**Date:** 2026-10-06
**Scope:** evidence in the frozen R2 roadmap, accepted-packet records, the M8-C
handoff, issue-tracker convention, and live Git worktree inventory. This is an
audit of delivery evidence, not a release or architecture decision.

## Executive finding

The evidence does not support the conclusion that nothing has been delivered.
M8-A and M8-B have accepted packets, and M8-C has real schema, repository and
transaction-service increments. The slow visible progress comes from treating
many internal custody and authority increments as separate completion points
while the end-to-end consumer remains deliberately closed. The strongest
current evidence is therefore **implemented-unaccepted**, rather than an
approved user workflow.

This follows the frozen roadmap's deliberate rule: deliver vertical milestones
with explicit exit gates, regression tests and preserved authority boundaries,
rather than wholesale donor merging [R2_06_FROZEN_IMPLEMENTATION_ROADMAP.md:12-21].
The same roadmap places M8 after M0 through M7 and describes it as work after
both Golden workflows are stable [R2_06_FROZEN_IMPLEMENTATION_ROADMAP.md:239-255,
259-281]. Any decision to shorten that sequence needs an explicit milestone-gate
approval under the roadmap; this audit found no such approval in the sources
examined.

## Status separated by evidence class

| Area | Evidence class | What the evidence establishes | What it does not establish |
| --- | --- | --- | --- |
| M8-A exploration/promotion | **Accepted** | The acceptance record names `215d18e0` and records zero blocking findings [R2_M8_A_IMPLEMENTATION_ACCEPTANCE.json:3-10, 27-43]. | General M8-C readiness or production activation. |
| M8-B Creative Canvas | **Accepted** | The acceptance record names `488a183a`; its eighth review round has zero blocking findings [R2_M8_B_IMPLEMENTATION_ACCEPTANCE.json:3-9, 103-114]. | That every later packet inherited its quality gates. |
| M8-C pair schema/repository/service | **Implemented, unaccepted** | A real PostgreSQL FK-backed repository path passed 1/1 [R2_M8C_FRAME_CUSTODY_HANDOFF.md:229-233]. The transaction service verifies target, binding, receipt and parent state and has a deny-by-default authorization port [R2_M8C_FRAME_CUSTODY_HANDOFF.md:235-239]. | A production APPROVE decision, a public route, READY consumption, promotion or generation routing [R2_M8C_FRAME_CUSTODY_HANDOFF.md:241-241]. |
| Pair admission design | **Proposed** | The handoff describes the design packet as a proposal and records synthetic placeholder authorization/evidence digests [R2_M8C_FRAME_CUSTODY_HANDOFF.md:197-203]. | A trusted project-scoped Showrunner grant or proof that a reviewer saw the exact two frame bytes. |
| Whole-project/release state | **Unknown / not accepted** | The current M8-C handoff says the earlier full backend suite is red and was not rerun or fully triaged [R2_M8C_FRAME_CUSTODY_HANDOFF.md:215-219, 241-241]. | Whether all failures are caused by current work, and the status of worktrees not reviewed in this audit. |

## Evidence-backed delivery bottlenecks

1. **The first usable M8-C outcome is gated behind several unfinished authority
   prerequisites.** The service is intentionally closed because its only
   successful authorization is a test fake; the project-scoped grant, exact
   visual-review proof, forced PostgreSQL interleavings, withdrawal consumer
   and independent exact-HEAD review remain open
   [R2_M8C_FRAME_CUSTODY_HANDOFF.md:241-241]. This is the direct reason that
   internal progress does not yet appear as a user-facing READY flow.

2. **Review/remediation cycles consume a material share of a packet's lead
   time.** M8-B records eight review rounds before acceptance; the first seven
   had one to five blocking findings [R2_M8_B_IMPLEMENTATION_ACCEPTANCE.json:10-114].
   This supports a conclusion about rework in that packet only; it does not
   prove the same rate for every milestone.

3. **The active work is in a late, advanced milestone whose exit is broader
   than the immediate feature.** M8 explicitly includes canvas, promotion,
   spatial experiments, analytics, learning and extra formats, with an exit
   requiring no authority violation and measurable utility
   [R2_06_FROZEN_IMPLEMENTATION_ROADMAP.md:239-255]. The frozen order makes
   it dependent on all earlier milestones unless explicitly approved otherwise
   [R2_06_FROZEN_IMPLEMENTATION_ROADMAP.md:259-281]. This increases integration
   and acceptance work even where donor code exists.

4. **Work ownership and evidence are split across parallel worktrees.** The
   M8-C handoff explicitly says the separate C1 worktree had eight dirty or
   untracked paths and must be preserved [R2_M8C_FRAME_CUSTODY_HANDOFF.md:215-217].
   The live worktree inventory on 2026-10-06 showed separate M8-A, M8-B,
   M8-C, M8-C binding-design and V2-main heads. This is useful isolation, but
   it means a green packet in one worktree is not automatically an integrated
   release candidate.

5. **The project has issue-tracking conventions, but this audit found no
   linked delivery map in the inspected handoffs.** The convention requires a
   parent Spec, visible child-issue ownership, native sub-issues and blockers
   [docs/agents/issue-tracker.md:16-38, 53-62]. I did not query GitHub, so the
   existence and current assignment state of such issues is **unknown**. The
   evidence gap prevents a reliable statement of the critical-path owner and
   remaining duration from repository documents alone.

## Boundaries of this audit

- No source code, migrations, tests, provider calls or live databases were
  changed.
- The M8-C handoff is at `f0b30ac9`; it is a current checkpoint, not an
  independent acceptance record.
- Git worktree state is time-sensitive. The inventory observation above was
  made with `git worktree list --porcelain` on 2026-10-06 and should be
  refreshed before making an integration decision.

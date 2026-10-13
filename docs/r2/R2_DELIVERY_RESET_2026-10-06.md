# R2 delivery reset — 2026-10-06

**Status:** execution proposal for the current V2 lineage. This document changes
the delivery workflow, not the frozen architecture, authority contracts, release
gates, or sponsor decisions. The [source audit](../research/2026-10-06-r2-delivery-bottleneck-audit.md)
records the evidence and its limits.

## Why delivery feels slow

There is real progress, but too much of it ends at an internal packet boundary.
The frozen roadmap requires **executable vertical milestones**; it does not
define a donor merge as completion
([roadmap](R2_06_FROZEN_IMPLEMENTATION_ROADMAP.md), section 1). Broad donor
research was already closed at freeze; new research is limited to a specific
unresolved gap ([freeze index](00_R2_FREEZE_INDEX.md)). Reopening the same broad
comparison or reviewing a moving branch repeatedly adds time without creating
a runnable result.

The V1 lineage reached `PRODUCTION_CANDIDATE`, with a sponsor-accepted gate
exception; it is not described as `PRODUCTION_APPROVED`
([candidate dossier](evidence/R2_V1_PRODUCTION_CANDIDATE_2026-09-28.md)). The
sponsor nevertheless recorded a V2 start decision and a restored staging
baseline ([decision](evidence/R2_V2_START_DECISION_2026-09-29.json),
[baseline](evidence/R2_V2_00_STAGING_BASELINE_2026-09-29.md)). Thus both the
working V1 product and its remaining release limits must stay visible.

At the 2026-10-06 local snapshot, `r2-v2/main` was clean at
`8d4328d63f98bd8bf6e3baf02cbb05ad98300f37`. M8-A and M8-B had acceptance
records and were in that main lineage. The M8-C frame-receipt branch was clean
at `f0b30ac9`, descended from main, and 145 commits ahead of it. That count is
a Git distance, not a measure of completed features. The separate M8-C spatial
branch shared the `774952b2` ancestor and had eight dirty or untracked paths.
The checkout inventory contained 20 worktrees; it does not establish that 20
tasks are active. M8-C frame custody has implementation and focused evidence,
but lacks production grant, review-byte custody, approved reader, READY
consumption, promotion and exact-HEAD acceptance
(`R2_M8C_FRAME_CUSTODY_HANDOFF.md` at `f0b30ac9` in the separate pair
worktree; see the [source audit](../research/2026-10-06-r2-delivery-bottleneck-audit.md)).
These are snapshots, not permanent branch status.

## Operating rule: one integrated result at a time

The delivery unit is a **thin, runnable user path** on one clean integration
SHA. A document, interface, internal service, or green test on a side branch is
progress, but is not a delivered slice. Use `r2-v2/main` as the V2 integration
line and record the exact branch SHA at each gate. Preserve unrelated dirty
worktrees; do not reset, clean, or silently absorb them.

Keep only **one new authority packet under acceptance** at a time, as the
[accepted V1/V2 strategy](R2_V1_PRODUCTION_RELEASE_STRATEGY.md) already requires.
Keep one M8-C integration candidate in focus. Other branches may retain work,
but a second candidate does not enter review until the current one is accepted,
rejected with a named repair, or explicitly parked. This is a review queue, not
an instruction to discard parallel research or existing work.

For each slice, record on the tracking issue or in the handoff:

1. One observable outcome and its demo/fixture, including what remains disabled.
2. Existing donor/module to reuse, pinned source revision, and the exact
   authority or data seam to bridge. Research only an observed unresolved seam.
3. Owner, target integration branch/SHA, dependency, and one current blocker.
4. The smallest relevant tests plus the acceptance/release gates that apply.
5. The next integration action and its due decision, not a speculative list of
   later capabilities.

GitHub Issues are the canonical tracker by
[project convention](../agents/issue-tracker.md). The live issue state was
unavailable during this reset, so ownership and due dates are **unknown** until
the tracker can be read. Do not invent issue status from documents.

## The execution loop

| Point | Required output | Stop condition |
| --- | --- | --- |
| Select | One user path, pinned donor/reuse map, exact starting SHA, acceptance example | If it cannot be demonstrated, split or narrow the path before coding. |
| Implement | Small changes on the selected branch; targeted tests after each behavioral change | A new authority or public contract seam returns to main-agent design review. |
| Integrate | Rebase/merge in dependency order into one clean candidate; run the path against real persisted data and bytes | A branch-only green result cannot enter acceptance. |
| Accept | Affected static/tests, real PostgreSQL or media checks where the risk requires them, independent exact-SHA review for authority work, recorded exceptions | A blocker gets one owner and a reproducer; fix it, then rerun only the affected checks and final required gate. |
| Release | Full required domain gates, restore/reopen and operator/product evidence on the release SHA | No production or paid activation from an implementation or focused-test result. |

During implementation, use the test selection in `CONTRIBUTING.md`; an empty
selection must be widened. At completion, run the affected-domain full gates
required by `AGENTS.md`. Do not rerun an unchanged full suite or repeat an
independent review without a concrete failed gate, changed SHA, or release
boundary. Do not waive a required gate to improve throughput; record an
explicit sponsor exception when one is authorized.

**Definition of done for a slice:** a clean integrated SHA; the named user path
runs end to end with its real storage and representative artifact; relevant
checks pass on that SHA; authority/revision ownership is visible; every
remaining disabled capability is stated; and the tracker/handoff points to the
evidence. Use `implemented`, `integration candidate`, `accepted`, and
`released` as separate states.

## First application: finish a narrow M8-C path

The next candidate should make **one reviewed pair of exact frames usable by
one downstream readiness consumer** in an offline/local workflow. Keep paid
providers, live production approval, and release routing closed until their
own gates pass. This is a proposed delivery cut, not an assertion that the
current pair code already provides it.

1. Preserve the eight dirty/untracked spatial paths as a separate work item;
   capture its HEAD and intended acceptance surface. Do not mix them into the
   pair branch to make a green snapshot.
2. On the clean pair branch, close the trusted project-scoped grant and proof
   that the reviewer saw the two exact frame bytes. Add the current approved
   reader and withdrawal behavior. Verify transaction interleavings in real
   PostgreSQL, then perform one exact-HEAD independent review.
3. Integrate the accepted pair path into `r2-v2/main`. Connect only the minimum
   production binding/promotion and readiness consumer needed for one offline
   scenario; show invalidation when either frame or approval changes.
4. Reconcile the spatial branch after its own targeted checks and clear
   acceptance result. Advance to M8-D or other advanced features only after
   the selected M8-C vertical result is integrated and demonstrated.

The proposed path's full authority shape must be checked against the accepted
M8-C contract before implementation. A route, READY signal, or promotion must
not be enabled merely to complete the demo. If this cut conflicts with an
accepted dependency, stop at that specific seam and record a bounded decision.

## Control without more ceremony

- **Daily:** report the current integrated SHA, one active slice, its next
  observable result, and the oldest blocker. Update the existing issue or
  handoff; no new status document for each small change.
- **Twice per week:** inspect elapsed time since the last integrated runnable
  slice, age of the oldest blocker, open acceptance candidates, and the red
  gate list. If a slice has made no integrable progress for two working days,
  narrow it or decide the blocking seam explicitly. This is a trigger to act,
  not a promise that every slice finishes in two days.
- **At each acceptance:** record exact SHA, commands/results, reviewer decision,
  disabled capabilities, and next dependency in one durable evidence record.
  An ADR is needed only for a genuine authority, public-contract, or
  architectural decision.
- **Before a session ends:** leave a short handoff only when work is unfinished
  or the context is about to be lost: HEAD, dirty paths, result, remaining gate,
  and first resume command. Continue from live Git state next time.

The first baseline metrics are the snapshot above. The operating targets are
one acceptance candidate at a time, no unexplained dirty path on an integration
SHA, and at least one executable end-to-end example for each claimed vertical
milestone. Report cycle time from selection to integration and the blocker age;
do not use commit count, review count, or document count as a proxy for user
value.

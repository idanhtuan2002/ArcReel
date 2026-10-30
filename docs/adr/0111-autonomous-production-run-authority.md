---
status: accepted
---

# Production automation delegates decisions to an explicit run-scoped actor

The sponsor approved the autonomous/semi-automatic design on 2026-10-30 and instructed implementation without routine approval prompts. A new production run defaults to automatic execution; semi mode pauses at the selected narrative-package and final-film checkpoints. Backend orchestration reuses existing Story, Canon/Plan/adaptation, queue, master and Quality owners instead of relying on an open Agent session or introducing another provider queue.

For a qualified run, a current project Showrunner may delegate only operations they possess to a distinct automation principal, bounded by the exact run, policy, inputs, routes and budget. Automatic decisions retain their actual actor, grant and evidence. They are never serialized as Human approvals or used to satisfy a Human-required assessment slot. Parent/child revocation and owner-head currentness are checked at the authoritative transaction. Runtime automation may use an approved Quality profile; it cannot publish a weaker one, waive critical findings or accept blocking narrative exceptions.

This prospectively amends ADR-0089's mandatory manual A/B/C and associated narrative decision touchpoints only for explicitly delegated, qualified production runs. Existing Human contracts, receipts and manually operated projects retain their meaning; no historical project starts automatically. Gate D/publication is unchanged. A failed or unknown outcome remains blocked/failed, rather than becoming a successful film by permission alone.

Acceptance of this design does not activate a production capability. Activation requires the versioned authority adapters, durable recovery, qualified assessors, native renderer and end-to-end acceptance defined in the [design](../superpowers/specs/2026-10-30-autonomous-production-workflow-design.md) and [plan](../superpowers/plans/2026-10-30-autonomous-production-workflow.md).

The versioned `DELEGATE_AUTOMATION` entitlement is assigned only to a current signed project `HUMAN_SHOWRUNNER` through the activated Governance custodian. Its fixed operation namespace is BRIEF, STORY, STORY_COMMIT, HANDOFF, EPISODE_PLAN, SCRIPT_PLAN, SCRIPT, ASSET_ANALYSIS, MEDIA, RENDER, MASTER, QUALITY, PACKAGE and EXPORT. Each owner retains its content/evidence prerequisites; the namespace does not delegate profile publication, narrative exceptions, WAIVE or Gate D. App administration, API keys and embedded sessions do not establish this entitlement.

Delegations are separate append-only child records with a versioned head, exact Start command, parent event reference and frozen input/policy digest. Owner authorizations bind a staged canonical command, current run version/generation/stage, exact subject and active worker lease. Lock order is owner heads, signed parent, child head, run and decision; no model/provider operation runs under those locks. Start must lock the parent and create run plus child grant in one transaction. Replays preserve provenance and revalidate current authority before another side effect. Changing mode/policy requires a separately authorized bounded successor; an old child never authorizes the changed policy by inference.

---
status: accepted
---

# Production automation delegates decisions to an explicit run-scoped actor

The sponsor approved the autonomous/semi-automatic design on 2026-10-30 and instructed implementation without routine approval prompts. A new production run defaults to automatic execution; semi mode pauses at the selected narrative-package and final-film checkpoints. Backend orchestration reuses existing Story, Canon/Plan/adaptation, queue, master and Quality owners instead of relying on an open Agent session or introducing another provider queue.

For a qualified run, a current project Showrunner may delegate only operations they possess to a distinct automation principal, bounded by the exact run, policy, inputs, routes and budget. Automatic decisions retain their actual actor, grant and evidence. They are never serialized as Human approvals or used to satisfy a Human-required assessment slot. Parent/child revocation and owner-head currentness are checked at the authoritative transaction. Runtime automation may use an approved Quality profile; it cannot publish a weaker one, waive critical findings or accept blocking narrative exceptions.

This prospectively amends ADR-0089's mandatory manual A/B/C and associated narrative decision touchpoints only for explicitly delegated, qualified production runs. Existing Human contracts, receipts and manually operated projects retain their meaning; no historical project starts automatically. Gate D/publication is unchanged. A failed or unknown outcome remains blocked/failed, rather than becoming a successful film by permission alone.

Acceptance of this design does not activate a production capability. Activation requires the versioned authority adapters, durable recovery, qualified assessors, native renderer and end-to-end acceptance defined in the [design](../superpowers/specs/2026-10-30-autonomous-production-workflow-design.md) and [plan](../superpowers/plans/2026-10-30-autonomous-production-workflow.md).

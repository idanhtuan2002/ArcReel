---
status: accepted
---

# Batch films are launch-qualified like their template

Decided 2026-11-13 by the main agent under the sponsor's instruction to do the re-audit's work items. Research: [workflow re-audit](../research/2026-11-13-r2-workflow-stage-reaudit.md) A3.

A launch qualification is recorded per project (`auto_launch_qualifications`, scope user + project + launch profile) and the preflight refuses a run without one (`LAUNCH_PROFILE_NOT_QUALIFIED`). The film batch of [ADR-0124](0124-projects-run-on-autopilot-under-a-standing-delegation.md) §6 creates film projects that copy their template's automatic production settings and turns their autopilot on, but nothing recorded their launch qualification, so every batch film's first run would stop under "Needs you" until the Showrunner pressed "record launch" on each project by hand.

1. **The batch records each new film's launch qualification before turning its autopilot on**, through the same `QualificationJobs.record_launch` the run panel's button calls, under the same interactive Showrunner and the same host launch evidence (`ARCREEL_LAUNCH_EVIDENCE`). It is recorded only when the film's real preflight blocks on nothing but the missing record, so a film whose routes, quality profile, reviewers, voice or host resources differ from what qualifies is not qualified by inheritance; nothing is copied from the template's record.
2. **The batch reports why a film was not qualified.** Each created film lists `launch_reasons` (empty when recorded; the preflight's blocking reasons, or `LAUNCH_EVIDENCE_NOT_CONFIGURED`). The film's autopilot is still turned on: its run then stops with those reasons under "Needs you", as before.

Not done here: qualifying a project when its automatic production settings change (the Showrunner records it again, as today).

---
status: accepted
---

# Reviewers are trusted by configuration, as the donors do

Decided 2026-11-23 by the sponsor ("our app takes the best parts and is most like the donors"), option 3 of
[judge qualification options](../research/2026-11-23-r2-judge-qualification-options.md). Supersedes ADR-0167 and the
reviewer-corpus parts of ADR-0113 and ADR-0165.

## Context

No donor qualifies a judge model: DramaClaw @ b299bfd builds its reviewers from one configured model, ViMax's
`best_image_selector.py` calls a VLM without validation, OpenMontage, huohuo-drama and take have none, and AIVPE
@ a368af45 runs Gemini Flash with two guards. Our reviewer corpus was the only judge gate with a recurring cost (a run
over labeled films for every new reviewer model or launch profile: days of GPU and the Gemini free quota), and the
drama qualification failed on mislabeled films, not on the reviewers.

## Decision

1. **No reviewer qualification.** Preflight no longer checks one (`MISSING_QUALIFIED_REVIEWER` is no longer raised).
   The run's two reviewer routes are trusted as configured.
2. **Kept:** two reviewers of distinct models, neither the writer (`REVIEWER_INDEPENDENCE_MISSING`), both accepting; a
   review by any other model blocks (`REVIEWER_NOT_CONFIGURED`). The AIVPE guards: a `CRITICAL` or `MAJOR` finding is
   never accepted; a failed or unparseable review is `ASSESSOR_FAILED`. The deterministic checks.
3. **Evidence.** A MODEL observation names its reviewer with `assessor_qualification_ref = "configured-reviewer-route"`
   and a digest over model identity, route config digest and review-method digest
   (`r2.automation.assessment.configured_reviewer_digest`), recomputed when the evidence is read
   (`server/services/quality_runs.py`) and required to match one of the reviewer routes of the production run that
   recorded it. Observations recorded under a reviewer qualification are still verified
   against it, so earlier runs' packages keep their evidence; the qualification table stays for that.
4. **Removed:** reviewer qualification jobs, their API (`POST …/qualification/reviewers`), `scripts/r2/qualify_reviewers.py`,
   the corpus host settings and the reviewer rows of the run panel's qualification section.
5. **Unchanged:** the image judge (all launch profiles pin the local insightface scorer, qualified once by a committed
   evidence file, no per-run cost), the continuity judge gate (no launch profile enables it; decided again under the
   same principle when one does), media-route probes and the launch record (they prove routes run).

---
status: accepted
---

# A reviewer is admitted by a short smoke check, not a labeled 40-film corpus

Decided 2026-11-22 by the sponsor ("Gọn lại kiểu AIVPE"), after the [donor port audit](../research/2026-11-22-r2-donor-port-audit.md) found that reviewer qualification is our own mechanism: no donor gates a model by qualification (ADR-0113 records this), and AIVPE runs a Gemini Flash judge directly with two guards. The labeled corpora (ADR-0113, ADR-0134, ADR-0165, the drama corpus of 2026-11-16..22) cost days of GPU time and the Gemini free quota. Drama qualification failed twice on defects in the corpus itself (a drifting dog in a "clean" film; an audio/subtitle mismatch of unknown cause), not on the reviewers.

## Decision

1. **The two AIVPE guards are the runtime safety net, and they already hold.** A review with any `CRITICAL` or `MAJOR` finding is not accepted whatever its scores (`ModelAssessment.accepts`, the counterpart of AIVPE's cap at 69). An unparseable or failed review is `ASSESSOR_FAILED` and blocks the unit; it is never read as a score. Neither changes.
2. **A smoke check replaces the corpus rule for new qualifications.** A corpus manifest marks its smoke cases with `"split": "SMOKE"`: at least three `CRITICAL_DEFECT` films with obvious defects, and at least two `CLEAN` films checked by eye. A reviewer qualifies on a smoke record when every smoke defect is rejected and every smoke clean film is accepted. The check runs in minutes and costs at most a handful of cloud requests.
3. **Every smoke review must be answered.** A smoke review that is not `COMPLETED` ends the job without a record, so a reviewer that cannot answer is never admitted by rejecting everything.
4. **Existing records stay valid.** A record over `CALIBRATION` and `HOLDOUT` splits is still judged by the old rule, so reviewers qualified before this decision keep their status. The qualification job reviews only the smoke cases when the manifest has any.
5. **No new corpus is built by side scripts.** Smoke films come from the existing corpora or from runs of the app itself (AGENTS.md "Donor 整体移植").

## Consequences

- A reviewer that is too lenient on subtle defects can now be admitted. That risk is accepted: the final watch, the per-unit guards and the Showrunner's view of every run remain, and AIVPE ships on the same trade.
- The drama corpus smoke set: defects and clean films are picked from `reviewer-corpus-drama-2026-11-16`, excluding the cases whose labels were in doubt (c02, c05, c07).

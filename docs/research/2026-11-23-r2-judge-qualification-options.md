# Judge qualification: impact of three options

Date: 2026-11-23. Sponsor principle: "the app takes the best parts and is most like the donors". The sponsor asked to
re-research the impact of three options before choosing. Labels: **FACT** (read here, with path), **INFER**.

## Facts

1. **No donor qualifies a judge.** DramaClaw @ b299bfd builds its reviewers from one configured model
   (`agents/episode_reviewer.py:211`, `character_reviewer.py:88`: `get_pydantic_model()`) next to rule checks.
   ViMax `best_image_selector.py` calls a VLM without validation. OpenMontage, huohuo-drama and take: no match for
   judge calibration/qualification (grep 2026-11-23). AIVPE @ a368af45 runs one Gemini Flash judge with two guards
   ([donor mechanisms](2026-11-13-video-quality-donor-mechanisms.md)).
2. **Three gates exist** (`server/production_run/preflight.py`):
   - Reviewer qualification (`MISSING_QUALIFIED_REVIEWER`): a labeled corpus per launch profile and language
     (ADR-0113/0165/0167). **Recurring cost:** every new reviewer model or profile needs a run over films; it took
     days of GPU and the Gemini free quota (20 requests/model/day), and failed twice on mislabeled corpus films
     (ADR-0167 amendment).
   - Image judge (`IMAGE_JUDGE_NOT_QUALIFIED`): all three active launch profiles
     (`r2/automation/launch_profiles/*.json`) pin `insightface/buffalo_l@2.1`, a local face-identity scorer, not an
     LLM, qualified once by a committed evidence file
     (`docs/r2/evidence/face-identity-qualification-2026-11-14/qualification.json`). **Recurring cost: none.**
   - Continuity judge (`CONTINUITY_JUDGE_NOT_QUALIFIED`): enabled in **no** launch profile (`continuity: null`).
     **Recurring cost: none.**
3. **Two reviewers are part of M10's quality contract.** Preflight requires at least two MODEL slots, each with
   `required_independence_groups >= 2` (`preflight.py:214-216`); `combine` requires two completed reviews of distinct
   models, neither the writer (`r2/automation/assessment.py:78`); each observation carries
   `independence_group = "model:<identity>"` (`server/production_run/quality_record.py`).
4. **Reviewer observations cite their qualification.** `quality_record.py` writes the qualification digest into
   each MODEL observation, and `server/services/quality_runs.py:371-380` re-verifies it against
   `ReviewerQualificationRepository` whenever the evidence is read (packaging, export). Old runs' evidence depends on
   it.
5. **A second reviewer has caught a lenient one.** gemma3:4b accepted defect d01 (dialogue from another story) that
   qwen2.5vl rejected; gemini-2.5-flash accepted c06 (baby born a line early) that gemini-3.5-flash rejected
   (tracker `R2_CRAFT_QUALITY_PROGRAM.md`, 2026-11-22).

## Options and impact

| | 1. Remove all three gates, keep two reviewers | 2. Like the donors: one reviewer, no gates | 3. Remove only the reviewer gate |
|---|---|---|---|
| Recurring cost saved | reviewer qualification (all of it) | same + one review per episode | reviewer qualification (all of it) |
| Extra saving vs 3 | none (facts 2: the other two gates cost nothing per run) | half the review requests and GPU minutes | — |
| Quality risk | as 3, plus the face scorer's pinned evidence is no longer checked | one lenient model passes defects with no second opinion (fact 5) | lenient model can pass only if the other one also accepts |
| Contract change | as 3 + judge reasons renamed | M10 independence invariant (fact 3) changed, every published quality profile re-published, `combine` single-review path | MODEL observation attestation (fact 4) with old-run compatibility |
| Code size (INFER) | as 3 + ~3 files | largest: as 1 + M10 contracts, profiles, UI | ~15 backend/frontend files + ~8 tests |
| Donor alignment | closer than 3 on paper | closest | reviewer gate removed, the costly own mechanism |

INFER: the whole recurring cost the sponsor objected to sits in the reviewer gate. Removing the face-scorer and
continuity gates saves nothing per run and removes a check on a deterministic local scorer whose evidence is already
committed. One reviewer halves review calls, but with the free Gemini tier each model has its own 20/day quota, so it
does not raise episodes per day, and it removes the only defence left against a lenient model once qualification is
gone, while forcing an M10 contract change.

## Choice

**Option 3**: remove the reviewer qualification gate only; reviewers are trusted by configuration (as every donor
does), two distinct reviewers and the AIVPE guards stay; the face-scorer evidence pin stays (no recurring cost); the
continuity judge gate stays dormant until a profile enables that judge, when it is decided again under the same
principle.

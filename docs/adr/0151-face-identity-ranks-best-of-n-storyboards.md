---
status: accepted
---

# Face identity ranks best-of-N storyboards

Decided 2026-11-14 by the main agent (identity ID-2 and ID-3).

Best-of-N storyboards (ADR-0112) stayed off because no model judge qualified: local vision models ranked by position or failed the holdout, and cloud judges run on daily free quotas that cannot serve every shot. Identity drift is what the selection most needs to catch.

1. **A deterministic identity scorer.** A local ArcFace server (InsightFace `buffalo_l`, CPU, port 8003) returns the cosine between a character sheet's front-view face (the most confident face in the sheet's left third) and the closest face in a candidate. A candidate's score is the mean over the shot's characters both pictures show; the highest wins; a shot with no scored face keeps its current version. The rule text is the judge's "prompt" and its digest is pinned (`lib/face_identity.FACE_JUDGE_RULE_DIGEST`), the judge identity is `insightface/buffalo_l@2.1`.
2. **Qualified on the continuity corpus.** On corpus 2 (38 right-person frames, 38 look-alike frames, local FLUX.2 klein 4B) it ranks the right person above the look-alike in 36 of 37 pairs (ADR-0112's bar: at most 10 % wrong), AUC 0.885 (`docs/r2/evidence/face-identity-qualification-2026-11-14/`). As a gate it is weak (at cosine 0.29 every look-alike fails but so do 27 % of right frames), so it only ranks.
3. **Wired into the existing selection.** The narration launch profile pins `image_selection` with two candidates and this judge. Preflight accepts it without a reviewer route but requires the face server (`ARCREEL_FACE_ID_URL`); a host without it freezes `image_candidates = 1` in the run's policy instead of blocking runs. MEDIA scores the usable candidates by face and restores the winner, writing every score to `image_selection.json` as before.

The launch profile changes, so each project's launch qualification is stale until its automation settings are saved again (ADR-0139 re-records it on save). Every shot with characters costs one more storyboard generation (about 21 s locally).

---
status: accepted
---

# A trailer is cut from the finished film

Decided 2026-11-15 on the sponsor's catalog (rank 11, trailer / teaser: packaging for every story and film). Donor: OpenMontage `cinematic` pipeline (`pipeline_defs/cinematic.yaml`, `skills/pipelines/cinematic/script-director.md` @ 08e2151): a beat map of hook → escalation → reveal → landing, sparse short title cards, "revealing the best moment too early" named as a failure.

1. **Source**: a succeeded production run's verified finals (`verified_final`: bytes still hash to the run's completed target) and their subtitles. No new picture or voice is generated; the trailer costs one text call per attempt and an ffmpeg cut.
2. **Plan** (the project's script text route, 3 attempts with the problems fed back): a hook line and 2–5 beats chosen by id from the numbered spoken lines (with their place in the story and length), at most two title cards (≤ 40 characters) and an end card line (≤ 70). Checked without the model: ids exist and are distinct; beats in story order; no pick ends after 70% of the story (no spoiler); no pick longer than 10 s or under an episode's next-episode card; the whole trailer lasts 12–45 s.
3. **Cut**: each picked line whole from its episode (start of the line to its end + 0.2 s, 60/150 ms sound fades), so no sentence is cut and the burned caption stays whole; title cards (1.6 s) after the hook and before the last beat over a blurred, darkened still of the film; the end card (2.8 s) shows the film's title over the end line; sound mastered with `loudnorm` I = −14 LUFS like the films.
4. **Records**: `output/trailer/<run_id>/trailer.mp4` and `trailer.json` (plan, cut list, duration). API `POST/GET /projects/{p}/production-runs/{run_id}/trailer`, file at `…/trailer/file`; the run panel offers it once the run succeeded.

Smoke (2026-11-15): a fixed plan cut from a real 26 s episode (staging backup) gave a 30.4 s trailer at −14.2 LUFS with readable cards; the planner's end-to-end run waits for a multi-episode film (a one-episode, three-line film has too few lines before the 70% mark, which the checks refuse as intended).

Not covered: music hit points (the finals' sound is already mixed; no separate stem), new inserts generated for the trailer, a vertical/horizontal reframe.

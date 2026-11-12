---
status: accepted
---

# The film is planned at the voice's pace toward the project's target

Decided 2026-11-13 by the main agent under the sponsor's instruction to do the re-audit's work items ("làm tất cả các công việc mà bạn thấy"). Research: [workflow re-audit](../research/2026-11-13-r2-workflow-stage-reaudit.md) A1, A2.

The only automatic film run after 2026-11-08 came out at 26.1 s against a 45 s target. Three causes, found in code:

- `RunPolicy.target_duration_seconds` (45, from the launch profile, bounded 30–60) was written at run start and read by no stage. The target the planner, adaptation and script prompts actually use is the project's `episode_target_duration` (10–600 s; film looks set 60 or 90).
- Lengths are planned in reading units at `lib/speech_rate.py`'s Vietnamese default of 2.5 words per second. VieNeu v3 turbo, the narration profile's voice, speaks 3.75 words per second: 185 words in 49.3 s of generated segment audio over 7 segments of two real runs (`/var/tmp/ar9b/{off1,dbg3}`, per-segment 3.53–4.01, silence padding included). A 45 s plan therefore reads in about 30 s.
- Films the autopilot makes copied no adaptation setting, so they were read from the story verbatim, the mode ADR-0114 replaces.

1. **One target.** The run's policy freezes the project's `episode_target_duration` at start (`None` when the project sets none); the policy bound becomes the product interval 10–600 s. The launch profile's `target_duration_seconds` stays descriptive metadata of the profile.
2. **The voice's pace is part of the launch profile.** `LaunchProfile.speech_rate_units_per_second` holds the measured rate of the profile's audio route (`fiction_narration_vi_v1`: 3.75). A film the autopilot creates takes it as its project `speech_rate_units_per_second` when its template narrates with that exact route and sets no rate of its own; every planner, adaptation and script prompt already honours that project override. The language default in `lib/speech_rate.py` (upstream) is unchanged: it is not a property of any one voice. A cloud voice gets its rate measured and recorded the same way before its profile is used.
3. **QUALITY reports the length.** Every review adds `CHECK_LENGTH_OFF_TARGET` (MINOR, `SCRIPT_PLAN`) when the final misses the policy's target by more than 20 %, the adaptation's own tolerance. It is MINOR, not a rework: a rework replans with the same speaking rate and source and would come back the same length, burning the evaluation limit. A wrong length means the rate or the adaptation is wrong, and the finding in the run report is what shows it.
4. **Films adapt their story.** The batch copies `episode_adaptation` from the template and defaults it to `screen`; a template that says `verbatim` keeps it. Projects created by hand keep their own setting (default `verbatim`, ADR-0114 §2).

Not done here: measuring the rate after MEDIA and replanning automatically (a second media pass per run for a correction the recorded rate makes once), and a rate per voice for manual projects outside the autopilot (the project setting exists for them).

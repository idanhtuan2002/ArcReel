---
status: accepted
---

# Autopilot draws its own idea and configuration

Decided 2026-11-10 by the main agent under the sponsor's instruction: on autopilot the program does everything itself; with no idea entered it creates one, then configures style, genre, format and length from the idea. Research: [autonomous idea and configuration](../research/2026-11-10-r2-autonomous-idea-and-configuration.md). Builds on [ADR-0124](0124-projects-run-on-autopilot-under-a-standing-delegation.md), [ADR-0119](0119-genre-packs-and-a-bounded-humanizing-repair.md) and [ADR-0121](0121-each-project-chooses-its-content-safety-level.md).

1. **An automatic run names its genre.** The fixed brief genre `truyện ngắn` matched no genre pack, so automatic stories ran without one. A run's genre is a genre pack id chosen as below; the brief carries that pack's label.
2. **The idea is drawn inside the BRIEF stage, not a new stage.** A start command may carry `idea_mode = "auto"` (left out of the stored command at its default) instead of an idea. The BRIEF owner then makes one bounded call on the run's frozen writer route that returns a schema-checked *profile*: the idea, a genre pack id among the ten, a tone, an audience and a book length within 6..120. The profile is stored in the project's story blob store under a key derived from the run before the brief is drafted, and is read back on any replay, so one run records one idea. The brief built from it is what Gate A greenlights, as before. Research option A (a separate `IDEA` stage) was not adopted: BRIEF already turns a command into the greenlit brief under the run's grant, budget and receipts, and a new stage would change the stage enum, the run graph and every stage label for no gain in authority.
3. **Closed choices, decided in code.** Every model-chosen value is validated against a closed set; a value outside it falls back to a recorded default. The model never chooses the content safety level, spending caps, routes or grants: the project's safety level (ADR-0121, default `off` since 2026-11-10; minors always blocked) is passed in and the generated idea is audited at that level.
4. **Different ideas across many projects.** The call is seeded from the start command id (a genre and an angle are picked from it when none is given) and given the titles and opening lines of the user's most recent projects as ideas to avoid. A near-duplicate (normalized word overlap above a threshold) is retried once with it added; a second near-duplicate stops the run with `IDEA_DUPLICATE`.
5. **Autopilot parameters become optional.** A story project's autopilot may carry no idea and no book length: its first part starts with `idea_mode = "auto"`; later parts continue the committed book as before. A Showrunner's explicit idea, genre or length always wins over the drawn one.
6. **Films configure from their story.** A film created for autopilot without wizard choices (including the batch of films for finished stories) takes its style template, aspect ratio and episode duration from a closed table keyed by the story's genre pack; only known template ids are written.
7. **Visible and overridable.** The project shows what was chosen (idea, genre, tone, length, style) and why; the create dialog's idea field is optional with "let the system choose".

Phases: (0) genre on automatic briefs; (1) profile schema and closed-set validation; (2) `idea_mode` and the drawn profile in BRIEF with replay reuse; (3) duplicate avoidance; (4) optional autopilot parameters; (5) film settings from the story's genre; (6) UI. Each phase is tested on the disposable PostgreSQL; one staged real run precedes workspace-wide use.

Implemented 2026-11-10, as decided with these specifics:

- §1: a brief whose genre names no pack asks the seed to pick one label from the ten packs; aliases match whole words only (`ma` no longer matches `mai`).
- §2: the profile is content-addressed in the story blob store and named by a *pin* (`story_authoring/pins/<sha256(key)>`, hard-linked into place so the first pin wins and never appears half-written). The draw spends at most two generations on the writer route; BRIEF reserves them (four calls with their counts, and the route's price bound on a cloud route). The brief's idea is the drawn idea with its tone and readers; an automatic run always starts a book of the drawn length. The project shows the profile under `story_profile` in project.json, which no input witness reads.
- §3: the project's safety level is written into the draw's instructions; the story's chapters are audited at that level as before, so no separate audit call is spent on the idea.
- §4: duplicates are compared with the ideas of the 20 most recently changed projects (their `story_profile`, else their title); word-overlap threshold 0.5.
- §6: the batch of films takes its look from the story's drawn genre when there is one, else from the template film.

Risks accepted: no Human reads the idea before it is written; Pause, Cancel and the recorded profile are the brakes. Thresholds for duplicates and the writer route's structured-output reliability are measured on real runs.

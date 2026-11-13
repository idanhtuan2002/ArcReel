---
status: accepted
---

# A story continues on the models the project has now

Decided 2026-11-13 by the main agent on the sponsor's instruction: "fix the app not letting the writer change in the middle of a story (the app must be able to change models flexibly at every step of story and film projects)". It amends [ADR-0129](0129-a-new-run-takes-over-an-unfinished-story.md) §1.

Free cloud quotas end mid-story (BytePlus and Alibaba give each model a one-time quota of 0.5–1M tokens; one short story took 1.3M tokens on 2026-11-02). Before this decision a stopped story could only go on with the routes it began with:

- every node fingerprint held the brief's route digest, and the first node held the brief digest, so a story on another writer rewrote everything from the seed;
- a later run took over a story only when its writer was the story's, the story had no judge route and no cloud prices, so no story with the craft judge (on since 2026-11-13) and no paid story was ever taken over;
- a story autopilot waited (`STORY_RUN_UNFINISHED`) on any unfinished story run, so it never started the run that would take a stopped story over.

1. **What was written stays written.** A brief gains an optional `basis`: the routes digest and the brief digest the story's nodes were first written under. Node fingerprints use `basis.routes` and the first node's brief input uses `basis.brief_digest` when a basis is set, the brief's own otherwise. Briefs without a basis keep their digests and fingerprints, so stories already running are unchanged. Each attempt still records the provider and model that answered it.
2. **Take-over reroutes the story.** A later automatic run takes over the project's stopped story whatever its routes, judges or prices; the project's current content safety is still required. The run greenlights the story's brief rerouted onto its own writer (`StoryAuthoringService.reroute_brief`): the same idea, structure, length and caps; the writer's routes, the judges that writer gets (craft judge on a local Ollama writer), their cloud profiles and the limit fields routes fix (input bound, context, currency, money cap, prices) are the run's; the basis is the original one. The task carries the rerouted brief from the hand-over, written with the run's command receipt, with the run's greenlight as its Gate A decision. A brief already on the run's routes is taken over unchanged.
3. **Money stays bounded by the run that pays.** The story's limits take the rerouted fields; on a priced route the money cap is the run's own reservation plus the tokens the story already used counted at the new prices, so the story spends at most what the run reserved. Call, token and time caps are reserved by the run as in ADR-0129. The top-up record keeps the limits before and after.
4. **The autopilot starts the run that takes over.** A story run stopped and left by automatic runs only (all their actor scopes are runs, and the planner starts nothing while a run of the project is active) no longer keeps a story autopilot waiting. A story a Showrunner started, one still queued or running, or a second unfinished story still does.

How the Showrunner changes the writer mid-story: change the project's text model in its automation settings (this re-pins the autopilot), cancel the blocked run if it is still open; the autopilot starts a new run, which takes the story over on the new writer.

Not changed: an open run keeps its frozen policy (a run is the unit a policy is approved for); variants and auto-idea runs are not taken over (ADR-0129); film runs take their routes from the settings when each run starts (whether a new film run reuses the media an earlier run of the same episode made is not settled here). A route change still needs the project's launch qualification to be recorded again before a film run passes preflight.

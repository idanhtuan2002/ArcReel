# Autonomous idea and self-configuration on autopilot

Date 2026-11-10. Worktree `impl/autonomous-production` at `ab76ddc63`. Sponsor request: on autopilot, if no idea is entered the program invents one, then configures itself (style, genre, format, content) from that idea. Status: research only, nothing decided. Paths are relative to the repo unless stated.

## 1. Internal facts

**Today an idea is mandatory, the genre is fixed.**
- `RunCommand` START with `story_source` `idea` or `continue` is rejected without an idea (`r2/contracts/automation.py:350-351`); the idea is part of the command that is hashed.
- `StoryAutopilot.idea` is a required `_Text`; `book_chapters` is required and bounded 6..120 (`r2/contracts/autopilot.py:19-24`). The delegation digest covers these (`:57-59`), and each start command id is derived from that digest plus ordinal and part (`:62-71`).
- Part 1 of an autopilot story starts from `delegation.story.idea` and `book_chapters` (`server/production_run/autopilot.py:176-181`); later parts use `direction` (`:186`).
- `BriefAdapter.dispatch` calls `draft_brief(genre=STORY_GENRE, ...)` with `STORY_GENRE = "truyện ngắn"` (`server/production_run/story_adapter.py:61,145`). Cost cap is `min(10_000, policy.max_cost_minor_units)` (`:148`), the route is the run's frozen `writer` route (`:127-130`).
- `brief_idea` raises `IDEA_REQUIRED` with neither idea nor variant profile (`server/story_authoring/service.py:159-170`).
- `draft_brief` freezes routes, limits and the project's content safety into `StoryBrief`; `safety = self.content_safety(project_name)`, default `standard` (`service.py:310-322`, `:324-330`). The brief's digest is what Gate A greenlights; `BriefAdapter` stores its exact bytes and greenlights that digest (`story_adapter.py:157-166`).
- Genre packs: 10 ids, `family mystery horror romance action fantasy scifi comedy historical school` (`server/story_authoring/genre_packs.py:35-136`). A run picks the pack whose alias occurs in the genre text (`:1-5`, `pack_for` `:150-157`). `"truyện ngắn"` appears in no alias (grep of `genre_packs.py` returned nothing), so an automatic run gets no pack, hence no genre planning block, craft rules or fatigue-phrase check. This is a quality gap independent of the sponsor's request.
- Book length: `BookSpec.chapters` ge 6, le 120 (`server/story_authoring/book.py:47`); at most 5 volumes (`:26`).
- Content safety (ADR-0121): four levels `strict standard mature off`, per project in `project.json`, read into the brief so a later change does not alter a running story (`docs/adr/0121-each-project-chooses-its-content-safety-level.md:9-13`); minors-sexual content is critical at every level (`:14`).
- ADR-0124: autopilot is a standing delegation recorded by an interactive Showrunner under a project or workspace grant; story parameters include "the first idea" and book length; command id is derived from the delegation digest so a crash replays the same run; any non-success outcome halts the project (`docs/adr/0124-projects-run-on-autopilot-under-a-standing-delegation.md:7-12`). ADR-0111 gives runs their own grant with automatic provenance (cited there, `:11`).
- Run stages: `BRIEF STORY STORY_COMMIT HANDOFF ASSET_ANALYSIS EPISODE_PLAN ADAPTATION SCRIPT_PLAN SCRIPT MEDIA ...` (`r2/contracts/automation.py:75-90`). There is no ideation stage.

**Film-side settings** (set at project creation, `server/routers/projects.py:213-241`, `:687-763`):
- `content_mode` (narration default; `ad` forbids `default_duration` and `episode_target_duration`, `:697-702`), `generation_mode` (required: `storyboard` or `reference_video`), `aspect_ratio` (default 9:16), `default_duration`, `episode_target_duration` (validated), `style_template_id` (checked by `is_known_template`, prompt via `resolve_template_prompt`, `:687-693`), backend fields validated by `validate_backend_value` (`:711-715`), `source_kind`, `speech_rate_units_per_second`.
- `lib/style_templates.py` holds 32 templates, ids `live_*` (live action) and `anim_*` (animation), each with a `category` and a Chinese prompt (`lib/style_templates.py:13-104`, accessors `:122-128`).
- Narration voice resolves `project.json narration_voice` > global setting > service default (`lib/config/resolver.py:1004-1011`).
- Commit `ab76ddc63` message: "new projects take production settings" (HEAD), so project creation already has a settings seam to extend.

**UI today**: the run panel idea field has placeholder `auto_idea_placeholder` ("Một hai câu về câu chuyện", `frontend/src/i18n/vi/workflow.ts:195`, used at `frontend/src/features/production-run/ui/ProductionRunPanel.tsx:356`); the story page uses `story_idea_placeholder` (`frontend/src/i18n/vi/dashboard.ts:2866`). No idea suggestion feature exists. A search of `docs/adr` and `docs/research` for ideation, discovery or research-stage plans found only donor notes (`docs/research/2026-11-08-r2-donor-stage-mechanisms.md`, `2026-10-18-r2-v2-story-release-research.md`); I found no accepted ADR for an ideation stage.

## 2. Donors (pinned commits)

**huohuo-drama @ f104b85** (`/home/anhtuan/content-os-r1-8/work/huohuo-drama`)
- Genre registry is a fixed table of presets, each with `value`, `skillKey`, `keywords`, `premise` text and `status` (`workbench-server/src/common/novel/novel-genre-registry.ts:3-21`); the frontend applies a preset to fill keywords and premise (`workbench/app/common/novel/novelGenrePresets.ts:25-32`).
- Premise generation starts from user keywords: `POST /novel/generate-premise` rejects empty keywords (`workbench-server/src/routes/novel/novel.ts:166-180`); `generateNovelPremise` builds a user message from title, genre, planned chapters and keywords, picks the genre's skill by `resolveSkillKeyFromGenreValue`, temperature 0.78, then `assertValidNovelCreativeOutput` (`workbench-server/src/services/novel/novel-writing.ts:137-161`). The `novel_premise` skill demands a 200-500 character premise covering world, protagonist, core conflict, tone and selling points (`agent-skills/novel_premise/SKILL.md:3-5`); each genre has its own premise skill (18 genre dirs under `agent-skills/novel_premise/`).
- Takeaway: it never invents an idea from nothing; the genre registry's `keywords` seed the generator. Genre is chosen first by the user, then ideas follow. Nothing derives genre from a free-text idea.

**shenbi @ 10efa7c** (cloned to the session scratchpad, `shenbi/`)
- `skills/shenbi-market-radar/SKILL.md:35-54`: human-driven: asks platform and genre, scans leaderboards by web search, reports saturated elements (over 60% of top-20 flagged saturated, `:53`) and an author checklist; every recommendation must cite a data row (`:60-70`, the evidence rule); "the author decides" (`:54`).
- `skills/shenbi-genre-config/SKILL.md:66-70`: genre config is a reviewed file; disabling critical audit dimensions requires a `manual_override` decision record with a rationale (`:70`); decisions are written to a `decisions.json` sidecar (schema `shenbi-decisions-v1`). This is the audit pattern worth copying.
- No skill invents a premise from nothing; `skills/shenbi-book-spine-init/SKILL.md` rule 2 says declared values are inherited, never invented (`:56`).

**OpenMontage @ 08e2151** (`/home/anhtuan/content-os-r1-8/work/OpenMontage`)
- Each pipeline has `idea-director`, `research-director`, `proposal-director` skills (`skills/pipelines/*/`). The topic comes from the user; research is web research; the proposal is reviewable before money is spent and records a `decision_log` with `options_considered`, `selected`, `reason` (`skills/pipelines/animation/proposal-director.md:5,21-23`). Idea-director classifies a mode (`animation_mode`) and a visual path from available tools and writes brief metadata (`skills/pipelines/animation/idea-director.md:15-60`). Style comes from `styles/*.yaml` playbooks (`styles/` has 6) chosen in the proposal.
- Takeaway: classification into a closed enum plus a decision log, but a human approves the proposal.

**Inference from donors**: none of the three auto-generates an idea with no input. The closest patterns are (a) a closed registry feeding a generator (huohuo), (b) a data-cited, human-reviewed trend step (shenbi, OpenMontage research), and (c) a recorded decision log (shenbi, OpenMontage). ArcReel would be the first to remove the human, so the audit record and diversity controls must be stronger than the donors', not weaker.

## 3. Facts, inferences, unknowns

Facts: sections 1 and 2.

Inferences:
- Idea generation must be an owner call before the brief because the brief's digest, Gate A and the command id all hash the idea; the idea cannot appear after the greenlight without a new digest.
- A generated idea is a paid model call; if it is not stored durably before the dependent command, a crash replay (ADR-0124 item 5) would draw a different idea and a different command id, and the old run could be orphaned or doubled.
- Without a closed enum and negatives, a writer model repeatedly produces the same few premises at "thousands of projects" scale. The existing 10 genre packs plus a vi-language topic space is the natural lever.

Unknowns (not verified):
- Real duplicate rate of model-generated premises from the writer route; needs a measurement on the actual routes.
- Whether the writer route follows a JSON schema reliably (Ollama gotchas are noted in memory; schema `pattern` applies to raw characters). Needs a probe before choosing structured output versus two plain calls.
- Whether style template prompts (Chinese text) are suitable for Vietnamese stories; no evidence either way.
- Cost of one ideation call versus the story's share; tiny relative to the story, but not measured.

## 4. Recommendation

### 4.1 Where idea generation runs: a new owner stage `IDEA` before `BRIEF` (option A, recommended)

Options:
- A. New run stage `IDEA` (owner adapter like `BriefAdapter`) that runs only when the start command carries `idea_mode = "auto"` instead of an idea. Pros: reuses run authority (ADR-0111), budget reservation, usage receipts, replay and the "needs you" surface; the result is an owner receipt with a digest that `BRIEF` reads, exactly as `STORY` reads the brief (`story_adapter.py:175-181`). Cons: touches `RunStage`, planner and the digest-bearing contract (additive, left out of the stored command at default like `story_source`, `automation.py:322-325`).
- B. Generate at autopilot enable and store in `StoryAutopilot.idea`. Pros: tiny change, idea is in the delegation digest. Cons: pays at enable time, in an interactive request, without a run's budget, route freeze or receipts; every enable of a workspace-wide batch becomes a burst of model calls; a retried enable would re-draw unless the command replay is exact. Fine only as the UI "suggest idea" button, not as the autonomous path.
- C. Inside the planner. Rejected: the planner is not an owner of paid calls in the evidence read.

Chosen: A for autonomy, with the same generator also exposed as an interactive "suggest idea" endpoint (B's UX without B's authority).

### 4.2 Durable storage and idempotency

- Store the idea artifact in the project's story blob store (`StoryBlobStore`, same as briefs, `story_adapter.py:97-99,153`) keyed by sha256 of canonical JSON; the `IDEA` stage returns `OwnerReceipt(owner="story-idea", digest=...)`.
- Idempotency key is the existing start command id (`autopilot_command_id`, `r2/contracts/autopilot.py:62-71`) plus stage `IDEA`; dispatch first looks for an existing receipt and reuses it. Crash after the model call but before the receipt: bounded loss of one call, recorded as usage by the reservation (do not claim exactly-once for the model call itself; claim exactly-one-recorded-idea).
- `BRIEF` reads the idea from the receipt, never from the command, so the command can stay `idea = None` and its digest stays stable across replay. Contract change: `RunCommand` allows `idea = None` for `story_source == "idea"` only when `idea_mode == "auto"` (new field, excluded when default, same pattern as `book_chapters`).
- For autopilot: `StoryAutopilot.idea` becomes optional (None means auto) and `book_chapters` optional (None means chosen by the classification, 4.4). The delegation digest then records "auto" rather than a drawn idea, and part 1's command carries `idea_mode = "auto"`. Parts 2+ continue from the committed book, which already holds the idea, so they need no new idea (`autopilot.py:182-186` unchanged).

### 4.3 Inputs, diversity, route, cost

- Inputs to the generator: language `vi` (`STORY_SOURCE_LANGUAGE`, `handoff.py:39`); optional genre preference (a pack id or none); the project's content safety level (read through `content_safety`, `service.py:324-330`); optional user hint words; a seed.
- Diversity: (1) the seed is derived from the command id so replay is deterministic in inputs; it selects one genre pack uniformly when none is preferred and one "angle" from a small table, as huohuo uses registry keywords to seed (`novel-genre-registry.ts:3-21`); (2) negatives: titles and the first 200 characters of the idea of the user's existing projects (`ProjectManager.list_projects`, `lib/project_manager.py:388`, plus stored idea artifacts), capped at about 40 most recent plus 10 nearest by genre; (3) a post-generation duplicate check (normalized token Jaccard against those, reject over a threshold, one retry with the matched idea added as negative, then fail visibly with a code instead of looping). Thresholds are unknown until measured on real output.
- Route: the frozen `writer` role (`route_for(run, "writer")`, `owner_support.py:161-163`); missing role blocks with `MISSING_MODEL_ROLE` as `BriefAdapter` does (`story_adapter.py:127-130`). Temperature moderately high (huohuo uses 0.78, `novel-writing.ts:147`) as a starting point, to be tuned.
- Cost bound: the stage is planned with an explicit estimate (1 or 2 model calls, short output) and cut from the run caps like `STORY_SHARE`; it never raises the run's caps, so the story share keeps its meaning. Fail closed if the reservation is refused.
- Output safety: the generated idea is audited by the same content safety level the story will use; a minors-sexual idea is refused regardless of level (ADR-0121 item 2). Generation never sees a level lower than the project's.

### 4.4 Auto configuration from the idea (`ProjectProfile`)

A second call (or the same call, decided after the structured-output probe) returns a schema-validated `ProjectProfile`:
- `genre_pack` in the 10 pack ids (closed enum from `PACKS`, `genre_packs.py:33`); the label passed to `draft_brief(genre=...)` instead of `STORY_GENRE`, fixing the no-pack gap in section 1.
- `tone` (short enum), `audience` (enum), `book_chapters` 6..120 (matches `BookSpec` bound, `book.py:47`; also clamp by affordable run caps).
- Film side, only for film projects: `style_template_id` in `STYLE_TEMPLATES` keys (validate with `is_known_template`, `projects.py:687-693`), `aspect_ratio` from a closed list, `episode_target_duration` through `_validated_episode_target_duration` (`projects.py:725-728`), `content_mode`, and `generation_mode`. Narration voice: pick only among voices that the resolver and TTS backend already expose; otherwise leave unset so the existing resolution applies (`resolver.py:1004-1011`).
- Validation: pydantic schema with closed enums; any out-of-enum or invalid value falls back to the documented default and records that it fell back. Selection by model is a classification; the final validity check is deterministic code.

**Human-owned and never auto-set** (inferences from ADR-0121 and ADR-0124):
- Content safety level: the profile may not carry it. New autopilot projects use the delegation's recorded level or `standard`; automation never lowers it, and may not raise it from `strict` either, because changing it changes what Gate A greenlit. A generated idea that needs a lower level is refused, not accommodated.
- Spending caps and run policy (policy digest frozen at enable, ADR-0124 item 1), routes, the grant chain.
- Anything touching accounts, backends that incur new cloud spend beyond the frozen policy.

### 4.5 Audit and override

- Write one `profile-decision` artifact (`schema r2.project-profile.v1`): input digests, generator route and model id, seed, candidates considered, selected values with a one-line reason each, which defaults were used, and the duplicate check result; modeled on the shenbi `decisions.json` sidecar and OpenMontage `decision_log` (donors above). Its digest is part of the `BRIEF` receipt chain, so Gate A greenlights a brief that names the profile.
- Overrides: a Showrunner can supply any field at enable time (explicit beats auto); after the fact, changing a project setting follows the existing PATCH rules, with immutable fields (`generation_mode`, `source_kind`, per `projects.py:232-234`) staying immutable. Re-running ideation is a new command id, never a replay.
- Film projects of finished stories (ADR-0124 item 6): the profile derives from the committed story, so no idea is generated; only style, aspect ratio and duration are chosen, using the story's `genre_pack`/tone as input.

### 4.6 UI

- Create and enable dialogs: idea becomes optional with a visible toggle "Let the system choose"; show the chosen genre, tone, length, style, format and the idea after the `IDEA` stage as read-only chips with a "Needs you" style Edit before Gate A only when the run is not on autopilot.
- Suggest button calls the same generator (interactive, runs under the user's session, counts usage) so users can preview ideas.
- The control room shows the profile decision per project; i18n keys for all supported languages (project rule in `CLAUDE.md`).

## 5. Risks

1. Duplicate or bland ideas at scale (mitigation: seed, negatives, duplicate check, genre rotation; measure first).
2. Idea or profile drift between replay and original (mitigation: receipt reuse, deterministic seed).
3. Idea outside content safety (mitigation: audit with project level; minors refusal at every level).
4. Model-chosen style mismatching a Vietnamese story (unknown; mitigation: restrict film choices to a vetted subset and measure).
5. Spend: every project on autopilot adds one ideation call; bounded by run caps, but ADR-0124 already accepts no cap beyond runs.
6. Additive contract changes alter digests if defaults are not excluded (mitigation: `exclude_if` default pattern, same as `story_source`).
7. Autonomy without a human reviewing the idea: wrong or off-brand ideas ship; Pause/Cancel and the decision record are the only brakes.

## 6. Phased plan with tests

- Phase 0 (fix first, small): replace `STORY_GENRE` with a genre argument from the command, default mapped to a pack; test that an automatic brief selects a pack and that existing fixtures still pass. Probe writer-route structured output on the real routes (manual, recorded in evidence).
- Phase 1: `ProjectProfile` schema, closed-enum validation, deterministic fallback; unit tests for each enum bound (6, 120, unknown template id, unknown pack), and for "profile cannot carry content safety".
- Phase 2: `IDEA` stage and `story-idea` owner adapter, `idea_mode` on `RunCommand`; tests: replay with a stored receipt makes no second model call (fake route counts calls), missing writer route blocks, refused reservation blocks, command digest of default commands unchanged.
- Phase 3: diversity (negatives, duplicate check); tests with a fake generator returning a duplicate then a fresh idea, and a duplicate twice failing with a code.
- Phase 4: autopilot: `StoryAutopilot.idea` and `book_chapters` optional, `idea_mode` in part 1's command; tests: crash between stages replays the same run id, part 2 continues with no idea call, delegation digest differs between auto and explicit.
- Phase 5: film profile (style, aspect, duration, voice) for new film projects and the batch of films for finished stories; tests that `is_known_template` rejects invented ids and voices never leave the exposed set.
- Phase 6: UI (optional idea, chips, suggest button, i18n consistency test), decision record view, then a staged real run on one small project before any workspace-wide use.

Each phase ends with the related tests only, per the repo's test-selection rule; Phases 2 and 4 need the Postgres-backed suites run through `AsyncClient` per the known cross-loop caveat.

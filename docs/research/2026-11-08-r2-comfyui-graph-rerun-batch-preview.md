# Graph view, partial re-run, batch variants and live previews: what to take from ComfyUI

Date: 2026-11-08. Worktree `9b89` at `1101f7e0a`. Follow-up to
[2026-11-04-r2-automatic-production-ui-vs-comfyui.md](2026-11-04-r2-automatic-production-ui-vs-comfyui.md), which
rejected the node canvas, queue modes and batch count in one line each. This round gives those four topics a
primary-source basis. Facts, inferences and unknowns are labelled; "Inference" is mine, not a source claim.

## 1. Question and scope

A production run has 14 fixed stages (`RunStage`, `r2/contracts/automation.py:75-89`) and carries governance. A real
run took 4 h 33 min: STORY ~4 h 10 min as one task, MEDIA ~10 min for 15 tasks. Four questions:

1. Node graph UI: what does a canvas add to a fixed 14-stage pipeline over a stage timeline or read-only graph?
2. Re-run on change: how does ComfyUI rerun only changed nodes, and what would "change one scene's image prompt,
   regenerate that asset and the downstream RENDER/MASTER/QUALITY" need in ArcReel?
3. Batch and variants: where do N variants make sense given GPU cost?
4. Live previews and thumbnails: can the run panel show media as MEDIA tasks finish, and STORY progress?

Out of scope: licensing (project policy), changing the 2026-09-29 decision, any code change.

## 2. Internal state (facts)

**Governance decision.** `docs/research/2026-09-29-r2-comfyui-reuse.md:40-49`: ComfyUI's frontend "is a workflow
editor built on **LiteGraph**, not React Flow"; large graphs of 100+ nodes lag; recommendation 2 is "Do not use it
as the Creative Canvas (M8-B)"; embedding LiteGraph "would bring in a second graph model and a second history, and
nothing would say which graph is authoritative". Row 3 of its table: "ComfyUI editor as the Canvas — Rejected".
The 2026-11-04 doc (line 58) restates it: ComfyUI is an execution backend, not the canvas.

**Run model and reuse.**
- `server/production_run/service.py:45-52` `_RESUMABLE` = PAUSED and the five BLOCKED_* states. Resume of a
  blocked run keeps stage, generation and `completed_targets` (`service.py:418-424`, `_changed(... status=RUNNING)`);
  it does not rerun finished stages.
- Step identity is a digest of `run_id, stage, unit_key, generation, input_digest, policy_digest, repair_index`
  (`r2/automation/identity.py:24-52`; `command_id` and `task_id` derive from it). `current_step` looks up a staged
  step by stage + generation + input digest + policy digest
  (`lib/db/repositories/production_runs.py:271-299`). Inference: a changed policy or input yields a different
  identity and therefore no reuse; the same identity reuses the receipt (`controller.py:92-96, 108-113`).
- `input_digest` is one value per run. Each tick compares the witness digest of the project inputs with
  `run.input_digest`; on mismatch the run blocks `BLOCKED_INPUT_CHANGED` (`controller.py:71-72`). Resuming with
  rebind starts "a new lineage": `generation + 1`, stage reset to BRIEF, `completed_targets=()`
  (`service.py:433-442`). So today an input change is a whole-run restart, not a partial one.
- A scoped partial re-run already exists for quality rework. `advance` on `REWORK` (`r2/automation/transitions.py:
  85-113`) jumps back to `outcome.repair_stage`, bumps `generation`, counts repairs per `(stage, unit_key)`
  against `unit_repair_limit` (max 2, `automation.py:125`), and drops only the affected targets from
  `completed_targets`. If the repair stage is at or before EPISODE_PLAN it widens to all targets (line 102).
  QUALITY emits `REWORK` with `unit_key=f"episode:{n}"` (`quality_adapter.py:132, 160-163`).
- Granularity today: MEDIA plans one step with `unit_key="media"` for all targets and `calls_per_target * units`
  tasks (`media_adapter.py:101-122`); QUALITY is `unit_key="quality"` (`quality_adapter.py:83`). Inference: the
  smallest rerun unit is an episode target, never one scene or asset.

**Progress and report.** `server/production_run/report.py:79-87` `run_progress` returns only
`{run_id, stage, tasks: Counter(status)}` for the current stage's owner tasks. `run_report` returns reviews,
final previews and story exceptions (`report.py:113-126`); `verified_final` hashes the mp4 against
`final_digest` (`report.py:59-67`). Routes: `GET .../report`, `.../progress`, `.../outputs/{episode}/final`
(`server/routers/production_runs.py:331-367`). 2026-11-08 progress note: `/progress` returned `{"tasks": {}}`
for all of STORY (2026-11-04 doc §6).

**Frontend.**
- Stage strip: `STAGES.map(...)` list in `ProductionRunPanel.tsx:422-438` with `reached` index (line 255). It
  polls every 5 s (`POLL_MS = 5000`, lines 31, 133, 156). Files: `frontend/src/features/production-run/ui/
  {ProductionRunPanel,RunReportDetails,AutomationQualification,AutomationReadiness,AutomationSettingsEditor}.tsx`.
- `@xyflow/react` 12.10.2 is already a dependency (`frontend/package.json:28`), used by the Creative Canvas
  (`frontend/src/features/creative-canvas/ui/{CanvasBoard,CanvasNodeView,CreativeCanvasPage}.tsx`).
- Per-asset versions: `lib/version_manager.py:159-170` keeps `<project>/versions/versions.json` with
  `add_version`, `commit_staged_version(s)`, `commit_staged_paid_version`; UI `components/canvas/timeline/
  VersionTimeMachine.tsx` lists versions and selects one. Grid regenerate: `server/routers/grids.py:305`.
  Inference: this is the manual path (human edits one asset, picks a version); it is separate from the run
  controller and does not feed `completed_targets` or digests.
- Push channels already present: project filesystem SSE `GET /projects/{name}/events/stream`
  (`server/routers/project_events.py`, 1 s poll, `fastapi.sse`), a durable execution-event SSE
  (`server/routers/execution_events.py`, 15 s idle), and a header-capable fetch-SSE client
  `frontend/src/utils/sse-stream.ts` with backoff reconnect. `useTaskRefresh.ts:1-25` says terminal task states
  arrive over the project SSE, while queued-to-running is polled (3 s fast, 30 s idle). The production-run panel
  itself does not use SSE; it polls.
- ComfyUI client: HTTP only. `lib/custom_provider/comfyui_execution.py:141-170` polls `fetch_history(prompt_id)`
  to a terminal state and falls back to `/queue` to decide "job lost" (lines 205-227); artifacts via
  `{base_url}/view?...` (line 137). No websocket in `lib/custom_provider/comfyui_*.py` (grep for
  `websocket|/ws` returned nothing).

## 3. ComfyUI facts per topic

Sources were read on 2026-11-08 at ComfyUI `master` `c76e64fe5f` (latest release tag v0.44.0) and
ComfyUI_frontend `master` `4926abbd0f`. Quotes under ~125 characters come from the fetched pages. WebFetch
summarizes pages, so quotes were extracted by a small model and not copied byte-for-byte by me; treat them as
close paraphrase of the cited file.

### 3.1 Node graph UI

- The frontend is LiteGraph-based and Vue: package `@comfyorg/comfyui-frontend` depends on `vue`
  (`package.json`); its README changelog entries are tagged "**Litegraph**" (nested group, canvas pan mode).
  [github.com/Comfy-Org/ComfyUI_frontend](https://github.com/Comfy-Org/ComfyUI_frontend). The repo home page
  returned HTTP 504 via WebFetch; README and `package.json` were read through `gh api`.
- "App Mode" is "Linear / app-style UI for running workflows"; Apps is a sidebar entry
  ([docs.comfy.org/interface/overview](https://docs.comfy.org/interface/overview)). Fact: ComfyUI itself ships a
  non-graph linear view of the same workflow. Not found: its internals or what it hides.
- Partial Execution "lets you run only a part of your workflow" and "Only runs the branch of the workflow from the
  starting node to the output node" ([interface/features/partial-execution](https://docs.comfy.org/interface/features/partial-execution)).
  The page says nothing about cached nodes.

### 3.2 Re-run on change

Source: [comfy_execution/caching.py](https://github.com/comfyanonymous/ComfyUI/blob/master/comfy_execution/caching.py)
and [execution.py](https://github.com/comfyanonymous/ComfyUI/blob/master/execution.py).

- Per-node cache key (`CacheKeySetInputSignature`): the signature is `[class_type, is_changed]`, plus `node_id`
  only for `NOT_IDEMPOTENT` or `UNIQUE_ID` nodes, plus each input in sorted order: literals as `(key, value)`,
  links as `(key, ("ANCESTOR", ancestor_index, ancestor_socket))`. The key is the node's signature followed by the
  signature of every ancestor, in deterministic order. "The `IS_CHANGED` result is part of the key, so a changed
  value produces a cache miss." Ancestors are indexed by wiring order, not node id, so identical graphs give
  identical keys.
- Consequence (inference from the above, consistent with the source): editing one literal changes that node's
  signature and the signature of every node that has it as an ancestor. Those keys miss and rerun; siblings and
  upstream nodes hit. That is the whole mechanism of "only changed nodes rerun"; there is no separate dirty flag.
- `IsChangedCache.get(node_id)` calls `IS_CHANGED` (V1) or `fingerprint_inputs` (V3); "If neither exists, the result
  is `False`". "Intentionally do not use cached outputs here. We only want constants in IS_CHANGED". A raising
  `IS_CHANGED` becomes `NaN`, which never equals itself, so the node always reruns (used for nodes that read
  files or time).
- `execute()` does `cached = await caches.outputs.get(unique_id)`; on a hit it calls `emit_cached_output(...)` and
  returns SUCCESS without running the node. Before the loop, `execution_cached` is sent listing "nodes" skipped.
  After a run: `await caches.outputs.set(unique_id, cache_entry)`.
- Eviction: `BasicCache.clean_unused()` drops entries whose key is not used by the current prompt (so an old
  branch is forgotten after the graph changes); `LRUCache(max_size=100)` keeps the N most recently used;
  `NullCache` stores nothing; `RAMPressureCache` evicts by an age-weighted score when RAM is low.
- Server flags (`comfy/cli_args.py`): `--cache-classic` "Use the old style (aggressive) caching."; `--cache-lru N`
  "Use LRU caching with a maximum of N node results cached. May use more RAM/VRAM."; `--cache-none` "Reduced
  RAM/VRAM usage at the expense of executing every node for each run."; `--cache-ram` "Use RAM pressure caching
  ... This is the default caching mode." `PromptExecutor` itself defaults to classic when no type is passed.
- Important limit: the cache is in memory only (`self.cache` dicts). Restarting the server clears it. Inference:
  ComfyUI's reuse is a per-process optimisation; ArcReel's `production_steps` rows and receipts are durable.
- Frontend queue modes: "Run (On Change) queues again each time you edit the workflow"; "Run (Instant) queues
  again right after the current run finishes" (overview page). Combined with the cache, On Change reruns only the
  invalidated suffix.

### 3.3 Batch and variants

- "Batch count: How many times the workflow is queued per run (default `1`)" (overview page). Each queued run is a
  separate prompt with its own `prompt_id`.
- KSampler: seed "Used to generate random noise, using the same 'seed' generates identical images";
  `control_after_generate` "Provides ability to change seed after each prompt" with options listed as
  "Random/Inc/Dec/Keep" ([docs.comfy.org/built-in-nodes/KSampler](https://docs.comfy.org/built-in-nodes/KSampler)).
  The page does not define the options or document `batch_size`; I did not find a primary page for it, so
  `batch_size` (images per latent batch inside one run) is **unknown to me from primary docs**.
- Inference from §3.2: because the seed is a node input, changing it changes the key of the sampler and its
  downstream nodes only; text encoders and model loaders hit the cache, so a new variant costs the sampling and
  decode time, not the whole workflow.
- Job History groups and previews multi-output jobs; the 2026-11-04 doc already cites Assets "multi-output runs
  grouped with a count badge". Side-by-side comparison of variants: not found in the pages read.

### 3.4 Live previews and thumbnails

- Websocket events (`/ws`): `execution_start`, `executing`, `progress` (`node`, `prompt_id`, `value`, `max`; "Sent
  during a node's execution, but only if the node implements the required hook"), `executed` (`output`, only when
  a node returns UI output), `execution_cached`, `execution_success`, `execution_error`, `status`
  ([comms_messages](https://docs.comfy.org/development/comfyui-server/comms_messages)). That page does not cover
  binary previews.
- Source fills the gap. `server.py`: binary frames are `struct.pack(">I", event)` + payload; PREVIEW_IMAGE is a
  4-byte image type (JPEG 1, PNG 2) + encoded image; PREVIEW_IMAGE_WITH_METADATA is a 4-byte metadata length +
  JSON metadata + image. `comfy_execution/progress.py` (`WebUIProgressHandler`) sends a combined
  `progress_state` JSON message `{"prompt_id", "nodes": {...}}` with per-node state, and a
  `PREVIEW_IMAGE_WITH_METADATA` frame. This closes the 2026-11-04 unknown "per-node progress": the server does emit
  it; whether the current frontend renders it was not checked.
- Preview method: `--preview-method` values `none | auto | latent2rgb | taesd`, default `none`, "Default preview
  method for sampler nodes."; `--preview-size` default 512 (`comfy/cli_args.py`). Frontend setting: "Live preview
  method" (docs.comfy.org/interface/settings/comfy, from 2026-11-04 doc).
- Job History: "Jobs are listed with status, progress when running, and preview thumbnails when outputs exist"
  (docs.comfy.org/interface/job-history, from the 2026-11-04 doc).
- Polling alternative: `GET /history/{prompt_id}`, `/queue`, `/view?filename=...` (`server.py`). `/history`
  appears only after the job ends; `/queue` shows running and pending. Inference: previews of an in-progress
  sampler need the websocket; a poller sees only finished outputs.

## 4. Other tools (graph UIs)

- React Flow ([reactflow.dev](https://reactflow.dev/learn), v12 `@xyflow/react`; repo `xyflow/xyflow` `1bc405cd11`):
  interaction props exist: `nodesDraggable` "Controls whether all nodes should be draggable or not.",
  `nodesConnectable` "Controls whether all nodes should be connectable or not.", `elementsSelectable` "When
  `true`, elements (nodes and edges) can be selected by clicking on them." The docs never say "read-only"; setting
  those three false is how a view-only graph is built (inference). `onlyRenderVisibleElements` limits rendering to
  the viewport. Layout: "We have not implemented our own layouting solution yet"; recommended external libraries
  dagre (trees), d3-hierarchy, d3-force, elkjs ("the most configurable ... also the most complicated"). For 14
  fixed nodes, positions can be hard-coded and no layout library is needed (inference).
- Vue Flow, Rete.js: not read; they are Vue and framework-agnostic respectively and add nothing for a React app
  that already ships `@xyflow/react`. Unknown beyond that.
- Nuke/Houdini: not read (no quick primary page was fetched). I make no claim about them.

**What a canvas adds (inference).** In ComfyUI the graph is the program: users author topology (swap samplers, add
LoRAs). ArcReel's topology is fixed (14 stages), and authority lives in the controller, grants and digests; the
2026-09-29 decision already refuses a second authoritative graph. So an editable canvas adds nothing the
controller would honour. A read-only graph adds only things a stage strip lacks: fan-out within a stage (episodes
x scenes x assets), dependency edges showing what a change invalidates, and per-node status/thumbnail. The stage
strip is linear and cannot show "this one asset is stale because scene 3's prompt changed". The honest value is
the invalidation view, not editing.

## 5. Comparison per topic

| Topic | ComfyUI pattern | ArcReel today | Adopt? | Why |
|---|---|---|---|---|
| Graph UI | Editable LiteGraph canvas; App Mode as linear alternative | 14-item stage strip, polled every 5 s | **No** for editable canvas; **Partly** for a read-only graph | Topology is fixed and controller-owned; 2026-09-29 forbids a second authoritative graph. A read-only React Flow view of stage -> episode -> unit nodes shows fan-out and invalidation; `@xyflow/react` is already installed. |
| Re-run on change | Content-addressed key (inputs + ancestors + IS_CHANGED); miss = rerun; in-memory cache | Step identity digest includes generation, input_digest, policy_digest; REWORK jumps to `repair_stage` with a generation bump; input change = restart from BRIEF | **Partly** | The reuse key idea exists but is run-wide. Per-unit keys (one scene's prompt digest) are missing; the mechanism to adopt is per-unit input digests, not a cache. Durable rows replace the in-memory cache. |
| Queue modes (On Change / Instant) | Re-queue on every edit | None | **No** | Hours-long STORY and paid calls under budgets; automatic re-queue breaks governance. Make re-run an explicit, granted command. |
| Partial execution | Run only start-to-output branch | `REWORK` re-enters at one stage for scoped targets | **Partly** | Same idea; ArcReel already has it for QUALITY-driven repair; a Human-initiated variant is the new part. |
| Batch count | Queue the same workflow N times | Episode count at start only | **No** at run level; **Yes** per cheap asset | N full runs = N x 4.5 h. For one storyboard/clip, N variants cost minutes. |
| Seed control | fixed / increment / randomize after generate | Not exposed in the run panel (not checked in backends) | **Partly** | Fixed seed for reproducible rerun, randomize for variants; store the seed in the version metadata. |
| Variant compare | Job History grouping | `VersionTimeMachine` lists versions per asset | **Yes** | Reuse the existing version store and UI; no new compare surface needed first. |
| Progress per node | `progress` value/max, `progress_state` | `/progress` task counts; empty during STORY | **Yes** | STORY progress is the largest gap (4 h of blank). |
| Live sampler preview | Websocket binary frames, latent2rgb/taesd | HTTP poll of `/history`; no websocket | **No** (for now) | Needs a ComfyUI websocket client plus a relay; image tasks last about a minute. Finished-output thumbnails give most of the value. |
| Output thumbnails | Job History thumbnails | Final mp4 preview only | **Yes** | MEDIA outputs land in `versions/` and project SSE already announces file changes. |

## 6. Recommendation (ranked by value / cost)

1. **STORY progress inside the stage (high value, small).** Expose scenes drafted / planned and repair round in
   `/progress` by reading the story run state (`RunStateStore`, already loaded in `report.py:97`), and show it in
   the panel; add started-at and elapsed per stage. Files: `server/production_run/report.py` (`run_progress`),
   `server/routers/production_runs.py`, `ProductionRunPanel.tsx`, i18n en/vi/zh. Effort: about 1 day. Unknown to
   verify first: which story state fields give a total (see §7).
2. **MEDIA thumbnails as tasks finish (high value, small).** List the run's produced images/clips for the current
   stage with thumbnails from the project file tree; refresh via the project SSE the panel does not use yet
   (`useProjectEventsSSE`), keeping the 5 s poll as fallback. Files: `report.py` (a `media` list), a new
   authenticated thumbnail route beside `outputs/{episode}/final`, `RunReportDetails.tsx`. Effort: 1-2 days.
3. **Read-only invalidation graph (medium value, medium).** Render stage -> episode -> unit nodes with status and
   thumbnail using `@xyflow/react` (view-only props, hard-coded layout). It becomes valuable mainly together with
   item 4; alone it duplicates the strip. Files: new `frontend/src/features/production-run/ui/RunGraph.tsx`, reuse
   `CanvasBoard` styles. Effort: 2-3 days.
4. **Targeted regenerate with downstream invalidation (highest value, highest cost; needs an ADR).** Required
   pieces, as inference from §2:
   - per-unit input digests (scene prompt, asset prompt) recorded in the step's `input_refs` or a unit table;
   - MEDIA planned per unit (today one `unit_key="media"` step) so one asset can be marked stale alone;
   - a Human command `regenerate-unit {stage, unit_key}` that reuses the `REWORK` path
     (`transitions.py:85-113`: bump generation, drop affected targets), with `unit_repair_limit` and the grant
     and budget checks unchanged, and an explicit downstream set (RENDER, MASTER, QUALITY, PACKAGE, EXPORT for that
     episode; the existing code already drops the whole target);
   - tie to the version store so the new asset is a new version, not an overwrite.
   Files: `r2/automation/transitions.py`, `identity.py`, `server/production_run/media_adapter.py`,
   `quality_adapter.py`, `service.py`, `routers/production_runs.py`, `lib/db/repositories/production_runs.py`,
   an Alembic migration if a unit table is added. Effort: 1-2 weeks. Smaller first slice: episode-level
   "regenerate from MEDIA" using the existing REWORK semantics only (about 2-3 days), since the generation bump and
   target scoping already exist.
5. **Variants for cheap stages only (medium value, after 4).** N variants of one storyboard image or clip with
   fixed/increment seed, saved as versions of the same asset; pick one in `VersionTimeMachine`. Not for STORY (one
   extra variant = about 4 h of GPU) and not at run level. Story-idea alternatives belong in BRIEF/idea
   brainstorming with a cheap model, not in a full run. Files: `lib/version_manager.py` (seed in metadata),
   the image task builder, `VersionTimeMachine.tsx`. Effort: 3-5 days.
6. **ComfyUI websocket client for live latent previews (low value now, medium cost).** Only if clip generation
   becomes long enough that a blank minute matters. Files: `lib/custom_provider/comfyui_execution.py`, a relay
   to the SSE. Effort: 1 week. Defer.

Not recommended: editable canvas, On Change/Instant queue, run-level batch count.

## 7. Unknowns

- Whether the current ComfyUI frontend renders `progress_state` per node and the live previews (server side
  confirmed; frontend rendering not read; the frontend README page returned 504).
- ComfyUI `batch_size` semantics and the exact meaning of `control_after_generate` options: the docs page lists
  "Random/Inc/Dec/Keep" without definitions.
- `IS_CHANGED` / `fingerprint_inputs` behaviour for specific nodes (LoadImage etc.) was not read.
- Whether ArcReel's story run state carries a planned-scene total during STORY (needed for "N of M"); not read.
- Which image/clip seed ArcReel's backends pass, and whether results are deterministic per seed on FLUX.2 klein
  endpoints: not checked.
- Exact GPU cost of a variant: only the 15-task MEDIA total of about 10 min is known; per-task times were not
  measured here.
- Vue Flow, Rete.js, Nuke, Houdini: not read; no claim made.
- Whether a Human-initiated regenerate fits the existing grant operations (`AutomationOperation` per stage,
  `controller.py:197`) or needs a new operation: not designed.

## 8. Verification and status (main agent, 2026-11-08)

- Internal citations re-checked against source at `2babeb56a`: `docs/research/2026-09-29-r2-comfyui-reuse.md:40-49`
  (ComfyUI is a backend, not the canvas), `r2/automation/transitions.py:85-113` (REWORK bumps the generation and
  drops only affected targets), `lib/custom_provider/comfyui_execution.py:141-170` (HTTP `/history` polling, no
  websocket), `frontend/package.json` `@xyflow/react` 12.10.2 (used by `features/creative-canvas`).
- Recommendation 1 implemented in `2babeb56a`: `GET …/progress` returns `started_at`, per-stage `finished_at` and,
  inside STORY, the story run's planning / scenes drafted of planned / reviews / model calls; the run panel shows
  each stage's duration, the run's elapsed time and the story line.

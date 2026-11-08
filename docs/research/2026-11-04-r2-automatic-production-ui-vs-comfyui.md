# Automatic production UI: what is still unwired, and what to take from ComfyUI's interface

Date: 2026-11-04. Branch `impl/autonomous-production` at `bd7ddb734`. Sponsor request: wire every function to the
UI, and research the current UI against the ComfyUI donor.

## 1. Internal state (facts)

Wired in the run panel (episode page and project overview) since 2026-11-04: Start (idea, mode, episode count),
pause/resume/cancel, mode switch, semi-mode review, 14-stage list, status/reasons in words, run history and
details, quality report per target, accepted story exceptions, readiness (real preflight), setup editor (model per
role, limits), download with the quality decision.

Not wired (backend or scripts only):

| Function | Where it lives today | Gap |
|---|---|---|
| Automatic quality profile | `server/services/quality_template.automatic_quality_policy`; Quality page (M10) publishes only the human template from `GET /quality/template` | no automatic template in the UI; the setup editor cannot point the project at a published profile |
| Reviewer qualification | `scripts/r2/qualify_reviewers.py` (`qualify`, receipt reuse, `--record`) | CLI only; ~45–90 min GPU per reviewer when receipts cannot be reused |
| Launch qualification record | `scripts/r2/record_launch_qualification.py` (`build_record`: records only when the real preflight's sole blocker is `LAUNCH_PROFILE_NOT_QUALIFIED`) | CLI only |
| Progress inside a stage | owner tasks per step (`server/production_run/owner_tasks.py`), project task table | panel shows the stage only |
| Final preview | verified archive download; final mp4 under `production/automation/<run>/g<gen>/episode_<n>/` | no in-panel preview |

Authority: the app is single-user (`server/auth.py`: every session maps to `DEFAULT_USER_ID`); Human-only actions use
`InteractiveUser` (a session JWT, never an API key or an agent token). M10 profile publication is already a
Human-signed prepare/submit flow on the Quality page.

## 2. ComfyUI interface (primary sources, read 2026-11-04)

- Overview ([docs.comfy.org/interface/overview](https://docs.comfy.org/interface/overview)): left sidebar (Job
  History, Assets, Nodes, Models, Workflows, Apps), a run bar with batch count, Run, queue modes (Run, On Change,
  Instant), Cancel, and an Active jobs control that opens the queue.
- Job History ([interface/job-history](https://docs.comfy.org/interface/job-history)): status tabs All / Completed /
  Failed, running and queued counts, per-job actions (cancel, copy job ID; for completed: inspect, download, open as
  workflow; for failed: copy error message, report error, remove from the list), "Clear history".
- Assets ([interface/assets](https://docs.comfy.org/interface/assets)): Generated and Imported tabs, list or grid,
  preview by double-click, download, multi-output runs grouped with a count badge.
- Errors ([interface/right-side-panel](https://docs.comfy.org/interface/right-side-panel)): an Errors tab only when
  errors exist; node errors with "locate", missing models with download actions; a red dot on the closed panel.
- Templates ([interface/features/template](https://docs.comfy.org/interface/features/template)): a gallery to start
  from a ready workflow; missing models show as a banner "N errors found" with details, not a modal.
- Server messages ([comms_messages](https://docs.comfy.org/development/comfyui-server/comms_messages)):
  `execution_start`, `executing`, `progress` (`value`, `max`), `executed`, `execution_cached`, `execution_error`,
  `execution_interrupted`, `execution_success`, `status` (`queue_remaining`).
- Not found in the pages read (unknown): an overall progress bar, per-node progress display and live sampling
  previews in the current frontend.

## 3. Comparison and inferences

| ComfyUI pattern | ArcReel run panel now | Take it? |
|---|---|---|
| Job list with status tabs and per-job actions | a run selector | **Yes**: list runs with All / Active / Done / Failed filters; per run: open, copy run id, copy reason, download |
| `progress` value/max per running node | stage name only | **Yes, as counts**: owner tasks of the current stage (queued / running / done / failed); the run is a pipeline of stages, not a node graph |
| Assets with preview | zip download | **Yes**: preview the verified final mp4 of each completed target in the panel |
| Errors tab only when errors exist, with actions | reason line | **Yes**: an errors box when the run is blocked/failed, with the reason in words, copy, and the action (resume / setup) |
| Templates gallery | free idea text | Partly: example ideas to start from; launch profiles already in setup |
| Queue modes (On Change, Instant), batch count | Start once; episode count | No: automatic runs are expensive (hours of GPU); re-running on change would waste resources |
| LiteGraph node editor | not used | No (2026-09-29 decision stands: ComfyUI is an execution backend, not the canvas) |

## 4. Plan (decided; implemented in this order)

1. Quality: `GET /quality/template?kind=automatic` returns `automatic_quality_policy`; the Quality page offers it.
2. Setup editor: choose the published quality profile (profile id + digest) from the project's profiles.
3. Qualification service `server/production_run/qualification.py` (moved out of the scripts, which stay thin CLIs):
   reviewer qualification as a background job per reviewer role with stored-receipt reuse, and the launch
   qualification record; `POST`/`GET /projects/{p}/automation/qualification…` behind `InteractiveUser`; corpus and
   receipt directories from host settings (`ARCREEL_REVIEWER_CORPUS`, `ARCREEL_REVIEWER_RECEIPTS`), never from the
   request.
4. Run panel (ComfyUI patterns): run list with filters and actions, stage task counts, final preview, errors box,
   example ideas.

## 5. Unknowns

- Whether ComfyUI's current frontend shows per-node progress or live previews (pages read do not say).
- How long a reviewer qualification takes when no stored receipt matches (measured earlier: ~45 min per local
  reviewer on the 40-case corpus; a Gemini reviewer depends on API limits).

## 6. Follow-up 2026-11-08 (after the first production run)

Implementation check at `9f4bf373b` (`frontend/src/features/production-run/`): all four plan items of §4 are wired —
history filters All / Active / Done / Failed (`ProductionRunPanel.tsx`), example ideas, stage task counts from
`GET …/progress`, error/reason box, in-panel final preview (`RunReportDetails.tsx`, `GET …/outputs/{n}/final`),
reviewer and launch qualification (`AutomationQualification.tsx`), settings editor, readiness.

ComfyUI re-read 2026-11-08 (docs.comfy.org; the frontend GitHub README returned 504 and was not read):
- [job-history](https://docs.comfy.org/interface/job-history): "Jobs are listed with status, progress when running,
  and preview thumbnails when outputs exist"; sort by "Most recent" or "Total generation time".
- [settings/comfy](https://docs.comfy.org/interface/settings/comfy): "Live preview method" (none, auto, latent2rgb,
  taesd) — an image in progress is previewed while a prompt runs.
- Per-node progress display, tab-title progress, completion sound/notification: not found in the pages read.

Gaps the production run `6de90785` exposed (facts from its progress log):
- STORY ran ~4 h 10 min as one task; `/progress` returned `{"tasks": {}}` the whole time, so the panel showed only
  the stage name. ComfyUI shows progress for a running job. Inference: progress inside STORY (scenes drafted of the
  planned total, repair round) is the highest-value addition; the story run state already tracks its nodes.
- No elapsed time per stage or per run, and no start/finish time on the run; ComfyUI at least sorts by total
  generation time. Inference: show started-at, elapsed per stage and total (the run record's step history has the
  timestamps).
- Preview exists only for the verified final; ComfyUI shows thumbnails of outputs as they appear. Inference: show
  the current stage's produced media (storyboards, clips) as thumbnails during MEDIA.
- The quality gate `record` exported a final the reviewers judged REWORK; the panel shows the decision next to the
  download, which matches ComfyUI's "status + outputs" pattern; no change needed.

Not adopted, unchanged from §3: node canvas, queue modes, batch count.

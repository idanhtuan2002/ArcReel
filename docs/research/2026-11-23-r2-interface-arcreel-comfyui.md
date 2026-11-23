# The product interface: ArcReel, ComfyUI, DramaClaw's canvas

Date: 2026-11-23. The sponsor asked: what about the interface and ArcReel as a donor; should the ComfyUI interface be
used because it is visual and easy to operate? Labels: **FACT** (source), **INFER**.

## 1. Facts

- **ComfyUI** is a node editor for model pipelines (LiteGraph; nodes are samplers, VAEs, loaders); its interface
  patterns around the graph — job history with status filters and per-job actions, progress while running, assets
  with preview, an errors panel only when errors exist, a template gallery — were studied on 2026-11-04
  (`2026-11-04-r2-automatic-production-ui-vs-comfyui.md`, sources docs.comfy.org). That study kept ComfyUI as an
  execution backend, not the product canvas (decision of 2026-09-29), and took the patterns into ArcReel's run panel.
- **ArcReel's run panel** (`frontend/src/features/production-run/` on `impl/autonomous-production`, then the release
  line) implements those patterns: history filters All / Active / Done / Failed, stage task counts, an errors box,
  in-panel final preview, example ideas; the app's UI is Vietnamese. It is bound to R2's API (production runs, grants,
  qualification).
- **DramaClaw already ships a visual node canvas**: `frontend/src/features/canvas/` built on `@xyflow/react` 12
  (`frontend/package.json`), with node types for images, image edits, video, audio and text (`nodes/`), backed by its
  "freezone" API. Its UI languages are `zh`, `en` (`frontend/src/i18n/index.ts`, `SUPPORTED = ["zh","en"]`, locale files
  loaded over HTTP).
- huohuo's workbench UI has `vi`.

## 2. Options for "visual and easy to operate"

| Option | What it means | Verdict (INFER) |
|---|---|---|
| ComfyUI as the product UI | wrap every donor stage (story, episodes, identities, storyboards, voices, compose) as ComfyUI custom nodes | **No** — it rebuilds the orchestration inside another framework (GOAL rule 2), duplicates DramaClaw's canvas, and ComfyUI's graph models model calls, not a story-to-film workflow |
| ComfyUI's patterns in our control page | job list with filters, progress, previews, errors panel, templates | **Yes** — already proven in ArcReel's run panel; adopted in M2b |
| DramaClaw's canvas as the visual workspace | the sponsor opens DramaClaw's canvas for hands-on visual work on images, video, audio of a project | **Yes** — a ComfyUI-like canvas made for this domain, already running (M0); linked from the control page |
| DramaClaw's UI in Vietnamese | add a `vi` locale (translated locale files + `"vi"` in `SUPPORTED`) | Valuable for one Vietnamese operator; it is a donor change (GOAL tolerance) → sponsor decision |
| ArcReel's frontend as the shell | reuse its React run panel against the connector | **No** for code — the components are bound to R2's API and would bring R2 back; **yes** for design: M2b copies the run panel's layout, words and patterns (recorded as "Why not ported: bound to R2's production-run API") |

## 3. Result for the plan

- M2b keeps its scope and adopts the ComfyUI/ArcReel patterns explicitly: run list with All / Active / Done / Failed,
  per-run actions (open, resume, copy error), progress per step, previews of every step's output, errors panel,
  start templates (idea sources D22).
- The control page links each project to its DramaClaw canvas and screens; the canvas is the visual workspace.
- Open for the sponsor: translate DramaClaw's UI to Vietnamese (donor change, locale files + one line).

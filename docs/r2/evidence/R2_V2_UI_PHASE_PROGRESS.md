# V2 whole-app UI phase — progress log (durable checkpoint)

Resume rule: read this file first, then `git log --oneline -10` on `release/r2-v2-story` (worktree `.worktrees/r2-v2-story-release`). Every step below is committed and pushed to `r2-v2/main` when it finishes. Plan: `R2_V2_UI_CRITIQUE_2026-10-23.md` § Next phase.
Design priority: fully automatic, with Human monitoring and intervention at any important decision (memory `autonomy-with-oversight-design`).

## Decided stage model (source of truth)
`docs/r2/R2_01_FROZEN_ARCHITECTURE.md` §2 North Star loop:
DISCOVER → RESEARCH → CREATE/CANON → ADAPT/SCRIPT → DIRECT → PREPARE → PRODUCE → EVALUATE → PACKAGE/DISTRIBUTE → MEASURE/LEARN → next iteration.
Story authoring is CREATE/CANON (step 3), not step 0 (Human correction 2026-10-23). The current workspace stepper (Chuẩn bị / Kịch bản / Sản xuất / Hoàn thành) is upstream V1's and does not follow this loop.

## Steps
- [x] 0. Stage model located (this file).
- [x] 1. Inventory (below).
- [x] 2. Design (impeccable shape + /frontend-design): stepper on the North Star loop, pipeline control center on Overview, decision inbox, activity center.
- [x] 3. Implement + tests, in small committed slices.
- [x] 4. App-wide audit fixes (header labels, mobile overflow, /episodes empty state, 422/409, Vietnamese serif).
- [~] 5. Re-run critique app-wide (Chrome overlay + detector over all src) vs 22/40.
- [~] 6. Tag + Human deploy: r2-v2.0.4 tagged; deploy pending Human (sudo m8e-review-stop.sh; sudo v2-deploy.sh r2-v2.0.4).

## Inventory: North Star stage → V2 surfaces and server workflow steps
| Stage | V2 surfaces (routes) | Server workflow steps (`lib/workflow_plan.py`) |
|---|---|---|
| DISCOVER | none | none |
| RESEARCH | none (ResearchPack/ClaimLedger factual path not built) | none |
| CREATE/CANON | Viết truyện `/story`, Tệp gốc `/source`, Tổng quan (overview analysis), lorebook/clues routes | (source admission, overview) |
| ADAPT/SCRIPT | Tập `/episodes/:n` (script review) | episode_plan, script_plan_content, script_plan_review, final_script |
| DIRECT | storyboard / canvas, Định dạng `/formats` (M8) | storyboard |
| PREPARE | Nhân vật / Cảnh / Đạo cụ / Sản phẩm | asset_inventory, asset_sheets |
| PRODUCE | timeline, narration, video units | narration_delivery, video |
| EVALUATE | Gates (script lock, final cut), reviews | (gates) |
| PACKAGE/DISTRIBUTE | Xuất (export, Jianying draft), formats | (export) |
| MEASURE/LEARN | Học từ dữ liệu `/learning` | none |
Current header stepper reads only `status.phase` ∈ {preparation, script, production, completed} (frontend/src/types/project.ts PHASE_ORDER; PhaseStepper.tsx). The workflow plan carries per-step states (completed/ready/active/blocked/pending/skipped) and is the richer server truth for a North Star stepper.
Human decisions 2026-10-23: DISCOVER/RESEARCH shown muted as "Sắp có" (coming soon); order = North Star stepper + pipeline control center first, then app-wide fixes.

## Log
- r2-v2.0.5 tagged (includes v2.0.3 + v2.0.4 + operations overview, gates, provider note). Deploy pending Human: `sudo bash ~/arcreel-v2-staging/m8e-review-stop.sh; sudo bash ~/arcreel-v2-staging/v2-deploy.sh r2-v2.0.5`. Open: full critique re-run, Gates A–D in the cross-project inbox, per-chapter story progress (backend), V3 per R2_V2_CAPABILITY_AND_V3_BOUNDARY.md.
- Slices (b)+(c) done: pipeline board shows Gates A/B/D latest decision from gate history (C is per episode), "always your decision" label, and a "no video provider configured" note derived via useModelCapabilities (repo rule). Next: tag r2-v2.0.5, deploy pending Human; full critique deferred.
- Slice (a) done: cross-project "Vận hành" overview on the projects page (frontend/src/components/pages/operations/): decisions waiting (story runs) across projects, running work per project (story runs + running/queued tasks), each project's North Star stage; read-only, polls every 30 s, states the gate boundary. Gates A–D in the inbox still pending (needs per-project gate state). Next: (b) gates + (c) provider readiness on the pipeline board.
- 2026-10-23: Human asked to re-read research/decisions and separate V2 from V3 before finishing the UI. Wrote docs/r2/R2_V2_CAPABILITY_AND_V3_BOUNDARY.md. Next UI slices, all read-only views over existing owners: (a) cross-project operations view + decision inbox on the projects page, (b) gates on the pipeline board, (c) provider readiness on Produce, (d) automation-boundary copy.
- Step 5 (lite): detector over all frontend/src found 9 legacy findings (side-tab 4, codex-grid-background 2, gray-on-color 1, layout-transition 1, bounce-easing 1), none in changed areas. A full critique (sub-agent A + Chrome overlay) is deferred to a session with quota. r2-v2.0.4 tagged.
- Step 4 done: mobile projects page no longer scrolls horizontally (390px viewport measured 758 → 390); workspace on mobile 390 with the board visible. Load errors: the only failing request is GET video-capabilities 422 (no video provider configured, a valid server refusal); follow-up idea: show "no video provider" on the Produce stage. Next: step 5 critique re-run (Chrome overlay + detector over all src), then tag r2-v2.0.4.
- Step 4b done: bare /episodes redirects to the overview; header icon buttons already carry aria-label/title (no change); <html lang> follows i18n and a Vietnamese UI uses Noto Serif (loaded) as the editorial face. Remaining step 4: 422/409 on load, mobile projects page overflow.
- Step 4a done: below 768px the agent panel becomes a full-width overlay that starts closed (not persisted) and the sidebar collapses to icons (frontend/src/hooks/useNarrowViewport.ts, StudioLayout.tsx, AssetSidebar.tsx). Remaining step 4: /episodes empty state, header icon labels, 422/409 on load, Vietnamese serif, mobile projects page overflow.
- Visual check done (vite dev on :5199 proxying to production, Playwright desktop+mobile). Fixed: next-step line used the dashboard namespace (raw "next_step"), world setting snake_case, script_structure→adapt, export→package. The board is correct against the real plan (server gates episode_plan behind asset_inventory). Found for step 4: on mobile the workspace shows only the agent panel and the header overlaps.
- Slice 2 done: pipeline control center on Overview (frontend/src/components/canvas/pipeline/: pipeline-stages.ts aggregates server workflow steps + story runs per stage; PipelineBoard shows 10 stages with state, next action (nextStepForAction), "Chờ bạn quyết định" and "Đang chạy" lists). Next: one visual check (desktop+mobile), then step 4 app-wide fixes.
- Slice 1 done: header stepper follows the North Star loop (frontend/src/components/layout/PhaseStepper.tsx; 10 stages, current pill + dots, DISCOVER/RESEARCH dashed "Sắp có"; current stage mapped from server status.phase: preparation→create, script→adapt, production→produce, completed→package). Next: slice 2 pipeline control center on Overview from the workflow plan.
- 2026-10-23: r2-v2.0.3 tagged (story UI P0/P1), deploy pending Human. Phase started.

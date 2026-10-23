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
- [ ] 2. Design (impeccable shape + /frontend-design): stepper on the North Star loop, pipeline control center on Overview, decision inbox, activity center.
- [ ] 3. Implement + tests, in small committed slices.
- [ ] 4. App-wide audit fixes (header labels, mobile overflow, /episodes empty state, 422/409, Vietnamese serif).
- [ ] 5. Re-run critique app-wide (Chrome overlay + detector over all src) vs 22/40.
- [ ] 6. Tag + Human deploy.

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
- 2026-10-23: r2-v2.0.3 tagged (story UI P0/P1), deploy pending Human. Phase started.

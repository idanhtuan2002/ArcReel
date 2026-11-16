---
target: ArcReel studio (frontend)
total_score: 20
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 5
timestamp: 2026-11-16T05-49-46Z
slug: frontend-src-components-layout-studiolayout-tsx
---
⚠️ DEGRADED: single-context (repo policy caps background agents; user did not request sub-agents)

# ArcReel studio UX/UI critique: r2-v2.5.49 on 2026-11-16

Heuristics: 1 status 2; 2 real world 2; 3 control 2; 4 consistency 2; 5 error prevention 2; 6 recognition 2; 7 efficiency 3; 8 minimalist 2; 9 error recovery 1; 10 help 2. Total 20/40 (Acceptable, low end).

Design specificity: the Darkroom language (mono kickers, dark surfaces, stage chips) is product-specific. The information architecture, though, exposes the engine (stages, gates, generations, qualification, raw reason codes) rather than the creator's job (my story, my films, what do I do next).

Detector: 9 findings in frontend/src.
- side-tab ×4: NarrationAudioCard:81, ShotDetail:954, AgentHandoffHint:168, styles.css:268.
- codex-grid-background ×2: app.css:68, canvas.css:51.
- gray-on-color: MentionPicker:291.
- layout-transition: AssetSidebar:236, width transition.
- bounce-easing: studio.css:297.

Priority issues:
- P1: the finished film is hidden behind a run selector that defaults to the latest run.
- P1: raw reason codes with no plain explanation or next step (ADAPTATION_FAILED, MEDIA_RETRY_LIMIT…).
- P1: contradictory status. The header stepper and the project list say "Kịch bản" for a project whose episode 1 is exported. "Bị dừng" plus "Đang tắt" plus a blocked run make "is autopilot broken?" unanswerable.
- P1: mixed languages: Chinese document title and episode titles, English NARRATION and section headers, Vietnamese UI.
- P1: a user can regenerate assets while a run is in MEDIA with no warning. This happened in trial 7: 6 regenerations led to all storyboards and videos being redone.
- P2: overview cognitive overload: 10 stages, 4 gates, 15 stage chips, 3 expanders and 4 run filters.
- P2: the floating assistant button overlaps "Chỉnh sửa" and the episode page's top links.
- P2: a delete icon is always visible on every project row.
- P2: cost cards show only dashes; the header cost button renders as "–".

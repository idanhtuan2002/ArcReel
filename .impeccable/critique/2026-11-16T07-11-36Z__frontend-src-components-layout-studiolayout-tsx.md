---
target: ArcReel studio (frontend)
total_score: 28
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 0
timestamp: 2026-11-16T07-11-36Z
slug: frontend-src-components-layout-studiolayout-tsx
---
⚠️ DEGRADED: single-context (repo policy caps background agents)

# ArcReel studio UX/UI re-critique after r2-v2.5.50 and 2.5.51 (2026-11-16)

Heuristics: 1 status 3; 2 real world 3; 3 control 3; 4 consistency 3; 5 error prevention 3; 6 recognition 3; 7 efficiency 3; 8 minimalist 3; 9 error recovery 3; 10 help 2. Total 28/40 (Good; up from 20/40).

Remaining priority issues:
- P2: the header stepper and the project list's "Giai đoạn" still read the workflow phase ("Kịch bản") while the status card says episode 1 is finished and episode 2 stopped. There are two sources of status.
- P2: recovery advice is text. A one-click action (reset the plan from this episode, open writer model settings) would close the loop.

Limitations:
- The mobile layout was not verified (the resize tool did not apply).
- The new Chinese UI copy awaits the user's review.

Detector: 8 findings.
- False positives (2): MentionPicker gray-on-color sits on different branches; AgentHandoffHint is a CSS arrow.
- Intentional (3): the narration quote rules and the code block rule; the canvas grid background.
- Mitigated (1): the sidebar width transition now respects reduced motion.

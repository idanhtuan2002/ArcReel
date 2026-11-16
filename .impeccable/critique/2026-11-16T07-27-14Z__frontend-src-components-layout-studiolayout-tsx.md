---
target: ArcReel studio (frontend)
total_score: 31
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 0
timestamp: 2026-11-16T07-27-14Z
slug: frontend-src-components-layout-studiolayout-tsx
---
⚠️ DEGRADED: single-context (repo policy caps background agents)

# ArcReel studio UX/UI re-critique after r2-v2.5.52 (2026-11-16)

Heuristics: 1 status 4; 2 real world 3; 3 control 3; 4 consistency 3; 5 error prevention 3; 6 recognition 3; 7 efficiency 3; 8 minimalist 3; 9 error recovery 4; 10 help 2. Total 31/40 (Good; 20 → 28 → 31).

Verified in the browser on r2-v2.5.52:
- The header stepper reads "Kịch bản · tập 2".
- The project list's phase reads "Kịch bản · tập 2", consistent with 1/10 episodes done.
- The status card shows four actions: Tiếp tục, Đặt lại kế hoạch từ tập 2, Mở cài đặt model, Xem chi tiết vận hành.
- "Mở cài đặt model" opens the project settings.

Remaining:
- P3: "Mở cài đặt model" lands at the top of the project settings rather than at the model section; it needs a deep-link anchor.
- P3: help and documentation are unchanged; there is no contextual help at the blocked points beyond the card.
- Limitation: the mobile layout is still unverified. The Chinese copy awaits the user's review.

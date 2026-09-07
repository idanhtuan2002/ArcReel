# R2 Origin — Bộ tài liệu gốc (tầng lý do)

**Trạng thái:** Tầng lý do / nguồn gốc. **Không có thẩm quyền.**
**Ngày biên tập:** 2026-09-07. Biên tập từ các vòng thảo luận/nghiên cứu 2026-09-03 → 2026-09-07.

## Mục đích

Bộ 4 tài liệu này giải thích **vì sao** kiến trúc R2 đã đóng băng lại có hình dạng như hiện tại. Nó lấp "khoảng giữa" giữa nghiên cứu và kiến trúc:

```
RESEARCH → PRINCIPLE → REQUIREMENT → ARCHITECTURE → ROADMAP → IMPLEMENTATION
              └──────── bộ tài liệu này ────────┘
```

## Thứ tự đọc

| File | Trả lời câu hỏi |
|---|---|
| [`00_PRODUCT_VISION.md`](00_PRODUCT_VISION.md) | Chúng ta đang xây cái gì? |
| [`01_RESEARCH_SYNTHESIS.md`](01_RESEARCH_SYNTHESIS.md) | Toàn bộ nghiên cứu đã dạy chúng ta điều gì? |
| [`02_SYSTEM_REQUIREMENTS.md`](02_SYSTEM_REQUIREMENTS.md) | Vì các kết luận đó, hệ thống bắt buộc phải có capability nào? |
| [`03_ARCHITECTURE.md`](03_ARCHITECTURE.md) | Chúng ta xây chúng như thế nào? |

## Quan hệ với tài liệu đã FROZEN

Khi bộ này mâu thuẫn với `docs/r2/` (`FROZEN_V1`) hoặc một implementation plan `APPROVED`, **bản frozen thắng**. Cụ thể:

| Chủ đề | Bản frozen có thẩm quyền |
|---|---|
| Kiến trúc | `docs/r2/R2_01_FROZEN_ARCHITECTURE.md` |
| Ma trận trách nhiệm | `docs/r2/R2_02_FROZEN_RESPONSIBILITY_MATRIX.md` |
| Hợp đồng domain/state | `docs/r2/R2_03_FROZEN_DOMAIN_STATE_CONTRACTS.md` |
| Quyết định (LOCKED) | `docs/r2/R2_04_DECISION_REGISTRY.json` (`FROZEN_V1`) |
| Host hardening H1–H8 | `docs/r2/R2_05_FROZEN_HOST_HARDENING_REQUIREMENTS.md` |
| Roadmap M0–M8 | `docs/r2/R2_06_FROZEN_IMPLEMENTATION_ROADMAP.md` |

Các quyết định tạm (`R2-D07`…`R2-D45`, `D-B01`…`D-B08`) xuất hiện trong thảo luận gốc **đã được nâng lên LOCKED** trong `R2_04_DECISION_REGISTRY.json` với ID sạch hơn — xem crosswalk ở `03_ARCHITECTURE.md` §7.

## Nguồn

- Charter draft: `.../conten os/content_production_os_foundation_r2_2026-09-06/` (11 tài liệu `00`–`10`)
- Reuse map: `docs/research/2026-09-07-r2-reuse-map-and-completion-gates.md`
- R1 reality-check bundles: `.../conten os/content_production_os_r1_evidence_2026-09-06*/`
- R1.8 final host decision: `.../conten os/content_production_os_r1_8_final_2026-09-06.zip`

Log vận hành (Phase C0 fixes, R2-M0 task runs) **không** thuộc bộ này — chúng là log thực thi.

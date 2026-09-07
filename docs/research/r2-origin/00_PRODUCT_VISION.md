# 00 — Product Vision

**Trạng thái:** Tầng lý do. Không có thẩm quyền — xem [`README.md`](README.md).
Bản có thẩm quyền của tầm nhìn: `.../content_production_os_foundation_r2/01_PROJECT_CHARTER_R2.md` (14 locked invariants).

---

## 1. North Star

> Xây dựng một **AI-native Creative Production Operating System** biến một **cơ hội hoặc ý tưởng** thành một **IP/câu chuyện được quản lý bằng Canon**, rồi thành **nhiều dạng sản phẩm media hoàn chỉnh**, thông qua một production pipeline **reuse-first, hybrid, model-agnostic**; kiểm soát chất lượng và provenance xuyên suốt; phân phối ra thị trường; và dùng dữ liệu thực tế để cải thiện các vòng sáng tạo tiếp theo — trong khi **con người giữ quyền quyết định sáng tạo và quyền phát hành cuối cùng**.

Rút gọn:

```
Ý tưởng → câu chuyện → sản phẩm media hoàn chỉnh → thị trường → dữ liệu → câu chuyện tiếp theo
```

## 2. Đây KHÔNG phải là gì

| Không phải | Vì sao |
|---|---|
| "App tạo video" | Video chỉ là một output; nút thắt là giữ trạng thái tự sự/sản xuất/chất lượng/version/cost/quyền con người |
| "Tự động hóa YouTube" | YouTube là **production profile đầu tiên** để chứng minh kiến trúc, không phải đích đến |
| "AI viết truyện" | Viết truyện là một capability của cùng hệ thống |
| "Content farm" | Tối ưu **originality**, không tối ưu số lượng video |

Cả ba việc (tự động hóa YouTube, AI viết truyện, AI tạo video) chỉ là **capabilities của cùng một hệ thống**.

## 3. Đầu vào tối thiểu → đầu ra

Người dùng nhập một mục tiêu nhỏ:

- "Tạo một series YouTube/TikTok về chủ đề X"
- "Tạo một câu chuyện sci-fi dài 20 tập"
- "Tạo một IP sci-fi về AI mất kiểm soát"

Hệ thống đi gần như toàn bộ chu trình:

```
tìm cơ hội → nghiên cứu → chọn ý tưởng → viết truyện → kiểm tra canon
→ screenplay → storyboard → shot list → tạo nhân vật/bối cảnh
→ tạo video/voice/music → dựng → QA → thumbnail/title
→ xuất bản → lấy analytics → học từ kết quả → vòng tiếp theo
```

## 4. Vòng đời khép kín — 7 capability

```
                DISCOVER  ── What should we make?
                    │
                    ▼
                 CREATE   ── What is the story/content?        (Narrative Production OS)
                    │
                    ▼
                 DIRECT   ── How is it expressed visually/audibly?   (Director OS)
                    │
                    ▼
                PRODUCE   ── How do we manufacture every asset?      (Production OS)
                    │
                    ▼
               EVALUATE   ── Is it correct and good enough?         (QA/Evaluation OS)
                    │
                    ▼
              DISTRIBUTE  ── How does it reach the market?
                    │
                    ▼
                 LEARN    ── What did reality tell us?              (Analytics + telemetry)
                    │
                    └──────────────────────────→ DISCOVER
```

**Closed-loop ≠ bỏ con người.** Kỹ thuật có thể tự động hóa gần toàn bộ pipeline, nhưng để tạo sản phẩm chất lượng cao, nguyên bản và kiếm tiền bền vững, Human Creative Director giữ các approval gate.

## 5. Human-in-the-loop — 4 Gate ban đầu

| Gate | Vị trí | Câu hỏi |
|---|---|---|
| **A — Greenlight** | sau Idea | APPROVE ý tưởng? |
| **B — Narrative lock** | sau story/script | APPROVE tự sự? |
| **C — Final cut** | sau video | APPROVE bản dựng? |
| **D — Publish** | sau metadata + video | PUBLISH? |

Về sau, khi `confidence > 0.98 ∧ risk = LOW ∧ production_profile = proven`, Gate B/C có thể auto. **Không bắt đầu với zero-human.**

## 6. Nguyên tắc chủ đạo

> **Machines execute. Agents decide. Humans govern.**

| Vai | Ví dụ |
|---|---|
| execute (máy) | FFmpeg, H3/Seedance render |
| decide (agent) | LLM reasoning, Director planning, QA inspection |
| govern (người) | approve, Canon commit, final cut, publish |

## 7. Một IP → nhiều production profile

```
                    ONE IP  (World: "Project Aurora")
                       │
   ┌─────────┬─────────┼─────────┬──────────┬─────────┐
 Novel    Audiobook  YouTube   TikTok    Podcast   Short drama → Film
```

Đây **không phải 7 project khác nhau** — là **một Canon/IP + nhiều production profile**. Ví dụ:

| Profile | Đặc trưng |
|---|---|
| YouTube Explainer | research-heavy, narration-heavy, screen recording + graphics, ít generative video |
| AI Drama | character/location bible, dialogue, shot continuity, heavy generative video |
| Shorts/TikTok | 9:16, pacing nhanh hơn, subtitle lớn, hook < 2s — Director tạo shot **khác**, không chỉ crop |

## 8. Không phải content farm

YouTube (2026) chống nội dung AI generic, repetitive, templated, mass-produced; từ 5/2026 disclosure AI hiển thị nổi bật hơn. Nội dung AI **có góc nhìn độc đáo / câu chuyện nguyên bản / giá trị sáng tạo** vẫn được monetize.

> Mục tiêu: AI giảm **90% labor**, giữ **100% creative intent + 100% provenance + 100% quality gate**. Không phải "100 video/ngày".

## 9. Ước lượng khả năng tự động hóa (đánh giá kỹ thuật, không phải benchmark)

| Loại sản phẩm | Automation khả thi |
|---|---|
| TikTok/Shorts, Podcast video | 95%+ |
| YouTube faceless tech/explainer | 90–95% |
| Documentary faceless, Motion graphic explainer | 85–95% |
| AI animated story | 80–90% |
| AI short drama | 75–90% |
| AI short film cinematic | 65–80% |
| Long cinematic movie | 50–70% |
| Feature film chất lượng cao | chưa nên chạy hoàn toàn autonomous |

**Vì sao YouTube explainer dễ nhất:** không cần mọi giây là generative video. Một video 10 phút có thể gồm ~25% screen recording, ~20% screenshots, ~15% graphics, ~15% stock, ~15% generated images, ~10% generated video — chất lượng thường **tốt hơn** 100% AI video.
**Vì sao fiction khó hơn:** cần character/costume/location consistency + performance + dialogue + camera + continuity.

## 10. Con trỏ

- 14 locked invariants + North Star chi tiết: `01_PROJECT_CHARTER_R2.md`
- Roadmap thực thi M0–M8: `docs/r2/R2_06_FROZEN_IMPLEMENTATION_ROADMAP.md`
- Yêu cầu hệ thống suy ra từ tầm nhìn: [`02_SYSTEM_REQUIREMENTS.md`](02_SYSTEM_REQUIREMENTS.md)

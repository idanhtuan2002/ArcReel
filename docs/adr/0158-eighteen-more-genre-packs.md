---
status: accepted
---

# Eighteen more genre packs

Decided 2026-11-15 on the sponsor's catalog decision (`docs/r2/R2_CONTENT_FORMS_CATALOG.md`: cover every known genre; popular TikTok/YouTube forms first). Supersedes the line of ADR-0119 that left huohuo's cultivation, system and officialdom genres out.

1. 18 packs join the 10: báo thù – vả mặt, ngược luyến, tổng tài – hào môn, xuyên không – trọng sinh, tu tiên – tiên hiệp, võ hiệp – kiếm hiệp, hệ thống – game, mạt thế – sinh tồn, dị năng, đô thị, quan trường – thương chiến, gián điệp, trừ tà – tâm linh, điền văn – làm giàu, não động – cú lừa (from huohuo `agent-skills/novel_{premise,outline,writing_brief,chapter_writer}/<genre>/SKILL.md` @ f104b85, rewritten in Vietnamese for a 3-chapter story), and chuyện có thật – đời thường, thiếu nhi – cổ tích – ngụ ngôn, truyện ngủ ngon (no donor pack; general craft). Each has planning and craft rules, worn phrases and a film look (`film_looks.py`).
2. Specific packs come before the general ones in `PACKS`, so a genre text naming both ("võ hiệp", also action's word) takes the specific pack; aliases that would pull unrelated stories ("kể chuyện", "làng quê", "trẻ em", "thư giãn", "đau lòng") are left out.
3. The idea draw spreads over all 28 packs; the seed's genre menu lists all labels.

Evidence: draft and the donor lines adapted in the session's scratchpad (`genre-packs-draft.md`), reviewed by the main agent; tests `test_a_specific_genre_takes_its_own_pack_over_a_general_one`, story_authoring unit + integration, idea draw, story adapter, autopilot batch.

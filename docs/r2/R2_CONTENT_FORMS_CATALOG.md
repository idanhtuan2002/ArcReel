# Content forms and genres catalog (living list)

Owner: sponsor. Created 2026-11-15. Update in place when a form or genre is added or its status changes.

**Sponsor decisions (2026-11-15):**
1. The goal is coverage of **every known genre and form**, including **remakes, recaps and summaries of other people's videos turned into a variant** of that video.
2. Order of work: first the genres and formats popular on **TikTok and YouTube now**, by value per effort; then the rest.
3. Quality first; free tiers; licence out of scope (`CLAUDE.md`).
4. Languages: products in several languages, Vietnamese is one of them; priority **Vietnamese first, then English, then Chinese** (2026-11-15). Genre packs keep one id with content per language: `vi` adapted, `zh` close to huohuo's original skills, `en` rewritten for that market; a story uses the pack content of its own language, never another language's prompt (prompt language pulls the output language).

Design constraint from the platforms (not a block): YouTube monetizes reused content only when "viewers can tell that there's a meaningful difference"; allowed examples include "Edited footage from other creators where you add a storyline and commentary" and "A scene from a movie where you've rewritten the dialog and changed the voiceover"; not allowed: clips "with little or no narrative", "readings of other materials you did not originally create", "Image slideshows, templated storylines, or scrolling text with minimal or no narrative" ([YouTube channel monetization policies](https://support.google.com/youtube/answer/1311392), read 2026-11-15). So every remake/recap form here produces a **transformed** work: a new storyline, rewritten narration or dialogue, new voice; never a re-upload or a verbatim reading.

Status: ✅ shipped and run · 🟡 parts exist, not run end to end · ❌ missing. Effort S/M/L. Donor evidence: `docs/research/2026-11-15-r2-donor-forms-inventory.md`; gap analysis: `docs/research/2026-11-15-r2-forms-genres-video-types-vs-vision.md`.

## A. Story genres (fiction)

| # | Genre (vi / en) | Status | Donor reference |
|---|---|---|---|
| G1 | Tâm lý – gia đình / family drama | ✅ pack `family` | HH 种田 (partial) |
| G2 | Trinh thám – phá án / mystery, detective | ✅ `mystery` | HH 悬疑 |
| G3 | Kinh dị / horror | ✅ `horror` | HH 诡异 |
| G4 | Ngôn tình – tình cảm / romance | ✅ `romance` | HH 言情 |
| G5 | Hành động – phiêu lưu / action-adventure | ✅ `action` | — |
| G6 | Kỳ ảo – huyền huyễn / fantasy | ✅ `fantasy` | HH 玄幻 |
| G7 | Khoa học viễn tưởng / sci-fi | ✅ `scifi` | HH 科幻 |
| G8 | Hài / comedy | ✅ `comedy` | SB 轻喜剧 |
| G9 | Lịch sử – cổ trang / historical | ✅ `historical` | HH 历史 (planned), DC palace looks |
| G10 | Học đường – thanh xuân / school, youth | ✅ `school` | HH 校园 |
| G11 | Báo thù – vả mặt / revenge, face-slapping | ✅ pack (ADR-0158), not yet run | HH 爽文 serial pulse, SB highpoint |
| G12 | Ngược luyến / angst romance | ✅ pack (ADR-0158), not yet run | HH 虐恋 |
| G13 | Tổng tài – hào môn / CEO, rich-family romance | ✅ pack (ADR-0158), not yet run | DC urban_romance looks |
| G14 | Tu tiên – tiên hiệp / xianxia, cultivation | ✅ pack (ADR-0158), not yet run | HH 仙侠, SB power-system |
| G15 | Võ hiệp – kiếm hiệp / wuxia | ✅ pack (ADR-0158), not yet run | HH 武侠 |
| G16 | Xuyên không – trọng sinh / transmigration, rebirth | ✅ pack (ADR-0158), not yet run | HH 穿越 |
| G17 | Hệ thống – game / system, LitRPG | ✅ pack (ADR-0158), not yet run | HH 游戏 |
| G18 | Mạt thế – sinh tồn / apocalypse, survival | ✅ pack (ADR-0158), not yet run | HH 末世 |
| G19 | Dị năng – siêu năng lực / superpowers | ✅ pack (ADR-0158), not yet run | HH 异能 |
| G20 | Đô thị / urban | ✅ pack (ADR-0158), not yet run | HH 都市 (planned) |
| G21 | Quan trường – thương chiến / office, business politics | ✅ pack (ADR-0158), not yet run | HH 官场 |
| G22 | Gián điệp / spy, espionage | ✅ pack (ADR-0158), not yet run | HH 谍战 |
| G23 | Trừ tà – tâm linh / exorcism, spiritual | ✅ pack (ADR-0158), not yet run | HH 驱魔 |
| G24 | Điền văn – làm giàu / slow life, farming | ✅ pack (ADR-0158), not yet run | HH 种田 |
| G25 | Não động – twist / high-concept, twist ending | ✅ pack (ADR-0158), not yet run | HH 脑洞 |
| G26 | Thiếu nhi – cổ tích – ngụ ngôn / children's, fairy tale, fable | ✅ pack (ADR-0158), not yet run | VM audience adaptation |
| G27 | Truyện ngủ ngon / bedtime, sleep stories | ✅ pack (ADR-0158), not yet run | — |
| G28 | Truyện có thật – đời thường (storytime) / real-life storytime, slice of life | ✅ pack (ADR-0158), not yet run | TikTok Next 2026 "Reali-TEA" |
| G29 | Tình cảm gia đình – cảm động / tearjerker, wholesome | 🟡 via `family` | — |
| G30 | Hài – chế / parody | ❌ | — |
| G31 | Fanfic / spinoff of an existing work | 🟡 variants of own stories | SB review-fanfic/spinoff |
| G32 | Tương tác – rẽ nhánh / interactive, branching | ❌ | DC README claim only |

## B. Non-fiction and factual genres

| # | Genre | Status | Donor reference |
|---|---|---|---|
| N1 | Lịch sử kể chuyện / history narration, documentary | ✅ ADR-0162 (sourced narration → film path) | OM documentary-montage |
| N2 | Án có thật / true crime | ✅ ADR-0162 | OM documentary |
| N3 | Giải thích – giáo dục / explainer, educational, "curiosity" | ❌ | OM animated-explainer, animation |
| N4 | Khoa học – vũ trụ / science, space | ❌ | OM |
| N5 | Bí ẩn – thuyết âm mưu – sự thật thú vị / mysteries, fun facts | ✅ ADR-0162 (facts only from sources) | OM |
| N6 | Top list / xếp hạng, trivia, quiz | ❌ | OM |
| N7 | Tiểu sử / biography | ✅ ADR-0162 | OM explainer |
| N8 | Tài chính – công nghệ (giải thích, không tư vấn) / finance, tech explainers | ❌ | OM |
| N9 | Tin tức – bình luận / news commentary | ❌ | — |
| N10 | Động lực – trích dẫn / motivation, quotes | ❌ | — (YouTube "templated" risk) |
| N11 | Hướng dẫn – mẹo / how-to, tips, cooking hacks | ❌ | OM screen-demo |

## C. Video and output forms

| # | Form | Status | Donor reference |
|---|---|---|---|
| V1 | Truyện chữ / novel, serial text | ✅ | HH, SB, NS |
| V2 | Phim kể chuyện ảnh + chuyển động máy / narrated motion comic | ✅ `fiction_narration_vi_v1` | HH, OM, DC |
| V3 | Sách nói / audiobook (chapters, music) | ✅ ADR-0159 (`standard`) | — |
| V4 | Phim drama có thoại, giọng riêng nhân vật / dialogue drama | 🟡 `fiction_drama_vi_v1` (F3) | HH, DC, VM |
| V5 | Phim trộn ảnh + video AI / hybrid motion | ❌ (F4) | OM, VGA, HH |
| V6 | Phim ngắn dọc nhiều tập / vertical micro-drama series | 🟡 episodes, hook < 4 s, burned captions, title and next-episode cards ✅ (ADR-0160); motion ❌ | DC, HH |
| V7 | Hoạt hình / anime, cartoon, chibi | 🟡 18 anim styles; motion ❌ | HH, OM, DC |
| V8 | Người thật – điện ảnh / live-action cinematic | 🟡 18 live styles; motion ❌ | HH, DC |
| V9 | Quảng cáo sản phẩm / product ad, UGC-style ad | 🟡 `content_mode=ad` (F5) | OM, AIVPE, Topview |
| V10 | Trailer – teaser | ❌ (F6) | OM cinematic |
| V11 | Explainer có đồ họa tất định / explainer with charts, diagrams, kinetic text | ❌ (F7) | OM animation, Remotion |
| V12 | Documentary montage (stock + narration) | ❌ | OM documentary-montage |
| V13 | Remake / recap / tóm tắt video người khác thành biến thể (cốt truyện, lời kể, giọng mới) | 🟡 video → story source ✅ (ADR-0161), variant + film via ADR-0115 path; footage-cut recap ❌ | OM video analysis + clip-factory, Topview recast, DC canvas analysis |
| V14 | Review – reaction có bình luận / review, reaction with commentary | ❌ | OM |
| V15 | Lồng tiếng – dịch video / dub, localization | ❌ | OM localization-dub |
| V16 | Podcast video – audiogram / podcast repurpose | ❌ | OM |
| V17 | Người dẫn ảo – talking head / avatar presenter, lip sync | ❌ | OM (Wav2Lip, SadTalker) |
| V18 | Cắt clip ngắn từ video dài / clip factory | ❌ | OM |
| V19 | Quay màn hình – demo / screen demo | ❌ | OM |
| V20 | Nhạc – MV lời / music video, lyric video | ❌ | OM (music tools only) |
| V21 | ASMR – thư giãn – nhạc ngủ / ambience, sleep, relaxation | 🟡 sleep story ✅ ADR-0159 (`sleep`); ASMR/music-only ❌ | — |
| V22 | Slideshow ảnh có lời / photo story | 🟡 (= V2 without moves; YouTube "slideshow" risk) | HH |

Formats per platform: 9:16 Shorts/TikTok/Reels ✅, 16:9 YouTube ✅, 1:1, 4:5, 21:9 🟡 (aspect parsed generically; not run).

## C2. Languages

| # | Language axis | Status | Effort | Note |
|---|---|---|---|---|
| L1a | English film via the translation path: story (vi) → translation (ADR-0120) → English narration (Gemini TTS) → English subtitles and packaging | 🟡 translation ✅, English TTS route ✅ (ADR-0156), film path not run in English | S–M | First English products |
| L1b | Native English story authoring: prompts, checks (word counts, pronouns, names), genre packs `en`, English voices | ❌ | L | Quality beyond translation |
| L2a | Chinese film via the translation path (Gemini TTS speaks Chinese) | 🟡 | S–M | After L1a |
| L2b | Native Chinese authoring with genre packs `zh` from huohuo's skills (near verbatim) | ❌ | L | After L1b |

Re-ranked 2026-11-15 on measured cost: local i2v (Wan 2.2 5B GGUF, RTX 2070) takes ≈ 250 s for 49 frames (≈ 2 s of video) (`docs/r2/evidence/media-local-2026-10-30/wan-2.2/timing-summary.json`), so a whole episode in motion costs hours and still gives 2 s moves; Seedance free quota is ≈ 18 clips once and its adapter is `UNQUALIFIED`. Ranks 4–5 (hybrid motion, dialogue drama, both need generated video) move after ranks 6–11, which need no video model; the first motion step is a short motion insert on 1–3 key shots per episode. Per-shot motion also needs a queue/worker design (`docs/r2/evidence/R2_CRAFT_QUALITY_PROGRAM.md` "Catalog progress").

## D. Popular now on TikTok and YouTube (evidence)

- TikTok Next 2026 (official, `ads.tiktok.com/business/library/TikTok_Next_2026_Trend_Report.pdf`, 17 pp.): theme "Irreplaceable Instinct"; signals **Reali-TEA** (relatable real-life stories, "chaotic trip lore", #storytimes), **Curiosity Detours** (search-led discovery, "new rabbit holes", educational answers), **Emotional ROI** (purchase with a reason). INFER: storytime, curiosity/explainer and reason-to-buy product videos.
- YouTube policy (above): original stories visualized with AI are monetizable; series with "a distinct storyline" per episode are fine; templated slideshows and verbatim readings are not.
- Third-party, directional only (vendor blogs, conflicting numbers): AI-narrated revenge/betrayal drama stories lead faceless drama uploads ([outlierkit](https://outlierkit.com/resources/youtube-drama-trends-2026/)); micro-drama audience concentrated in emotional romance genres ([pinedrama](https://pinedrama.com/blog/tiktok-short-dramas-romance-fantasy-ai-content-trends)); history, sleep, space evergreen; true crime and history mid RPM, finance/tech highest CPM ([revid](https://www.revid.ai/blog/best-faceless-youtube-niches), [outlierkit faceless](https://outlierkit.com/resources/faceless-youtube-channels/)).

## E. Order of work (popular first, by value per effort)

| Rank | Item | Covers | Effort | Why this rank |
|---|---|---|---|---|
| 1 | Genre packs for the popular fiction: báo thù–vả mặt, ngược luyến, tổng tài–hào môn, xuyên không–trọng sinh, tu tiên, hệ thống, mạt thế, đô thị, truyện có thật–storytime, thiếu nhi–cổ tích, truyện ngủ ngon, não động–twist (+ film look each) | G11–G28 | S | The most uploaded faceless story types; runs on the shipped narration path now |
| 2 | Audiobook + sleep-story output | V3, G27, V21 | S | All parts exist; evergreen sleep/relax niche |
| 3 | Micro-drama series polish: cliffhanger per episode, hook in the first 2 s, series packaging | V6 | S–M | Short-drama growth; episodes already exist |
| 4 | Hybrid motion (stills + selective i2v) | V5, V7, V8 | M | Lifts every fiction form above "slideshow" (policy and retention) |
| 5 | Dialogue drama end to end with per-character voices | V4 | M | AI drama is the next fiction tier |
| 6 | Recap / remake as a transformed variant: ingest a video (download, scene cut, transcript), rewrite the storyline and narration, new voice, own visuals or transformed clips | V13, V14 | M–L | Sponsor decision; very popular; transformation built in |
| 7 | History / true crime / mysteries documentary narration with sourced facts | N1, N2, N5, V12 | M–L | Evergreen, higher RPM; needs a fact pack |
| 8 | Explainer / curiosity (charts, diagrams, kinetic text) | N3, N4, N8, V11 | L | TikTok "Curiosity Detours"; vision's first profile |
| 9 | Top list / trivia / quiz | N6 | M | Popular; template risk managed by narrative |
| 10 | Product ad (reason-to-buy) | V9 | M | TikTok "Emotional ROI" |
| 11 | Trailer / teaser | V10 | S–M | Packaging for every story/film |
| 12 | Languages, in order: English (L1a translation path, then L1b native), then Chinese (L2a, L2b) | C2 | S–M, then L | Vietnamese forms come first (sponsor priority) |
| 13 | Dub / localization; clip factory; podcast; avatar presenter; screen demo; music video; news commentary; motivation; parody; interactive | V15–V20, N9–N11, G30, G32 | L | Breadth after the above |

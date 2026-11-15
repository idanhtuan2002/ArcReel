# Forms, genres and video types: the original vision, the donors and ArcReel today (2026-11-15)

Asked by the sponsor: "chuẩn bị để app sẵn sàng với tất cả các hình thức, thể loại truyện, video phim mà các donor hỗ trợ được; đối chiếu với các ý tưởng, mục đích xây dựng app ban đầu". Quality first (sponsor rule of 2026-11-15); free tiers only; licence out of scope.

Sources: the vision `docs/research/r2-origin/00_PRODUCT_VISION.md`, `02_SYSTEM_REQUIREMENTS.md`, `docs/r2/R2_V2_CAPABILITY_AND_V3_BOUNDARY.md`; the donor inventory `docs/research/2026-11-15-r2-donor-forms-inventory.md` (source read at pins, FACT/PER-DOC/UNKNOWN); ArcReel at `r2-v2.5.25` (paths below). FACT = read in source or measured; INFER = reasoning; UNKNOWN = not established.

## 1. What the app was built for (vision, FACT)

- **One IP, many production profiles**: Novel, Audiobook, YouTube (explainer), TikTok/Shorts, Podcast, Short drama → Film (`00_PRODUCT_VISION.md` §7). YouTube is "the first production profile to prove the architecture", not the goal (§2).
- **Production Method Router** per shot: `REUSE / STOCK / SCREEN_CAPTURE / DETERMINISTIC / GENERATED_IMAGE / GENERATED_VIDEO / COMPOSITE`, chosen before any model (`02_SYSTEM_REQUIREMENTS.md` R-A5.1, R-A5.5, R-A5.6). "Not every second is generative video": the vision's own estimate puts explainers at 85–95 % automatable and AI short drama at 75–90 %.
- **Shot ≠ generation**: candidates V1..Vn per shot, approved master (R-A4.3); visual identity profiles and variants (R-A4.5).
- Fiction is harder than explainers because of character/costume/location consistency, performance, dialogue, camera and continuity (§9).

## 2. Coverage matrix (ArcReel status: ✅ shipped and run · 🟡 exists, not run end-to-end or partial · ❌ missing)

| Row | Vision | Donors that do it (mechanism) | ArcReel today |
|---|---|---|---|
| Idea → story | ✓ | HH, VM, SB, NS, BX | ✅ story authoring (3 chapters), autopilot |
| Novel / long serial (text out) | Novel profile | HH, SB, NS, BX, InkOS | ✅ book parts, continuation, 7 variants, translation (ADR-0116..0120) |
| Novel / script in → film | ✓ | HH, DC (Fountain), VM, AIDrama | ✅ upload source → episode adaptation (ADR-0114); screenplay-as-source 🟡 (treated as prose) |
| Genre machinery | Genre stage (R-A3.4) | HH only: 21 webnovel genres, per-genre prompt packs per agent | 🟡 10 Vietnamese packs (family, mystery, horror, romance, action, fantasy, scifi, comedy, historical, school) + film look per genre (`film_looks.py`); missing xianxia/tu tiên, võ hiệp, mạt thế, hệ thống/game, đô thị, xuyên không, ngược luyến, quan trường, gián điệp, điền văn, thiếu nhi |
| Narration over stills (motion comic) | TikTok/Shorts | HH (FFmpeg zoompan), OM (Remotion), DC (narrated spine) | ✅ `fiction_narration_vi_v1`: stills + camera moves + grade + looks + music + ambience + cues (ADR-0140..0152) |
| Dialogue drama, per-character voices | AI drama | HH (per-line TTS + mux), DC (Seedance 2 voice references, clone), VM (audio in video prompt), DramaAgent (per-line delivery) | 🟡 `fiction_drama_vi_v1` exists (local Wan 2.2 5B i2v, VieNeu); character voice binding `prompt`/`reference_audio` (`lib/character_voice.py`); never run end-to-end |
| Generated video clips (i2v) | GENERATED_VIDEO | HH, OM (~25), TK (Seedance→H3 failover), DC, VM | 🟡 backends exist (ark, kling, vidu, gemini, dashscope, openai, grok, agnes, ComfyUI Wan); every cloud video adapter `UNQUALIFIED` (`r2/provider_capabilities/registry.json`); free quota: Seedance 1.0 pro-fast ≈ 18 clips once |
| Hybrid per shot (stills + some video) | Method Router R-A5.1/5.5 | OM (stills when no video), VGA motion_led vs source_led, HH two pipelines per episode | ❌ one video route per run (launch profile) |
| Vertical series, episodes, hooks | Short drama | DC (2:3, arcs), HH (episodes) | ✅ episodes, closing hooks in chapter plans, film batch per story |
| Visual styles | VisualIdentity | HH 34, DC 6+45, OM 5 | ✅ 36 templates (18 live, 18 anim) + per-genre film look |
| Character consistency | R-A4.5 | HH sheets/forms, DC identity library/3D, VM portraits, TK refs | ✅ sheets, derivatives, 4-ref klein, face judge (ADR-0142..0151); Seedream ≤ 14 refs (ADR-0156) |
| Music / ambience / subtitles | Audio QA | OM, DC, HH BGM | ✅ ACE-Step, MMAudio, subtitles |
| Cloud image / voice | — | DC Seedream, OM many TTS | ✅ code (ADR-0156); 🟡 route canary pending |
| Voice cloning | — | DC, OM (ElevenLabs) | 🟡 `reference_audio` binding for the video model only |
| Lip sync / avatar presenter | Podcast, talking head | OM (Wav2Lip, SadTalker, Kling), Topview | ❌ |
| Audiobook | Audiobook profile | none as a pipeline (INFER: TTS + chapters + music) | ❌ (all parts exist: story, TTS, ACE-Step) |
| YouTube explainer / educational | **first profile** | OM `animated-explainer`, `animation` (ManimCE, Remotion), documentary montage (stock + CLIP) | ❌ (no research pack, no deterministic scenes); Remotion renderer exists (`r2/m3`) |
| Ad / product video | — | OM cinematic/hybrid/HyperFrames, AIVPE product refs, Topview | 🟡 `content_mode="ad"` and product assets exist (`lib/profile_manifest.py:59`, `artifact_planner.py:496`); no automatic launch profile |
| Trailer of a story/film | — | OM `cinematic` | ❌ |
| Podcast repurpose, clip factory, screen demo, dub of existing video | Podcast profile | OM only | ❌ |
| Existing video as reference/remake | — | OM analysis, DC canvas, Topview recast | 🟡 reference-video units (r2v) exist; analysis/remake ❌ |
| Interactive / branching | — | DC README claim only (UNKNOWN) | ❌ (not pursued: unverified) |
| Fanfic | — | SB only (text) | 🟡 variant profiles cover retelling; fanfic of external IP ❌ |

## 3. Reading of the gaps (INFER)

1. The shipped path (narration over stills) is the strongest row and is on par with or beyond the donors on finishing (moves, grade, looks, music, ambience, cues, face-ranked best-of-2).
2. The largest gap against the **vision** is not fiction but the first production profile it named: the YouTube explainer, and the Production Method Router that lets one film mix stills, generated video and deterministic scenes.
3. The largest gap against the **donors** for fiction is real motion: dialogue drama with per-character voices and i2v clips. The machinery exists (drama profile, backends, voice binding) but has never been run end to end; cloud video is gated (`UNQUALIFIED`) and its free quota is tiny (≈ 18 Seedance clips), so quality-first motion must be selective (hybrid), and local Wan 2.2 is the volume path.
4. Genre coverage is a prompt-pack gap: huohuo's catalog shows which Vietnamese-market genres are missing (tu tiên, võ hiệp, mạt thế, hệ thống, xuyên không, đô thị, ngược luyến…).
5. Audiobook is almost free: every part exists.

## 4. Plan, ordered by value per effort (each step: research done here → ADR → tests → release; quality gates unchanged)

| # | Step | Value | Effort | Reuse |
|---|---|---|---|---|
| F1 | **Audiobook profile**: a committed story → chaptered narration (VieNeu or Gemini TTS) + ACE-Step bed + chapter marks, exported as M4B/MP3 + MP4 with cover | Vision profile; near-free | S | TTS, music bed, story manifest |
| F2 | **Genre packs +10** (tu tiên, võ hiệp, mạt thế/sinh tồn, hệ thống/game, xuyên không, đô thị, ngược luyến, quan trường/thương chiến, gián điệp, thiếu nhi) with film looks | More story forms, Vietnamese market | S | huohuo per-genre skills (content adapted to Vietnamese), `genre_packs.py`, `film_looks.py` |
| F3 | **Drama end-to-end**: run `fiction_drama_vi_v1` on a story; per-character voices (VieNeu voices / Gemini 30 voices) for dialogue lines; fix what breaks | Real AI drama | M | HH per-line TTS + mux, DramaAgent per-line delivery |
| F4 | **Hybrid motion (Method Router lite)**: per shot choose still+move or i2v by a rule (opening hook, climax, action beats; budget of clips), local Wan 2.2 by default, Seedance for the few key shots once qualified | Motion where it matters, within free quota | M | VGA motion_led/source_led, HH two pipelines, OM stills fallback |
| F5 | **Ad / product launch profile** (`content_mode="ad"`): product refs (Seedream 14 refs), hook-first 15–30 s script, CTA end card | Commercial form | M | AIVPE product references, OM cinematic/hybrid |
| F6 | **Trailer** of a story/film: pick beats from the manuscript, cut existing shots + 2–3 new ones, music hit points | Distribution packaging | S–M | OM cinematic, existing shots |
| F7 | **Explainer profile** (vision's first): research pack with sourced facts (M9), narration script, deterministic scenes (charts/diagrams via Remotion), stills/stock | Vision's first profile | L | OM animated-explainer + documentary-montage, `r2/m3` Remotion |
| F8 | Podcast/talking head/avatar, lip sync, dub of existing video, clip factory | Breadth | L | OM pipelines (Wav2Lip/SadTalker local) |

Not planned: interactive/branching (claim only, UNKNOWN), fanfic of external IP (rights), recap of others' videos (rights/originality: the vision forbids trend remakes, R-A1.2).

## 5. Unknowns
- Wan 2.2 5B i2v quality and speed on the RTX 2070 for a whole drama episode (one proof clip exists, 2026-10-30).
- Gemini TTS daily free quota per model (not measured yet).
- Seedance qualification evidence requirements for `OFFLINE_VERIFIED` (ADR-0091) beyond the precedent document.

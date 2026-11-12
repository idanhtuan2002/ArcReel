# R2 film quality: synthesis of all donor research and low-cost cloud paths (2026-11-13)

Inputs (all in `docs/research/`; internal baseline is tag `r2-v2.5.16`):
- `2026-11-13-video-quality-donor-mechanisms.md` — new external donors (AIVPE, Calliope, ViMax HEAD, openfilm, OpenChatCut, open-edit, VGA, Kling/Seedance/Veo docs) + internal gap inventory I1–I7.
- `2026-11-13-cloud-cost-paths-for-quality.md` — official prices, GPU rental, cost per 60 s episode.
- Existing donor research at the tag: `2026-11-08-r2-donor-stage-mechanisms.md` (HUO, OM, TAKE, DC, VIMAX@63bb9c7, shenbi, ASF, BUT, JF; adoption table §12), `2026-11-08-r2-best-of-n-and-judge-retry-donors.md`, `2026-11-03-r2-stronger-models-for-automatic-quality.md`, `2026-10-30-media-providers-free-and-local.md`, the 2026-11-09/11 story-donor series.
- Two ChatGPT reports pasted by the sponsor (2026-11-13).

Sponsor direction (2026-11-13): finishing the project targets strong/cloud models; quality design must not be bounded by small local models; find the cheapest trial paths that still keep quality.

## 1. Facts

F1. The 2026-11-08 film-stage adoption table (§12 of the stage-mechanisms doc) is essentially unimplemented: no `slideshow_risk`, no failure-reason feedback into regeneration (`retry_guidance`/`promptFix`), no words-per-second narration budget, no identity-lock render preflight in `lib server r2` at `r2-v2.5.16` (git grep, 0 non-test hits). ADR-0114..0132 all went to the story side.
F2. `Zulgo/video-generation-automation` is derived from OpenMontage (its `NOTICE` line 4), an existing donor (OM, pinned 08e2151). Its slideshow-risk and delivery-promise mechanisms are OM's.
F3. ViMax moved on: at the pinned `63bb9c7` the best-image selector existed but was not called (stage-mechanisms §13); at HEAD `fd4b72e` `generate_and_select_best_image` calls `BestImageSelector` and is tested (`tests/test_image_selection.py`). Re-pin before reuse.
F4. Automatic production today = narration slideshow (I1), drama refused (I2), no music/SFX/ducking (I3), no TTS delivery control (I4), judge asks only line-to-picture fit (I5), no loudness normalization or caption design (I6) — see the donor-mechanisms doc, synthesis table.
F5. A cloud watch-reviewer already exists (`server/production_run/gemini_reviewer.py`); live probes on 2026-11-03 showed `gemini-3.6-flash` rejects real defects and `*-flash-lite` accepts them.
F6. The cheap cloud video/image models are already in `lib/config/registry.py` at the tag: Seedance 2.0 / 2.0-fast / 2.0-mini / 2.5, Seedream 4.0–5.0 lite, Hailuo 2.3 / 2.3-Fast, Vidu q1–q3 turbo/pro, Wan 2.7 i2v/r2v, Kling v2.5-turbo..v4, Veo 3.1 (+fast, lite). Trials need route qualification and keys, not new backends. Not registered: Seedance 1.0 Pro Fast, Wan2.2-i2v-flash, Gemini Omni 1.2 Flash, LTX API.
F7. Official prices (read 2026-11-13, see cost doc): Veo 3.1 Lite $0.05/s, Fast $0.10/s, full $0.40/s; Kling 4.0 ≈ $0.14/s 720p (unit price inferred), lip-sync ≈ $0.014/s; Seedance 2.0 Mini ≈ $0.076/s (token-derived, ±30%); Hailuo 2.3 Fast $0.032/s; Seedream 5.0 lite $0.035/img; Nano Banana 2 $0.067/img. RunPod community 4090 $0.34/h, H100 $1.99/h.

## 2. Inferences

N1. The highest quality gain per dollar is on the film side, not the story side: the shipped film is a still slideshow while the story engine has had 19 ADRs of work.
N2. Per 60 s episode (cost doc §8.3): budget all-API ≈ $4–8, hybrid ≈ $3–4, premium ≈ $24–39. A cheap-first / premium-on-failure routing keeps most episodes in the budget band. 30 episodes/month ≈ $120–240.
N3. Moving selection and continuity judging to stills (AIVPE rubric + ViMax selection, cloud Flash-class VLM ≈ $0.15/episode) is cheaper than regenerating videos and makes the paid video step mostly first-time-right.
N4. Local models stay as plumbing fallback only; no threshold, rubric, prompt length or profile is to be sized to them (sponsor direction).

## 3. Unknowns (close by measurement in the trial)

U1. Which video engine wins on our own shots (dialogue close-up, action, wide) — no source compares them on Vietnamese drama.
U2. Vietnamese TTS quality with emotion (Gemini TTS, ElevenLabs v3, Azure vi-VN, MiniMax, VieNeu v4) — no price page proves it; needs native listening.
U3. Whether the $300 Google Cloud trial credit covers Veo; Seedance free quota; Kling resource-pack prices.
U4. Real Wan 2.2 LightX2V / LTX distilled speed on rentable GPUs other than RTX 5090.
U5. Cloud writer cost for a whole long novel part (not in the per-episode table).
U6. Veo 3.1 preview ids in our registry vs the reported 2026-10-22 shutdown (I7).
U7. Data-use terms: the Gemini free tier may use inputs for training — sponsor decision whether trial content may go there.

## 4. Re-evaluated recommendation

Order (each item: research-first → ADR → implement → measure):
1. **Trial bake-off (≈ $10–25 cash, 1–2 days):** 3 representative shots × 5–6 engines already registered (Veo 3.1 Lite/Fast, Seedance 2.0 Mini, Kling 4.0 Flash/v3, Hailuo 2.3 Fast, Vidu q3-turbo) with Seedream 5.0 lite / Nano Banana 2 stills; judge with Flash-class VLM; 20-line Vietnamese TTS A/B; optionally one rented 5090 for 2–3 h (≈ $2) to measure Wan 2.2 LightX2V. Output: a qualified cloud launch profile.
2. **P0 film quality ADRs:** (a) still-stage continuity judge + selection (AIVPE 11 checks, `promptFix` into regeneration, ViMax-style reference comparison; enables best-of-N); (b) real motion with a slideshow-risk gate and no silent downgrade (OM); (c) audio master: music/ambience bed with ducking, −14 LUFS / −1 dBTP normalization (openfilm), narration words-per-second budget (OM).
3. **P1:** shot grammar enum + coverage rule (Calliope/HUO 3-s segments), reference packing ≤ 8 (ViMax/HUO), duration fit to TTS (DC), drama via Kling elements + lip-sync route, per-model prompt dialects, delivery checks (open-edit).
4. **Routing policy:** cheap engine first, premium after 2 failed checks; batch API for non-interactive LLM/judge work.
5. **Cleanups:** verify/remove dead Veo preview ids; re-pin ViMax.

Rejected from the ChatGPT reports: building a separate Video Director/Router/Queue/Registry/Cost Manager (exist; ADR-0089 forbids a second orchestrator); running Calliope/AIVPE as platforms; Topview as a core path (API URLs valid 7 days, not 60; no Video Agent endpoint; Unlimited plan excluded from automation) — at most an optional avatar/UGC backend later.

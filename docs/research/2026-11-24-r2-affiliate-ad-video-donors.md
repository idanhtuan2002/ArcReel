# Affiliate / advertising videos (TikTok, YouTube Shorts) — donor units on this host

Date: 2026-11-24. Sponsor priority 2 after film 2 (film quality fixes deferred). Follows
[remake and ads donors](2026-11-24-r2-remake-and-ads-donors.md). Labels: **FACT**, **INFER**, **UNKNOWN**.

## 1. Units found (FACT)

| Donor @ commit | Unit | What it does | How it runs |
|---|---|---|---|
| DramaClaw v2.1.3 @ 1277795 | Freezone skill `ecommerce-ad` (`freezone/agent_workflows/catalog.py` `_DETERMINISTIC_SKILL_PLANNERS`) | stages planning (`video-ad-creative-outline`, `video-ad-brief`, `video-storyboard-script`, `ecommerce-text-plan`) → product assets (accepts the user's product image; else a generated "product anchor" image) → ad/scene images (`ecommerce-ad-image`, `ecommerce-scene-image`, `ecommerce-remix-image`) → optional video clips → optional audio; default 3 items | canvas workflow built and run by the Freezone chat agent (`freezone_*` tools, Hermes skill `workflows` + `references/ad-video.md`, `product-video.md`); recipe `social-copywriting` for captions text |
| DramaClaw | `product-video.md` chain | product input → features → use scenes → demo path → script → shots → assets → clips → voice/music → compose → QC | same agent |
| OpenMontage @ 4f682c8 | product ad as in its README "VOID — Neural Interface" | script, images, TTS narration, royalty-free music, word-level subtitles, Remotion composition, mandatory post-render self-review (ffprobe + frames + audio) | AI coding agent (our Claude or Codex driver, `assembly/openmontage/run.py`) following pipeline definitions (`animation`, `hybrid`, `cinematic`) |
| OpenMontage tools usable free here | `openai_tts` → VieNeu (`OPENAI_BASE_URL`), `pixabay_music` (no key), `subtitle_gen` + `remotion_caption_burn`, `video_compose`, `auto_reframe`, `wan_video` | | other providers (FAL, ElevenLabs, Suno, Runway, Pexels, …) have no key in `.env` |
| This host | `postiz` skill | schedules posts to TikTok/YouTube with caption text (affiliate link) | per-post sponsor approval |

## 2. Comparison for a 15–45 s vertical affiliate ad (INFER)

| Need | DramaClaw `ecommerce-ad` | OpenMontage |
|---|---|---|
| Product fidelity from the seller's photos | yes (product image replaces the generated anchor) | yes (stills as assets) |
| New lifestyle / scene images | yes, its strength (Seedream pool: limited, ~200 once-only) | only with an image key (none free here) |
| Hook / CTA script in Vietnamese | recipes are zh-first; agent writes the language asked (UNKNOWN quality on free models) | agent writes it; Claude driver strong, Codex free driver weak (film-1 evidence) |
| Voice | IndexTTS2 slot → our VieNeu channel | VieNeu via OpenAI-compatible TTS |
| Music | audio node (no free music model configured) | Pixabay music, free |
| Word captions | none found | yes (Remotion) |
| Final 9:16 compose + self-review | compose node; no self-review | yes |
| Driver | Freezone chat agent (Codex in the image on free models: flaky, film-1 evidence) | Claude Code (≈$0.70 per probe to the first checkpoint) or Codex (free) |

## 3. Recommendation

1. **OpenMontage drives the ad end to end** (script with hook/CTA, VieNeu voice, Pixabay music, motion on the product
   stills, word captions, 9:16, self-review) — it is the only unit here that delivers captions, music and a checked
   final file for free.
2. **DramaClaw `ecommerce-ad` supplies extra product scene images** when the seller has only one or two photos —
   later, because it spends the Seedream pool and needs the flaky chat agent.
3. Publishing through Postiz with the affiliate link in the caption — per-post approval.

## 4. Inputs needed from the sponsor (product questions)

- Product: 3–6 photos, name, price, 3 selling points, the affiliate link, target platform; dropped in
  `~/assembly-data/inbox/san-pham/`.
- Driver for the first ad: Claude (subscription quota, recurring) or Codex (free, weaker).

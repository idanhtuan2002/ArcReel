# Verification round on the running DramaClaw: what the plan got wrong, ArcReel as a donor, Vietnamese UI, no Cloudinary

Date: 2026-11-23, after M0. The sponsor asked: what about ArcReel as a donor; the interface must have a Vietnamese
version; what if there is no Cloudinary account; and one more deep round so nothing is wrong before continuing.
This round checked the plan against the **running** DramaClaw (`assembly-dramaclaw`, images 2.0.2) and the code.
Labels: **FACT** (probe or source), **INFER**.

## 1. Probes and readings (FACT)

| Check | Result |
|---|---|
| `GET /api/v1/model-gateway/custom/newapi/channel-types` (44 types) | image-capable: **OpenAI (1)**, Gemini (24), VertexAI (41), fal.ai (61); **VolcEngine (45) = text, embedding, video only**; DoubaoVideo (54) video; DoubaoAudio (62) audio; ComfyUI (63) **video only**; OpenRouter (20) text, vision, embedding |
| `official_media_models.json` | images are model `LingShan-G2` (aliases `gpt-image-2`, `newapi_gpt_image2`; legacy alias `seedream` → `newapi_gpt_image2`, `config.py`) and `LingShan-NB-2` (nanobanana), called on the OpenAI `images/generations` endpoint; reference images go in `payload["image"]` as URLs (`nanobanana_grid.py` ~3670) |
| Media relay (`storage/media_relay.py:280-315`) | providers `aliyun_oss` or `cloudinary` only, else `MediaRelayConfigError`; reference images are always relayed for NewAPI image calls (`_relay_reference_images_for_newapi`), video first frames too (`video_generator.py:2174-2195`) — no base64 fallback |
| Ingest (`api/routes/ingest.py`, `schemas.py:124`) | upload is multipart `file`; start takes `{filename, rebuild, spine_template: "drama" \| "narrated"}` |
| Container env | `INDEXTTS2_PROVIDER`, `INDEXTTS2_FAL_ENDPOINT`, `FAL_API_KEY` present in `assembly-dramaclaw-api-1` |
| UI languages | `frontend/src/i18n/index.ts` `SUPPORTED = ["zh","en"]`; one file `public/locales/<lng>/translation.json`, **5 886 strings**; switcher typed `"zh" \| "en"` in `components/layout/header.tsx`; the web image is prebuilt (nginx) |
| huohuo image | not on the registry; build from checkout |
| ArcReel upstream `6ddedc77` (v0.29) README | full novel / screenplay / product material → assets → storyboard → clips → film; asset reuse for consistency; per-asset redo and **version history rollback**; model and **cost management before and after generation**; **Jianying draft export** for further editing; three creation types (novel, screenplay, idea) and two generation modes |

## 2. Corrections to the plan

| # | Was | Now |
|---|---|---|
| V1 | D7: Seedream through the VolcEngine channel | VolcEngine has no image capability. **Images: NewAPI OpenAI-type channel with Base URL Override `https://ark.ap-southeast.bytepluses.com/api/v3`, upstream `seedream-4-5-251128`, mapped to DramaClaw's `LingShan-G2`** (DramaClaw already aliases `seedream` to it); `LingShan-NB-2` → Gemini channel image model if the free tier answers, else the same Seedream. Probe first (M1.0) |
| V2 | Local image fallback via ComfyUI | NewAPI's ComfyUI channel is video-only; a local image fallback needs a small OpenAI-images adapter in front of our ComfyUI (model-boundary adapter, GOAL rule 2) — M6, only when pools run out |
| V3 | Cloudinary assumed | Required for reference images, identity images, first frames. Without it: see §4 |
| V4 | Spine not chosen | **D26**: `spine_template = "drama"` for dialogue stories (default), `"narrated"` for narration-style stories; the run option `--spine` |
| V5 | Ingest through the plugin's JSON post | Upload is multipart; the connector posts the file itself, then `ingest/start` |
| V6 | DramaClaw UI zh/en | **Vietnamese UI required** (sponsor) → donor seam: `vi` in `SUPPORTED` and as default, a Vietnamese item in the header switcher, `public/locales/vi/translation.json` (5 886 strings translated by our translation with placeholders `{{…}}` checked), frontend image rebuilt from the pinned checkout. Backend messages stay zh/en |

## 3. ArcReel as a donor

ArcReel upstream is a third complete novel-to-film platform, besides huohuo and DramaClaw; our old app is its fork plus R2.
What it does that the chosen donors do not, and how it carries over without changing direction:

| ArcReel strength | In DramaClaw / huohuo | Carries over as |
|---|---|---|
| **Jianying (CapCut) draft export** — editable timeline with subtitles, voice, pacing, transitions | DramaClaw exports MP4 + SRT + ZIP; huohuo merges MP4 | post-stage on DramaClaw's episode (ArcReel's exporter on beats, clips, audio and subtitles) — **P2** (useful for a human edit pass) |
| Cost **before** generation (estimate) and after (usage) | NewAPI meters usage after calls | control page shows NewAPI usage per run (M2b); a pre-run estimate from ArcReel's cost calculator — P3 |
| Per-asset version history and rollback | DramaClaw keeps versions of some assets (UNKNOWN in full) | not carried until a need is seen |
| Product material / ad mode | none (OpenMontage has ads) | M5 with OpenMontage |
| Vietnamese workspace (our fork) | huohuo `vi`; DramaClaw after V6 | control page (M2b) in Vietnamese |
| Film pipeline | DramaClaw chosen (stage ranking) | ArcReel/R2 stays in production as the second fallback |

## 4. No Cloudinary account — options

| Option | Donor change | Cost | Verdict |
|---|---|---|---|
| Cloudinary free account (email sign-up) | none | free tier | **recommended** |
| Aliyun OSS | none | paid, Chinese account | no |
| "Inline" relay: a third provider in `storage/media_relay.py` that returns a `data:` URI instead of uploading (~30 lines) | yes (GOAL tolerance) | free | works only where the upstream accepts base64 in place of a URL: Gemini (inline data) yes; Seedream/Seedance image inputs and our voice adapter must be probed in M1.0 |
| Expose files from this machine publicly (tunnel) | needs a relay provider anyway (DramaClaw cannot point at arbitrary hosts) | — | no |

## 5. Plan impact

D7 corrected, D25 (Vietnamese UI everywhere: control page, huohuo `vi`, DramaClaw `vi` seam — sponsor requirement) and
D26 (spine) added; M1.0 probes include base64 acceptance; ArcReel's Jianying export added to M6/P2.

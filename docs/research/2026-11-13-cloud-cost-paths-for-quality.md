# Cloud cost paths for quality (Vietnamese AI film pipeline, 9:16 episodes)

- Date read: 2026-11-13 (all prices below were read on this date; they move fast and several carry promo cut-off dates, flagged inline).
- Scope: licenses excluded by sponsor decision.
- Method: official pricing/doc pages first. Many pricing pages are JS-rendered, so they were read through a text renderer (`r.jina.ai` proxy over the official URL) or WebFetch; the content is the official page, the renderer is only transport. Where a page rendered without numbers, the row is marked UNKNOWN. Reseller/aggregator numbers and blog numbers are marked **SECONDARY**. Anything computed by me is marked **INFERRED** with the formula.
- Conventions: USD; "720p/1080p" is output resolution; 9:16 is assumed to cost the same per second as 16:9 unless a page says otherwise (unverified).

## Sources (official unless marked)

| Short | URL | Read |
|---|---|---|
| Gemini API pricing | https://aistudio.google.com/docs/pricing (was ai.google.dev/gemini-api/docs/pricing) | 2026-11-13 |
| Vertex pricing (Veo, Imagen, TTS) | https://cloud.google.com/vertex-ai/generative-ai/pricing | 2026-11-13 |
| BytePlus ModelArk pricing | https://docs.byteplus.com/en/docs/modelark/model-pricing (page updated 2026-11-12) | 2026-11-13 |
| Kling dev pricing / docs | https://kling.ai/dev/pricing , https://kling.ai/document-api/pricing/base/video | 2026-11-13 |
| Alibaba Model Studio pricing | https://www.alibabacloud.com/help/en/model-studio/model-pricing | 2026-11-13 |
| MiniMax pricing | https://platform.minimax.io/docs/pricing/overview | 2026-11-13 |
| LTX API pricing | https://docs.ltx.io/pricing.md | 2026-11-13 |
| Vidu pricing | https://platform.vidu.com/docs/pricing | 2026-11-13 |
| Runway API pricing (includes resold third-party models) | https://docs.dev.runwayml.com/guides/pricing/ | 2026-11-13 |
| Sync.so pricing | https://sync.so/pricing | 2026-11-13 |
| Anthropic pricing | https://platform.claude.com/docs/en/about-claude/pricing | 2026-11-13 |
| OpenAI pricing | https://developers.openai.com/api/docs/pricing , https://openai.com/api/pricing/ | 2026-11-13 |
| DeepSeek / Kimi / Z.ai pricing | https://api-docs.deepseek.com/quick_start/pricing , https://platform.moonshot.ai/docs/pricing/chat , https://docs.z.ai/guides/overview/pricing | 2026-11-13 |
| Azure Speech pricing | https://azure.microsoft.com/en-us/pricing/details/cognitive-services/speech-services/ | 2026-11-13 |
| ElevenLabs API pricing | https://elevenlabs.io/pricing/api (prices partly stripped by renderer) | 2026-11-13 |
| Stability pricing | https://platform.stability.ai/pricing | 2026-11-13 |
| BFL pricing | https://bfl.ai/pricing | 2026-11-13 |
| RunPod pricing | https://www.runpod.io/pricing | 2026-11-13 |
| Modal pricing | https://modal.com/pricing | 2026-11-13 |
| Replicate pricing | https://replicate.com/pricing | 2026-11-13 |
| Lambda pricing | https://lambda.ai/pricing | 2026-11-13 |
| fal pricing + per-model llms.txt | https://fal.ai/pricing , https://fal.ai/models/fal-ai/wan/v2.2-a14b/image-to-video/llms.txt , .../veo3.1/image-to-video/llms.txt , .../ltx-2.3/image-to-video/llms.txt | 2026-11-13 (aggregator: SECONDARY for model prices; GPU prices are fal's own) |
| Vast.ai marketplace | https://vast.ai/pricing (live market: "from"/median, not a rate card) | 2026-11-13 |
| TensorDock / Salad | https://tensordock.com/ , https://salad.com/pricing | 2026-11-13 |
| WaveSpeed / Kie.ai / PiAPI / AIMLAPI / OpenRouter | https://wavespeed.ai/pricing , https://kie.ai/pricing , https://piapi.ai/pricing , https://aimlapi.com/ai-ml-api-pricing , https://openrouter.ai/models?output_modalities=video | 2026-11-13 (SECONDARY) |
| LightWan2.2 model card (maintainer benchmark) | https://huggingface.co/lightx2v/LightWan2.2-A14B , https://github.com/ModelTC/LightX2V | 2026-11-13 |
| HunyuanVideo-1.5 step distillation | https://huggingface.co/tencent/HunyuanVideo-1.5/blob/main/assets/step_distillation_comparison.md | 2026-11-13 |
| LTX-2.5 repo | https://github.com/Lightricks/LTX-2 | 2026-11-13 |
| Search-only (SECONDARY) | HeyGen help center / Hedra via web search; Kaggle/Colab via gpuperhour/aggregator blogs; Suno via unifically/costbench; BytePlus free-quota via search snippets | 2026-11-13 |

Note: model names in the pages (Gemini 3.8/4, Kling 4.0, Seedance 2.5, Wan 3.0, GPT-6.x, Claude 5.5, MiniMax H3, LTX-2.5) are exactly as the pages state them on 2026-11-13; the repo's integrated backends list (Kling 2.5..v4, Seedance, Veo 3.1, Wan 2.x) is a subset.

## 1. Video generation, price per output second

### 1.1 Official / first-party

| Provider / model | 720p | 1080p | Notes (source) |
|---|---|---|---|
| **Kling official API** | | | Billing in "Units/s". Video unit USD price not shown on the rendered page. **INFERRED 1 Unit = $0.14** (video): matches fal Kling 2.5 Turbo Pro $0.07/s = 0.5 u/s, and Runway resale 12 cr/s. Image unit is stated: 1 Unit = $0.0035 (list). |
| Kling 2.5 Turbo / 2.6 (no audio), std/pro | 0.3 u/s -> **$0.042** | 0.5 u/s -> **$0.07** | 2.6 with native audio 1080p 1.0 u/s -> $0.14 |
| Kling 3.0 Turbo (native audio) | 0.8 u/s -> $0.112 | 1.0 u/s -> $0.14 | |
| Kling 3.0 no audio / with audio | 0.6 / 0.9 u/s -> $0.084 / $0.126 | 0.8 / 1.2 u/s -> $0.112 / $0.168 | 4K 3.0 u/s -> $0.42 |
| Kling 4.0 (no input video) | 1.0 u/s -> **$0.14** | 1.5 u/s -> **$0.21** | 30 s native generation; input-video variants 0.6/0.9 u/s but billed on in+out duration |
| Kling 4.0 Flash | 0.6 u/s -> **$0.084** | n/a | 720p only listed |
| Kling resource packs | UNKNOWN | UNKNOWN | prepaid packages exist ("Flexible Prepaid Packages"); tiers not rendered |
| **Seedance, BytePlus ModelArk** | | | Per **1M output tokens**; second cost = tokens/s x price. **INFERRED** token formula tokens = W x H x fps x s / 1024 (24 fps) -> 9:16: 480p 9.6k tok/s, 720p 21.6k tok/s, 1080p 48.6k tok/s. The page flattens the resolution/with-video/offline columns, so the per-resolution split of the rate is not certain; offline (batch) is about 50% for 1.0 models ($2.5 -> $1.25). |
| Seedance 1.0 Pro Fast | $1/M -> **$0.022/s** | -> $0.049/s | cheapest decent model found |
| Seedance 1.0 Pro | $2.5/M -> $0.054/s | -> $0.12/s | |
| Seedance 2.0 Mini | $3.5/M -> **$0.076/s** (480p $0.034/s) | not supported | |
| Seedance 2.0 Fast | $5.6/M -> $0.121/s | not supported | |
| Seedance 2.0 | $7.0/M -> $0.151/s | $7.7(?)/M -> ~$0.37/s | |
| Seedance 2.5 / 2.5 Flash | $10.7/M -> $0.23/s ; Flash $7.0/M -> $0.151/s | $11.7/M -> ~$0.57/s | |
| Seedance on Volcengine (China) | UNKNOWN (not read; CN-region pricing not needed for BytePlus account) | | |
| **Veo 3.1 (Vertex)** | $0.40 / "count" | $0.40 | Vertex table says "$0.40 / 1 count" with audio; unit not stated. fal confirms **$0.40/s with audio, $0.20/s without** for Veo 3.1 (SECONDARY), so "count" = second is assumed. |
| Veo 3.1 Fast (Vertex) | **$0.10** | n/a (720p only) | |
| Veo 3.1 Lite (Vertex) | **$0.05** | n/a (720p only) | cheapest first-party video with audio |
| Veo in Gemini API (AI Studio page) | not listed on 2026-11-13 page | | page now lists Gemini Omni 1.2 Flash video instead: $12/M video-output tokens, 5,792 tok/s 720p -> **$0.07/s 720p, $0.104/s 1080p**, $0.023/s 360p, up to 15 s, paid tier only |
| **Wan, Alibaba Model Studio (Singapore)** | | | |
| wan2.6/2.7 i2v | $0.10 | $0.15 | |
| wan2.6-i2v-flash (with audio) | **$0.05** | $0.075 | |
| wan2.2-i2v-flash | **$0.036** | n/a | |
| wan2.5-i2v-preview (audio) | $0.086 | $0.143 | region header not shown in my excerpt |
| wan2.2-i2v-plus (silent) | n/a | $0.100 | 480p $0.020 |
| wan3.0-video-prime / wan3.0-video | $0.14 / $0.10 (30% promo) | $0.28 / $0.20 | |
| **MiniMax** (768P is its "720p") | | | |
| MiniMax-H3 | 768P $0.08 | 2K $0.13 | |
| H3-Highspeed / H3-Lite | $0.06 / **$0.04** (480P $0.04 / $0.025) | n/a | |
| H3-Max | 768P $0.08 | n/a | |
| Hailuo 2.3 Fast | 768P: $0.19 per 6 s = **$0.032/s** | 1080P $0.33/6 s = $0.055/s | |
| Hailuo 2.3 / 02 | $0.28/6 s = $0.047/s | $0.49/6 s = $0.082/s | |
| **Vidu** (credits; RMB 500 = 16,000 credits; **INFERRED** FX 7.1 RMB/USD -> $0.0044/credit) | | | |
| viduq3-turbo | 12 cr/s -> $0.053/s ; off-peak 6 -> $0.026/s | 13 cr/s -> $0.057/s (off-peak 7) | |
| viduq3-pro | 20 cr/s -> $0.088/s ; off-peak 10 -> $0.044/s | 24 cr/s -> $0.106/s (off-peak 12) | |
| viduq3-pro-fast (i2v) | 12 cr/s -> $0.053/s | 15 cr/s -> $0.066/s | |
| **LTX API (Lightricks)** | | | |
| ltx-2-3-fast / pro | $0.03 / $0.04 | $0.06 / $0.08 | per output second |
| ltx-2-5-fast / pro | $0.09 / $0.12 | $0.13 / $0.17 | audio-to-video billed on input audio seconds |
| **Runway API** (credit = $0.01) | | | resells others at a markup: Kling 3.0 std no audio 9 cr/s = $0.09/s (vs $0.084 official), Wan3 720p $0.10/s, Seedance 2.5 720p $0.30/s, 1080p $0.68/s. Runway's own Gen-4.5 rate not captured. |
| **Luma Ray3.2** | UNKNOWN | UNKNOWN | page lists credits only |
| Grok Imagine (via Runway) | 16 cr/s $0.16 (720p) | 29 cr/s $0.29 | lite 3 cr/s $0.03 (720p) |

### 1.2 Aggregators (SECONDARY; compare with official)

| Aggregator | Observations |
|---|---|
| fal.ai | Kling 2.5 Turbo Pro / 2.6 $0.07/s (= official pro 1080p rate); Kling 3 Pro/Std $0.14/s; Wan 2.2 A14B i2v $0.08/s 720p, $0.06 580p, $0.04 480p; Veo 3.1 $0.20/s no audio, $0.40/s with audio; LTX-2.3 i2v $0.08/s 1080p; Seedance 2.0 Fast $0.0112 per 1,000 tokens (= $11.2/M, **2x BytePlus Fast $5.6/M**), 2.0 Mini $7/M (2x BytePlus). So fal is at roughly official parity for Kling/Veo and about 2x official on Seedance 2.0 variants. |
| WaveSpeed | Seedance 2.0 from $0.12/s, 2.5 from $0.18/s (starting price, resolution not stated); Seedream 5.0 Flash $0.027/img; Nano Banana 2 $0.045/img; GPT Image 2 $0.01/img (starting) |
| Kie.ai | "from" prices only: Seedance 2 $0.057/s, Seedance 2 Mini $0.012/s, Seedance 1.0 Pro $0.014/s, Gemini Omni Flash 1.2 from $0.02/s, Kling 2.5 turbo from $0.315/video, Hailuo 2.3 from $0.15/video, Nano Banana from $0.02/img. Starting prices likely lowest tier (480p/shortest); not comparable to 720p/1080p without per-model checks. |
| PiAPI | pricing page rendered without model prices; plans $0/$15/$60/$100, new accounts $0.50 free |
| AIMLAPI / OpenRouter | OpenRouter lists 32 video models (Gemini Omni, Wan 3.0, MiniMax H3/H3-Max, Seedance, Runway Gen-4.5, HeyGen, FLUX) but per-second prices not captured: UNKNOWN. AIMLAPI mirrors LLM list prices (Claude Sonnet 5.5 $2/$10) = parity. |
| Replicate | GPU only (below) |

### 1.3 Free credits / free tiers / trials

| Provider | What | Conditions |
|---|---|---|
| Google Gemini API | Free tier: text/Flash models, Flash TTS ("Free of charge") | **not** for video, image gen (Nano Banana "Not available") or Pro; free-tier content is used to improve products |
| Google Cloud | $300 for new customers, 90 days, card required (official page) | Veo/Vertex eligibility asserted only by SECONDARY articles; UNVERIFIED |
| Alibaba Model Studio (SG) | Free quota valid 90 days: qwen3.8-max / qwen3.7-plus / flash 1M tokens each; qwen-image-2.1-pro 10 images; wan2.7-image(-pro) 50 images; **wan3.0-video 30 s**; wan2.1-t2v-turbo 50 s; qwen3-tts-flash / cosyvoice 10,000 chars | new activation, Singapore region only |
| BytePlus ModelArk | New users: 500k free tokens per LLM, 2M per vision model (homepage text via search); "Free tokens only" mode suspends service at quota | whether Seedance/Seedream are in the 2M vision quota is UNKNOWN (SECONDARY snippets) |
| WaveSpeed | $1 for eligible new accounts | |
| PiAPI | $0.50 for new accounts | |
| Modal | $30/month free compute credits (Starter), 1 TiB egress free | |
| Kling, Vidu, MiniMax, Runway, Luma, LTX, fal, Replicate | trial credit UNKNOWN (not shown on pages read) | |
| Kaggle | about 30 GPU h/week T4/P100 (SECONDARY; Kaggle does not publish a fixed number) | 16 GB cards, too small for Wan 14B at useful speed (INFERENCE) |
| Colab | Pro $9.99/100 units; Pro+ $49.99/600 units (SECONDARY) | T4 burn about 1.2-1.8 units/h |

## 2. Images (storyboard keyframes, with character reference)

| Model | Price per image | Source |
|---|---|---|
| Nano Banana 2.1 (Gemini) | $0.0336 (1K), $0.0504 (2K), $0.113 (4K) | Gemini API page |
| Nano Banana 2 (3.1 Flash Image) | $0.045 (0.5K), **$0.067 (1K)**, $0.101 (2K), $0.151 (4K) | same |
| Nano Banana Pro (3 Pro Image) | **$0.134** (1K/2K), $0.24 (4K) | same; batch about 50% |
| Nano Banana (2.5 Flash Image) | $0.039 | same |
| Nano Banana 3.1 Flash Lite Image | $0.0336 (1K) | same |
| Imagen 4 / Fast / Ultra (Vertex) | $0.04 / $0.02 / $0.06 | Vertex page |
| Seedream 5.5 | $0.045 (<=1.5K), $0.09 (larger) | BytePlus |
| Seedream 5.0 lite / 4.5 / 4.0 / 5.0 flash | **$0.035** / $0.04 / $0.03 / **$0.018** (input images free) | BytePlus |
| Kling Image 3.0 / 3.0 Omni / O1 | 8 u x $0.0035 = **$0.028**; 4K Omni $0.056; 2.1 t2i $0.014; multi-image ref 16 u = $0.056 | Kling dev pricing |
| Qwen-Image (SG) | 2.1-pro $0.04; 2.0 $0.035; 3.0 $0.03 | Alibaba |
| MiniMax H3-Image | about $0.022 (1K t2i), $0.027 (edit, 1 ref), $0.036 (edit, 3 refs); highspeed $0.035-$0.06 | MiniMax |
| FLUX (fal rates per megapixel; 1 MP image) | FLUX.2 $0.012, FLUX.2 Flash $0.005, FLUX 3 Image $0.048/img (BFL), FLUX.2 pro via Kie from $0.025 (SECONDARY) | fal / BFL / Kie |
| GPT-Image-2.6 (Flare/Sunburst) | token-based: $8/M image-in, $30/M image-out, $5/M text-in; **per-image figure not published on pages read: UNKNOWN**; reseller "from $0.03/img" (Kie) and $0.01 (WaveSpeed) SECONDARY | OpenAI |

## 3. Lip-sync / talking avatar (price per second of video)

| Service | Price | Source / note |
|---|---|---|
| Kling Lip Sync | 0.5 u per 5 s = 0.1 u/s -> **$0.014/s** (INFERRED unit $0.14) | Kling pricing |
| Kling Avatar | 0.4 / 0.8 u/s (720p/1080p) -> $0.056 / $0.112 per s | Kling pricing |
| Sync.so | lipsync from **$0.04-$0.05/s** depending on plan ($5/mo+$0.05, $19/mo+$0.05, $49/mo $0.0475, $249/mo $0.04) | sync.so |
| HeyGen API Avatar IV | about $3-$5 per minute (= $0.05-$0.083/s); conflicting numbers across sources | SECONDARY (help center via search) |
| Hedra Character-3 API | about $0.05/s; floor "from 2.5 cents/s" for avatar/lipsync | SECONDARY, unconfirmed |
| fal LatentSync / MuseTalk | not captured: UNKNOWN. Self-host cost = GPU time (section 7) |
| Vietnamese lip-sync quality for any of the above | UNKNOWN (no vendor claims found) |

## 4. TTS (emotion, Vietnamese)

| Service | Price | Vietnamese / emotion notes |
|---|---|---|
| Gemini 3.8 Flash TTS | $0.50/M text-in + $9.00/M audio-out (**rises Jan 1, 2027**; Vertex lists $1.00 text-in then); free tier "Free of charge" | line-by-line style direction; Vietnamese support not confirmed on the pricing pages (UNKNOWN; test) |
| Gemini 3.8 Flash-Lite TTS | $0.50 + $6.00/M | |
| Gemini 3.1 Flash TTS / 2.5 Pro TTS | $1.00 + $20/M | |
| ElevenLabs v3 | page shows **$0.08 per 1K chars** for v3 and $0.04 for "v3 Conversational"/Flash (renderer ordering ambiguous); Kie resells v3 from $0.07/1K (SECONDARY). v4 exists ("most emotive, audio tags", 90+ languages) but price stripped: UNKNOWN. v3: "70+ languages", 5,000 char limit, multi-speaker. | Vietnamese is within 70+/90+ language claims; per-language quality not stated by pricing page |
| Azure Neural TTS | **$15 per 1M chars** (pay-as-you-go), commitment tiers $12 / $9.75 / $7.50 per 1M; free F0 0.5M chars/month; Neural HD price "N/A" for the listed rows | vi-VN not named on the pricing page (UNKNOWN there); Azure has vi-VN voices historically (from memory, unverified here) |
| MiniMax speech-2.8-hd / turbo | $100 / $60 per 1M chars; voice clone $1.5/voice; voice design $3 | Vietnamese support not stated on the pricing page: UNKNOWN |
| Alibaba qwen3-tts-flash / cosyvoice-v3-flash / v3-plus | $0.10 / $0.13 / $0.26 per 10k chars ($10 / $13 / $26 per 1M); 10k chars free each | Vietnamese support UNKNOWN |
| OpenAI TTS (gpt-4o-mini-tts) | not shown on pages read: UNKNOWN (realtime/live voice priced per minute only) | |
| VieNeu | open-source TTS; **no vieneu.io v4 API found** (newest reference v3 Turbo, open-source self-host; Apify actor "pay per usage", rate unknown) | self-host = GPU/CPU time only |
| FPT.AI / Zalo / Viettel AI TTS | prices **UNKNOWN** (consoles/sales-led; no public per-char table found). Viettel advertises 16 Vietnamese voices; FPT docs list voices banmai, lannhi | native-Vietnamese vendors; quality must be A/B tested |

## 5. Music / SFX

| Option | Price / status |
|---|---|
| Google Lyria 3.5 | **$0.08 per full song**, Lyria 3 Clip (30 s) $0.04; no free tier; same on Vertex |
| ElevenLabs Music / Sound Effects API | "per minute" prices stripped by renderer: UNKNOWN. Music: 5-minute limit, commercial licensing on Starter+ plans; SFX described as royalty-free |
| Stable Audio 3.0 / 2.5 | 8 credits per generation (up to 6 / 3 minutes); USD per credit not on the rendered page (Stability credit = $0.01 from memory, UNVERIFIED -> about $0.08) |
| Suno | no sanctioned public developer API as of Oct 2026 (SECONDARY: unifically, api-evangelist); wrappers sell about $0.11-$0.12 per generation, ToS risk |
| Udio | no information found |
| MiniMax music | a music-models section exists; price not captured: UNKNOWN |
| Royalty-free libraries | not researched (out of the cost-compare scope; no per-use cost assumed beyond Lyria) |

## 6. LLMs and VLM judges

### 6.1 Text, per 1M tokens (standard; batch noted)

| Model | Input | Output | Batch / notes |
|---|---|---|---|
| Gemini 4 Carbon | $2.00 (to Nov 30, 2026) then $4.00 | $10 then $20 | no free tier |
| Gemini 3.1 Pro Preview (<=200k) | $2.00 | $12.00 | batch $1 / $6 |
| Gemini 3.8 Flash | $0.75 (to Dec 31, 2026) then $1.50 | $3.75 then $7.50 | **free tier available** |
| Gemini 3.5 Flash-Lite | $0.30 | $2.50 | free tier |
| Gemini 3.1 Flash-Lite | $0.25 | $1.50 | free tier |
| Gemini 3 Flash Preview | $0.50 | $3.00 | batch $0.25 / $1.50; free |
| Gemini 2.5 Pro / Flash | $1.25/$10 ; $0.30/$2.50 | | batch 50%; **routed away Dec 1, 2026** |
| Claude Opus 5.5 | $4 | $20 | batch $2 / $10 |
| Claude Sonnet 5.5 | $2 | $10 | batch $1 / $5 |
| Claude Haiku 5.5 | $0.10 (<=100k prompt) | $0.50 | |
| Claude Opus 5 / 4.8 | $5 | $25 | |
| GPT-6 Astra / 6.1 Sol / 6.1 Terra / 6 Luna | $10 / $2 / $1 / $0.10 | $50 / $10 / $5 / $0.50 | batch -50% |
| DeepSeek V4.1 Flash | $0.15 off-peak, $0.30 peak (cache miss) | $0.60 / $1.20 | off-peak = half; V4 Pro $0.66/$1.32 in, $1.98/$3.96 out |
| Qwen (Alibaba SG) | qwen3.8-max $2 ; qwen-plus $0.40 ; qwen-flash $0.05 | $6 ; $1.2 (thinking $4) ; $0.40 | free 1M tokens per model, 90 days |
| Kimi K3.1 Pro / K3 | $2.00 / $3.00 | $10 / $15 | auto context caching |
| GLM-5.3 / 5.3-Flash | $1.4 / $0.15 | $4.4 / $0.50 | "limited-time free" cached storage; |
| MiniMax M3 | $0.30 (50% permanent discount) | $1.20 | |
| OpenRouter free models | not measured: UNKNOWN |

Vietnamese writing/judging quality is not stated on any pricing page: UNKNOWN; must be measured on the repo's own evaluation set.

### 6.2 VLM judge per call (INFERRED)
Assumptions: one 720p frame about 1.0-1.3k input tokens (Gemini tiles of 258 tokens; not read from this page), plus 500 text tokens in, 300 out.
- Gemini 3.8 Flash: (1.8k x $0.75 + 0.3k x $3.75)/1M = **about $0.0025/image call**; free tier covers prototyping.
- Gemini 3.1 Pro: (1.8k x $2 + 0.3k x $12)/1M = about $0.0072/call.
- Video judging at 1 fps about 258 tok/s (INFERRED from Google video-token rule, not re-read): 5 s clip about 1.3k tokens + prompt, so about $0.003 (Flash) per 5 s clip pass.
- Qwen-VL-Max / qwen3-vl-plus price not captured: UNKNOWN.

## 7. Renting GPUs for self-hosting

### 7.1 Price per hour (cited; USD)

| GPU | RunPod pods secure / community | RunPod serverless (active) | Vast.ai (live, "from" / median) | Modal (per sec x 3600) | Other |
|---|---|---|---|---|---|
| RTX 4090 24GB | $0.89 / **$0.34** | $1.34 | from $0.13 / median $0.47 | n/a | TensorDock from $0.35; Salad $0.16-$0.44 |
| RTX 5090 32GB | n/a on page | n/a | from $0.39 / median $0.64 | n/a | Salad $0.25-$0.60 |
| L40S 48GB | $1.09 / $0.79 | $1.75 | from $0.44 | $1.95 | Replicate $3.51 |
| A100 80GB | $1.79 / $1.19-$1.39 | $2.72 | not captured | $2.50 | TensorDock A100 SXM4 from $1.80; Replicate $5.04 |
| H100 80GB | $2.89 PCIe, $3.99 SXM / $1.99 PCIe, $2.69 SXM | $5.39 | from $2.13-2.20, median $2.27-2.60 | $3.95 | TensorDock from $2.25; fal list $4.50 (as low as $2.49); Replicate $5.49; Lambda cluster $6.16 |
| H200 141GB | $5.29 / $3.59 | $6.99 | from $2.63, median $4.49 | $4.54 | fal $6.00 (as low as $2.99) |
| B200 192GB | $7.99 / $5.98 | $10.79 | from $7.50, median $10.00 | $6.25 | Lambda $7.69 on-demand; fal $7.99 (as low as $5.49) |

RunPod spot prices: not listed on the page (UNKNOWN). Google Colab/Kaggle: see 1.3. Lambda self-serve single-GPU H100/A100 rows not captured (only B200 $7.69 and cluster rates).

Storage / cold start: RunPod container disk $0.10/GB-mo; volume $0.10 running, $0.20 idle; network volume $0.07/GB-mo (under 1 TB). Modal volumes $0.09/GiB-mo, 1 TiB/month egress free; network egress $0.04/GiB. Cold-start seconds are **not published** on these pages (UNKNOWN): Wan 2.2 14B has two experts, so expect tens of GB of weights to load (INFERENCE). Budget a persistent network volume of about 100 GB = about $7/month (RunPod, INFERRED).

### 7.2 Throughput benchmarks (maintainer/official)

| Model | Benchmark | Source |
|---|---|---|
| Wan2.2-I2V-14B, LightWan2.2-A14B (4 NFE, NVFP4 + sparse attention, **Blackwell only**) | single **RTX 5090**: 480p **10.7 s**, 720p **26.7 s** end-to-end (vs 787 s / 2685 s for original 40-step). Clip length not stated on the card (presumed 81 frames about 5 s at 16 fps: INFERENCE). | LightWan2.2-A14B model card |
| Wan2.2 4-step I2V 14B (BF16/FP8/INT8) on 4090/L40S/A100/H100 | **no published wall-clock**; project claims about 20-24x step-distill speedup vs 40-50 steps and recommends quantization + CPU offload for 24 GB | LightX2V README |
| HunyuanVideo-1.5 480p I2V step-distilled (8 or 12 steps; 4 steps possible) | official: single **RTX 4090 within 75 s**, "up to 75% reduction" in e2e time; blog (SECONDARY): 65 s at 8 steps, 80 s at 12 steps | HF step-distillation doc |
| LTX-2.3 / 2.5 distilled (8 steps stage 1 + 4 steps stage 2) | official repo gives no timing; LTX marketing says an 8 s full-HD clip about 15 s on H100 cloud (vendor claim, no variant stated); "18x faster than Wan 2.2-14B" claim SECONDARY | github.com/Lightricks/LTX-2, ltx.io |

Derived cost per output second (INFERRED, formulas in section 8.2):
- Wan 2.2 14B LightX2V 720p on a rented 5090: 26.7 s per 5 s clip = 5.3 GPU-s per output second; at $0.64/h median = **$0.00094/output-s** at 100% utilization, about **$0.0019 at 50% utilization**. Compare Wan API $0.10/s: about 50-100x cheaper compute, ignoring engineering and the quality gap.
- Same model on 4090/L40S/H100: unmeasured. Using an **assumed** 120 s (4090/L40S) and 50 s (H100) per 5 s 720p clip: 4090 community $0.34/h -> $0.0023/output-s; H100 community $1.99/h -> $0.0055/output-s (100% util).

## 8. Cost per finished 60 s 9:16 episode

### 8.1 Assumptions (change them to match the pipeline)

- 12 shots x 5 s = 60 s final. Video generated seconds V = 60 x 1.3 retries = **78 s**.
- Images: 12 stills x 2 candidates = 24, plus 4 character/reference/edit calls = **28 image calls**.
- TTS: 150 lines x 50 chars = 7,500 chars x 1.3 retakes about **10,000 chars**, about 2 min audio.
- Lip-sync: 30 s of dialogue shots x 1.3 retries = 39 s (API stacks). Veo/Kling-with-audio could skip it (not modelled).
- LLM per episode (script, storyboard, prompts, QA; the novel is amortized elsewhere): 150k tokens in, 40k out.
- Judge per episode: about 100k input, 20k output tokens (stills + sampled video frames, 2 passes).
- Music/SFX: one Lyria song $0.08 plus small SFX/retries = $0.15-$0.30.
- Compute efficiency for rented GPUs: 50% billable utilization (loading, idle, queue); 15.6 clips of 5 s.
- Excluded: engineer time, egress, storage fixed costs (listed separately), failed-moderation refunds, FX.

### 8.2 Formulas

- API video = V x $/s. Images = 28 x $/img. TTS = chars/1000 x $/1K (ElevenLabs) or tokens x rate (Gemini; about 2.9k audio-out tokens at 25 tok/s -> about $0.03-0.05).
- Lip-sync = 39 s x $/s. LLM = in x p_in + out x p_out. Judge likewise.
- GPU video = clips x s_clip/3600 x $/h / utilization. Other GPU jobs (images about 9 GPU-min, TTS 3, LatentSync-type lip-sync 10; all **assumed** at 4090 speed) added similarly.

### 8.3 Table (USD per episode)

| Line | a) all-API premium (Kling 4.0 1080p) | a2) premium variant (Veo 3.1 with audio) | b) all-API budget (Seedance 1.0 Pro Fast 720p) | b2) budget, newer model (Seedance 2.0 Mini 720p) | b3) budget, Veo 3.1 Lite 720p | c) rented GPU, self-hosted media (4090 community / 4090 secure / H100 secure) | d) hybrid: API stills + GPU video + cheap TTS (same 3 GPUs) | e) free-credit trial path |
|---|---|---|---|---|---|---|---|---|
| Video | 78 x $0.21 = 16.38 | 78 x 0.40 = 31.20 | 78 x 0.0216 = 1.68 | 78 x 0.0756 = 5.90 | 78 x 0.05 = 3.90 | 0.35 / 0.93 / 1.25 | 0.35 / 0.93 / 1.25 | Veo Lite 3.90 (credit-funded) |
| Images | 28 x 0.134 (Nano Banana Pro) = 3.75 | 3.75 | 28 x 0.035 (Seedream 5.0 lite) = 0.98 | 0.98 | 0.98 | on-GPU, in "other GPU" | 28 x 0.067 (Nano Banana 2) = 1.88 | 28 x 0.0336 (Nano Banana 2.1) = 0.94 (credit-funded) |
| TTS | ElevenLabs v3 10k x 0.08/1K = 0.80 | 0.80 | Gemini Flash TTS about 0.05 | 0.05 | 0.05 | open TTS on GPU (inside other) | 0.05 | 0 (Gemini Flash TTS free tier) |
| Lip-sync | Sync.so 39 x 0.05 = 1.95 | 0 if Veo native audio used (kept: 1.95) | Kling LS 39 x 0.014 = 0.55 | 0.55 | 0.55 | on-GPU | on-GPU about 0.2 | none (voice-over or native audio) |
| Music/SFX | 0.30 | 0.30 | 0.15 | 0.15 | 0.15 | 0.15 | 0.15 | 0.08 (Lyria; not free, small) |
| Judge | Gemini 3.1 Pro 0.44 | 0.44 | Gemini 3.8 Flash 0.15 | 0.15 | 0.15 | 0.15 | 0.15 | 0 (Flash free tier) |
| LLM writing | Gemini 3.1 Pro 0.78 (Sonnet 5.5 0.70) | 0.78 | Flash 0.26 | 0.26 | 0.26 | 0.26 | 0.26 | 0 (Flash free tier, limits apply) |
| Other GPU jobs | | | | | | 0.25 / 0.65 / 0.95 | included above | |
| **Total per episode** | **about 24.4** | **about 39.2** (about 37 without lip-sync) | **about 3.8** | **about 8.0** | **about 6.0** | **about 1.0 / 2.0 / 2.6** | **about 3.0 / 3.6 / 3.9** | **about 0 cash, about 5 credits burned**; limited by quotas |

Other video engines at the b-slot (swap the video line, everything else equal to b = 3.82): Kling 4.0 Flash 720p 78 x 0.084 = 6.55 -> total about 8.7; Hailuo 2.3 Fast 768P 78 x 0.032 = 2.5 -> about 4.6; Wan2.2-i2v-flash 78 x 0.036 = 2.81 -> about 4.9; Vidu q3-turbo off-peak 78 x 0.026 = 2.0 -> about 4.1; LTX-2.3 fast 1080p 78 x 0.06 = 4.7 -> about 6.8.

Seedance 2.x per-second values are INFERRED from tokens; resellers show 2.0 at about $0.12-0.15/s (WaveSpeed from $0.12, Runway-resold 2.5 at $0.30), so treat b2 as +-30%.

Monthly at 30 episodes (excluding fixed costs): a about $730; a2 about $1,180; b about $115; b2 about $240; b3 about $180; c about $30-80 (+ about $7-10 storage); d about $90-120.

Free path (e) is bounded by quotas, not price: the Gemini free tier has rate limits and trains on your data; Alibaba's free `wan3.0-video` is only **30 s** (about 0.4 episode); the $300 Google Cloud credit funds about 60 episodes at the Veo Lite rate **only if** Veo is eligible for trial credit (unverified; 300 / 5 per episode). Image generation is not free on the Gemini API.

## 9. Recommendation

### (i) Two-week trial (target total spend about $60-$150 cash, or about $0 if the GCP credit is accepted for Veo)
1. Day 1-2 bake-off on 3 representative shots (dialogue close-up, action, wide establishing) x 6 engines, 720p: Veo 3.1 Lite and Fast (Vertex), Seedance 2.0 Mini and 1.0 Pro Fast (BytePlus), Kling 4.0 Flash (official), Hailuo 2.3 Fast / Vidu q3-turbo off-peak. Cost about 18 clips x 5 s x average $0.06 = about $5-$12. Judge with Gemini 3.8 Flash (free tier) plus human rating; record per-engine retry rate, because retries dominate cost.
2. Text, judge, TTS during trial on the Gemini free tier (Flash, Flash TTS) and Alibaba/BytePlus free quotas. Keep Pro/Opus-class models only for the story and judge calibration (batch API for 50% off where not interactive).
3. Stills: Nano Banana 2 / Seedream 5.0 lite (about $0.035-$0.067) for character-reference shots; reserve Nano Banana Pro ($0.134) for hero keyframes.
4. One rented 5090 (about $0.4-$0.65/h on Vast) for 2-3 hours (about $2) to measure real Wan 2.2 LightX2V and LTX-2.5 distilled speed/quality on your own shots: this closes the biggest unknown in section 7.
5. Run TTS Vietnamese A/B (Gemini 3.8 Flash TTS vs ElevenLabs v3 vs Azure vi-VN vs MiniMax vs VieNeu) on 20 real lines with native listeners before locking a stack; no pricing page confirms Vietnamese emotion quality.
6. Do not buy commitment packs/resource packs during the trial.

### (ii) Steady production, about 30 episodes/month
- Default stack: hybrid. Video: API for dialogue/hero shots (Veo 3.1 Lite/Fast or Kling 4.0 Flash or Seedance 2.0 Mini, whichever wins the bake-off) and, if the 5090 test passes, self-hosted Wan 2.2 LightX2V on a rented Blackwell/4090 for b-roll and retries. Expected **$4-$8/episode -> about $120-$240/month**, versus about $730-$1,180/month for premium-only.
- Use premium models (Kling 4.0 1080p, Nano Banana Pro) only as an escalation path for failed shots: model retries as a routing policy (cheap first attempt, premium after 2 fails) rather than a global default.
- LLM/judge: Gemini 3.8 Flash for judge and bulk; Pro/Sonnet-class for writing; use Batch (50% off) for non-interactive scripting/judging. Note the Dec/Jan price rises: Gemini 4 Carbon doubles Dec 1, Gemini 3.8 Flash and 3.8 TTS rise Jan 1, 2027; re-run this table in January.
- Do not build a Vietnamese-TTS dependency on an unpriced vendor (FPT/Zalo/Viettel/VieNeu API) until a price is obtained from them.

## 10. Facts / inferences / unknowns

### Facts (read on 2026-11-13 from the cited official pages)
- Veo 3.1 Lite/Fast/standard Vertex rates $0.05/$0.10/$0.40 per count; Gemini Omni 1.2 Flash $12/M video tokens; Nano Banana image prices; Gemini text/TTS prices; Lyria $0.08/song.
- Seedance token prices per 1M (1.0 Pro Fast $1; 2.0 Mini $3.5; 2.0 Fast $5.6; 2.0 $7.0; 2.5 $10.7); Seedream $0.018-$0.045/img.
- Kling per-second units (e.g., 4.0 1.0/1.5 u/s; 4.0 Flash 0.6 u/s) and image unit $0.0035.
- Wan/Qwen/Qwen-Image/TTS prices on Alibaba SG; MiniMax H3/Hailuo/TTS; LTX API; Vidu credits and RMB-per-credit; Runway credit = $0.01; Sync.so $0.04-$0.05/s; Azure TTS $15/1M chars; RunPod and Modal GPU rates; RunPod storage rates.
- Maintainer benchmark: LightWan2.2-A14B I2V 720p 26.7 s on a single RTX 5090 (NVFP4, Blackwell only); HunyuanVideo-1.5 distilled on 4090 within 75 s at 480p.
- Free quotas: Alibaba (90 days), Modal $30/mo, Google Cloud $300/90 days, Gemini free tier (text/TTS only).

### Inferences (derived; may be off)
- Kling video Unit = $0.14 (from fal and Runway matching).
- Seedance second-cost = tokens/s x rate (24 fps, W x H x fps x s / 1024); the per-resolution rate split is uncertain.
- Veo "count" = second.
- Clip length for LightWan2.2 timings is 5 s; Wan 4-step on 4090/L40S/H100 takes 120/120/50 s per clip (assumed, unmeasured).
- Vidu USD at 7.1 RMB/USD; judge token counts per image/video; utilization 50%; episode quantities in 8.1.
- fal charges about 2x BytePlus for Seedance 2.0 token rates and parity for Kling/Veo.
- Self-hosting is about 50-100x cheaper per second in raw compute than Wan API, but quality parity with Kling 4.0/Veo/Seedance 2.x is not established.

### Unknowns (need a direct check or a trial)
- Kling resource-pack tiers and any new-account credit; Luma Ray3.2 price; Runway Gen-4.5 price; Seedance Volcengine price; Seedance/Seedream free quota amount.
- Whether Google Cloud trial credit covers Veo; Veo in Gemini API price (not on current page).
- ElevenLabs v4/v3 exact price and Music/SFX per-minute; Stable Audio USD per credit; MiniMax music price; OpenAI TTS and gpt-image per-image price.
- Vietnamese quality and price for: Gemini TTS, ElevenLabs, Azure HD, MiniMax, Qwen/CosyVoice TTS, FPT.AI, Zalo, Viettel, VieNeu API; Vietnamese lip-sync quality for Kling/Sync/Hedra/HeyGen/LatentSync/MuseTalk.
- Real wall-clock for Wan 2.2 4-step, LTX-2.5 distilled, HunyuanVideo-1.5 on 4090/L40S/A100/H100; cold-start times and RunPod spot prices.
- Qwen-VL-Max / OpenRouter free models availability and prices; HeyGen/Hedra official API rates (conflicting SECONDARY numbers).
- Vietnamese writing/judging quality of cheap models (Flash, DeepSeek, Qwen, GLM, Kimi) versus Pro/Sonnet/Opus.

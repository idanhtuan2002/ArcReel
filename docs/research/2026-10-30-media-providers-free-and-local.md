# Media providers for a free proof run: local models on this host and free cloud tiers (2026-10-30)

Goal (sponsor, 2026-10-30): make the deployed V2.1 product usable end to end now (Produce stage: image, video, TTS),
at no cost, to prove the product works; paid cloud models come after the proof.

## 1. Facts: this host and ArcReel

| Item | Value | Consequence |
| --- | --- | --- |
| GPU | NVIDIA RTX 2070, 8 GB, Turing (compute 7.5) | FP16 only (no native bf16/FP8); 8 GB class models only, with offloading |
| RAM / CPU | 22 GB RAM | Offloading large text encoders is tight |
| Disk | `/` 195 GB, **6.5 GB free (97 %)** | Any local model path needs space first (safe reclaim: uv cache 7 GB, `~/.cache/pytmp` 2.9 GB, Docker reclaimable ~8.6 GB) |
| GPU sharing | Ollama models (gemma3:12b, 9B story models) use the same GPU | Story authoring and local media generation cannot run at the same time |
| ArcReel image backends | gemini (AI Studio + Vertex), ark, grok, openai, vidu, dashscope, minimax, kling, agnes, custom (ComfyUI, declarative) | No code change needed for DashScope, Gemini/Vertex or a ComfyUI workflow |
| ArcReel video backends | same set + ComfyUI video workflows + declarative endpoints | idem |
| ArcReel TTS backends | dashscope, openai-compatible `/v1/audio/speech` | A local TTS needs an OpenAI-compatible shim |
| Already on disk | `~/VieNeu-TTS` (repo) and the `pnnbao-ump/VieNeu-TTS-v3-Turbo` weights in the HF cache | Vietnamese TTS is available locally without a download |

## 2. Local options (free, unlimited, slow)

| Need | Candidate | Fits 8 GB? | Notes |
| --- | --- | --- | --- |
| Image | **FLUX.2 [klein] 4B** (GGUF Q4 ≈ 2.6 GB, 4 steps, Apache-2.0) | Yes, with headroom | Most cited 8 GB pick in 2026 guides; 9B also reported at Q4 |
| Image | Z-Image Turbo (FP8 ≈ 8 GB, GGUF ≈ 6 GB) | Tight | Sources disagree on VRAM |
| Image | FLUX.1 GGUF Q4_K_S | Yes | Largest LoRA ecosystem; RTX 2070 listed explicitly |
| Video | **Wan 2.2 TI2V-5B** (FP8/GGUF, 720p@24 fps, no audio) | Yes, with offloading | Most mature ComfyUI support |
| Video | LTX-2.3/2.5 GGUF (≥ Q4) | Reported at 8 GB | Native audio; quality poor below Q4 |
| TTS (vi) | **VieNeu-TTS v3 Turbo** (Apache-2.0, voice cloning from 3–5 s) | Yes (also CPU/ONNX) | Already downloaded; needs an OpenAI-compatible shim for ArcReel |

Inference (not measured): a 4090 makes a 5 s 720p Wan 2.2 5B clip in about 9 min; an RTX 2070 at 480p with offloading
is likely 20–45 min per 5 s clip. One episode of 10–20 shots would take many hours, so local video fits an overnight proof,
not daily use. FLUX.2 klein images should take well under a minute each. These numbers must be measured here.

## 3. Free cloud options (no cost, limited quota)

| Provider (ArcReel backend) | Free quota (verified 2026-10-30) | Fit |
| --- | --- | --- |
| **Alibaba Model Studio / DashScope, Singapore region** (`dashscope`, native) | Images: z-image-turbo 100, wan2.1-t2i-turbo 200, wan2.1-t2i-plus 200, qwen-image-2.0 100, wan2.7-image 50 (≈ 650+ images). Video: wan2.1-t2v-turbo 50 s, wan2.1-t2v-plus 50 s, wan2.1 i2v turbo/plus 50 s each, wan2.1-kf2v-plus 50 s, wan3.0-video 30 s (≈ 280 s). TTS: qwen3-tts-flash 110 000 chars, cosyvoice-v3 10 000 chars. Valid 90 days from activation; Singapore only | **Best free path**: image + video + TTS through an existing backend; enough for a few episodes. Vietnamese voice support of qwen3-tts/cosyvoice is unverified |
| Google Gemini API (AI Studio) (`gemini`) | Text models (2.5 Flash / Flash-Lite) free; **every image and video model is paid** (Nano Banana $0.039/image) | Not free for media |
| Google Cloud trial (Vertex, `gemini` vertex mode) | $300 credit, 90 days, card required; Veo/Imagen coverage by the trial is not confirmed in Google docs | Possible large free budget; unverified |
| BytePlus ModelArk (`ark`) | New-user free inference quota (docs mention 500 k tokens, "free tokens only" mode); Seedream/Seedance amounts not shown publicly | Unverified for media |
| Cloudflare Workers AI | 10 000 neurons/day free; FLUX.1 schnell ≈ 43 neurons per 512² 4-step image (arithmetic from the official table) | Not a native backend; would need a custom adapter |
| Zhipu CogView-3-Flash / CogVideoX-Flash | Reported free on the China-domestic platform only | Lower quality; not verified from official docs |

### 3.1 What ArcReel's DashScope backend can use of that quota (checked in lib/config/registry.py at r2-v2.1.0)

- The base URL is configurable (`lib/dashscope_shared.py`), so the provider can point at the Singapore host
  `https://dashscope-intl.aliyuncs.com` where the free quota applies (default is Beijing).
- Registered models overlapping the free quota: images `qwen-image-2.0` (100), `wan2.7-image` (50), `wan2.7-image-pro`
  (50) ≈ 200 images; video only `wan3.0-video` (30 s ≈ 6 shots of 5 s); TTS `qwen3-tts-flash` (110 000 chars).
- The wan2.1 models with the larger free video quota (≈ 250 s) are not in ArcReel's registry; using them would need a
  registry addition. So free cloud video is enough for a short proof only, and local video matters more.

## 4. Recommendation (decided)

1. **Cloud first for the proof: DashScope (Singapore) with its free quota.** It is native in ArcReel (image, video, TTS),
   needs no code, and its quota covers several episodes. The sponsor creates the Alibaba Cloud international account and
   API key (the agent may not create accounts or enter keys).
2. **Local in parallel, no key needed:**
   - Vietnamese narration: VieNeu-TTS v3 Turbo behind a small OpenAI-compatible `/v1/audio/speech` shim on the host;
     ArcReel's `openai` audio backend points at it.
   - Images: ComfyUI + FLUX.2 klein 4B GGUF as an unlimited fallback.
   - Video: ComfyUI + Wan 2.2 TI2V-5B for overnight runs only, after measuring one clip.
   Requires reclaiming disk first and downloading ComfyUI and the weights (sponsor approval for the downloads).
3. **Not now:** Gemini media (paid), Cloudflare (needs an adapter), Zhipu (China-only, unverified).
4. After the proof, pick the paid provider by measured quality per shot (DashScope Wan 3.0, Seedance, Kling, Veo).

## 5. Unknowns to close by measurement

- Whether DashScope qwen3-tts / cosyvoice voices read Vietnamese well (else VieNeu stays the TTS).
- RTX 2070 time per FLUX.2 klein image and per Wan 2.2 5B clip.
- Whether wan2.7 video models carry any free quota (not shown in the pricing excerpt).

## 6. Measured on this host (2026-10-30)

- VieNeu-TTS v3 Turbo (CPU/ONNX, offline, `HF_HUB_OFFLINE=1`): 20 built-in Vietnamese voices; 3.9 s of 48 kHz speech in
  5.7 s including model load. Behind the OpenAI-compatible shim `~/arcreel-v2-staging/vieneu-tts-shim/server.py`
  (127.0.0.1:23340), ArcReel's OpenAI SDK client lists the model and receives wav and mp3 (two sentences in 6.2 s).
  The shim maps ArcReel's OpenAI voice ids to VieNeu voices (nova → Trúc Ly, onyx → Xuân Vĩnh, ...).

## Sources

- Alibaba Cloud Model Studio pricing (official): https://www.alibabacloud.com/help/en/model-studio/model-pricing
- Gemini API pricing (official): https://ai.google.dev/gemini-api/docs/pricing
- Cloudflare Workers AI pricing (official): https://developers.cloudflare.com/workers-ai/platform/pricing/
- BytePlus ModelArk free inference quota: https://docs.byteplus.com/docs/ModelArk/free-inference-quota
- Google Cloud free trial: https://cloud.google.com/free
- Local video model guides: https://www.thundercompute.com/blog/best-open-source-ai-video-generation-models ,
  https://insiderllm.com/guides/local-ai-video-generation/ , https://www.earngenix.com/workflows/best-local-ai-video-model-2026 ,
  https://runaihome.com/blog/wan-video-local-ai-gpu-guide-2026/
- Local image model guides: https://localaimaster.com/blog/run-flux-on-low-vram-gpu ,
  https://botmonster.com/ai/best-local-image-generation-models-2026/
- VieNeu-TTS: https://github.com/pnnbao97/VieNeu-TTS
- Zhipu flash models (third-party claim): https://dev.to/vvvvking/a-genuinely-free-ai-video-image-generation-api-no-credit-card-with-working-python-code-24n5

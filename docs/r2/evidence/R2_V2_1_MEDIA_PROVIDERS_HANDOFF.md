# V2.1 media providers handoff (2026-10-30, paused for weekly quota)

Resume entry for "make the deployed V2.1 usable now with free providers". Research and decision:
`docs/research/2026-10-30-media-providers-free-and-local.md`.

## State (verified 2026-10-30)

- Production `r2-v2.1.0` healthy on 127.0.0.1:1251; quality probes enabled (C4).
- TTS done: VieNeu-TTS v3 Turbo behind `~/arcreel-v2-staging/vieneu-tts-shim` (OpenAI `/v1/audio/speech`,
  127.0.0.1:23340), user service `vieneu-tts-shim.service` active, linger enabled for `anhtuan`. ArcReel custom
  provider `custom-2` "VieNeu TTS (local)" (placeholder key `local`), default narration
  `custom-2/vieneu-tts-v3-turbo`, voice `nova`.
- Default image/video models on production are still **paid Gemini** (Veo 3.1, Gemini 3.1 Flash Image, existing AI
  Studio key). Do not generate media with them without the sponsor's decision.
- Disk `/`: 25 GB free after the user-level and sudo system cleanup and removing Ollama models ornith:9b, ornith-32k:9b and gemma3:12b (sponsor request; kept qwen3.5-vimax:9b and bge-m3). The Ollama custom provider `custom-1` still lists `gemma3:12b`; remove that row in Settings or re-pull the model if a story needs it.
- No ComfyUI server on this host (ArcReel has only the V2-03 client).

## Sponsor approvals already given (2026-10-30)

Download and install for local images (≈ 12–13 GB):
- ComfyUI server (github.com/comfyanonymous/ComfyUI) with its own venv (PyTorch CUDA wheels from PyPI, ≈ 6 GB);
- ComfyUI-GGUF custom node (GitHub);
- `unsloth/FLUX.2-klein-4B-GGUF` → `flux-2-klein-4b-Q4_K_M.gguf` (2.6 GB);
- text encoder `Comfy-Org/Flux-2-Klein-4B` `split_files/text_encoders/qwen_3_4b_fp4_flux2.safetensors` (3.85 GB) or a
  Qwen3-4B GGUF equivalent if FP4 does not run on Turing (RTX 2070, FP16 only);
- VAE `Comfy-Org/Flux-2-Klein-4B` `split_files/vae/flux2-vae.safetensors` (0.34 GB).

## Next steps

1. Install ComfyUI under `~/comfyui` (loopback `127.0.0.1:8188`), the GGUF node and the weights above; check free disk
   before each download (stop at < 3 GB).
2. Build and run a FLUX.2 klein 4B text-to-image workflow in ComfyUI; measure time per 1024² image on the RTX 2070;
   confirm it does not run while Ollama holds the GPU (story authoring).
3. Export the workflow in API format, add an ArcReel `comfyui` custom provider (Settings → Providers), bind
   prompt/size/seed/output nodes, test, then set it as the default image model (sponsor sees cost = 0).
4. Run one image through a real project on production; record evidence.
5. Later: Wan 2.2 TI2V-5B video (≈ +12 GB, overnight only) and/or DashScope Singapore key from the sponsor
   (`https://dashscope-intl.aliyuncs.com`; models qwen-image-2.0, wan3.0-video).

## Other open work (pointers)

- M9-B accepted with conditions, branch `impl/r2-m9b-acquisition-observations` pushed, not released
  (`.superpowers/sdd/2026-10-20-r2-m9b-manual-recovery-v2/independent-final-review.json` in the r2-m9b worktree).
- Next roadmap packet when resumed: M9-C (signals, candidates, donor parity).

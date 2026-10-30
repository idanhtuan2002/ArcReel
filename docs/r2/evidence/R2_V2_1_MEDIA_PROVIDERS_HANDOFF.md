# V2.1 media providers handoff (2026-10-30, local image gate completed)

Resume entry for "make the deployed V2.1 usable now with free providers". Codex resumed the approved local-image work on 2026-10-30. Research and decision:
`docs/research/2026-10-30-media-providers-free-and-local.md`.

## State (verified 2026-10-30)

- Production `r2-v2.1.0` healthy on 127.0.0.1:1251; quality probes enabled (C4).
- TTS done: VieNeu-TTS v3 Turbo behind `~/arcreel-v2-staging/vieneu-tts-shim` (OpenAI `/v1/audio/speech`,
  127.0.0.1:23340), user service `vieneu-tts-shim.service` active, linger enabled for `anhtuan`. ArcReel custom
  provider `custom-2` "VieNeu TTS (local)" (placeholder key `local`), default narration
  `custom-2/vieneu-tts-v3-turbo`, voice `nova`.
- Default image model is now `custom-3/flux2-klein-4b-gguf`, ComfyUI local, configured price 0. API comparison after Save and reload confirmed only `settings.default_image_backend` changed. Video remains **paid Gemini / Veo 3.1**; free/local video is not configured.
- Disk `/`: about 32.94 GiB available after cleanup and verified ComfyUI/Ollama storage migration; D has about 157.78 GiB free. Current migration/rollback evidence: `media-local-2026-10-30/storage-D/README.md`. No partition changes performed.
- ComfyUI source/venv stay at `~/comfyui`, loopback `http://127.0.0.1:8188`, user service `arcreel-comfyui.service` enabled. Models and provider media now live under `/mnt/arcreel/D/ArcReel/`, mounted by UUID with tested automount. Current unit and path configuration are in `media-local-2026-10-30/storage-D/`. ArcReel project-managed asset copies remain on ext4.
- Ollama model store is now `/mnt/arcreel/D/ArcReel/ollama/models`, exposed only inside its system service at `/var/lib/ollama-models`; service identity and both model digests preserved. Native chat, embedding and the deployed ArcReel client passed after deleting originals/restart. Evidence/rollback: `media-local-2026-10-30/ollama-D/README.md`.
- Image workflow endpoint `ce-1`, provider `custom-3` "ComfyUI local (RTX 2070)", model `flux2-klein-4b-gguf`, image concurrency 1. Qwen3 Q4_K_M GGUF encoder is used on Turing instead of FP4.
- Fresh inference: 1024 x 1024 benchmark succeeded in 34.787 s client wall time (33.75 s ComfyUI); production project character sheet 1792 x 1008 succeeded in 22.22 s execution timestamps (22.27 s ComfyUI log). Both outputs visually inspected. No Human quality/release acceptance claimed.
- Production proof: `http://127.0.0.1:1251/app/projects/local-media-proof-2026-1-f4bd3cf4/characters`, character "Linh - Local image proof". Existing story project was preserved.
- Evidence: `media-local-2026-10-30/` contains API workflow, saved endpoint definition, upstream model SHA256 pins, installed Python versions, histories, result image, UI screenshot, configuration verification and execution notes.
- Ollama was unloaded (`/api/ps` empty) before image tests; GPU VRAM returned to 417 MiB after inference. Concurrent Ollama/media execution has not been tested; use the GPU serially. Workflow is text-to-image only; reference images and negative prompt are explicitly marked unsupported.
- No application source code or database schema was changed. The app remains at deployed HEAD `0cef69a772f1d2946e452b918a8839b0f37fd2d9` (`r2-v2.1.0`).


## Sponsor approvals already given (2026-10-30)

Download and install for local images (≈ 12–13 GB):
- ComfyUI server (github.com/comfyanonymous/ComfyUI) with its own venv (PyTorch CUDA wheels from PyPI, ≈ 6 GB);
- ComfyUI-GGUF custom node (GitHub);
- `unsloth/FLUX.2-klein-4B-GGUF` → `flux-2-klein-4b-Q4_K_M.gguf` (2.6 GB);
- text encoder `Comfy-Org/Flux-2-Klein-4B` `split_files/text_encoders/qwen_3_4b_fp4_flux2.safetensors` (3.85 GB) or a
  Qwen3-4B GGUF equivalent if FP4 does not run on Turing (RTX 2070, FP16 only);
- VAE `Comfy-Org/Flux-2-Klein-4B` `split_files/vae/flux2-vae.safetensors` (0.34 GB).

## Next steps

1. Local-image installation/integration/proof is complete. Use the ComfyUI model already selected as the global image default. A project's explicit model override takes priority; inspect it before generating from an existing project.
2. Free video remains open. Wan 2.2 TI2V-5B needs roughly another 12 GB plus working space; current root free disk is about 32.94 GiB and the D model/media store has about 157.78 GiB free. Use the configured D store, verify exact artifact sizes and obtain any needed download authorization before adding it. Alternatively configure DashScope Singapore after the sponsor supplies the account/key and verifies applicable free quota.
3. Image editing/reference-guided image workflows are not part of the verified text-to-image workflow. They need their own workflow and project-level proof.
4. Full story-to-video proof remains incomplete until free video is configured and a real short clip is generated. M9-C is separate roadmap work.

## Other open work (pointers)

- M9-B accepted with conditions, branch `impl/r2-m9b-acquisition-observations` pushed, not released
  (`.superpowers/sdd/2026-10-20-r2-m9b-manual-recovery-v2/independent-final-review.json` in the r2-m9b worktree).
- Next roadmap packet when resumed: M9-C (signals, candidates, donor parity).

# V2.1 media providers handoff (2026-10-30, local image, Wan and three-scene pipeline proofs completed)

Resume entry for "make the deployed V2.1 usable now with free providers". Codex resumed the approved local-image work on 2026-10-30. Research and decision:
`docs/research/2026-10-30-media-providers-free-and-local.md`.

## State (verified 2026-10-30)

- Production `r2-v2.1.0` healthy on 127.0.0.1:1251; quality probes enabled (C4).
- TTS done: VieNeu-TTS v3 Turbo behind `~/arcreel-v2-staging/vieneu-tts-shim` (OpenAI `/v1/audio/speech`,
  127.0.0.1:23340), user service `vieneu-tts-shim.service` active, linger enabled for `anhtuan`. ArcReel custom
  provider `custom-2` "VieNeu TTS (local)" (placeholder key `local`), default narration
  `custom-2/vieneu-tts-v3-turbo`, voice `nova`.
- Default image model is now `custom-3/flux2-klein-4b-gguf`, ComfyUI local, configured price 0. API comparison after Save and reload confirmed only `settings.default_image_backend` changed. Video is now `custom-3/wan2.2-ti2v-5b-gguf` (Wan 2.2 5B Q4 on the same local ComfyUI provider, price 0), with native video audio disabled. API readback after reload confirmed those two video fields changed and other captured defaults were preserved.
- Disk `/`: about 32.94 GiB available after cleanup and verified ComfyUI/Ollama storage migration; D has about 150 GiB free after installing Wan. Current migration/rollback evidence: `media-local-2026-10-30/storage-D/README.md`. No partition changes performed.
- ComfyUI source/venv stay at `~/comfyui`, loopback `http://127.0.0.1:8188`, user service `arcreel-comfyui.service` enabled. Models and provider media now live under `/mnt/arcreel/D/ArcReel/`, mounted by UUID with tested automount. Current unit and path configuration are in `media-local-2026-10-30/storage-D/`. ArcReel project-managed asset copies remain on ext4.
- Ollama model store is now `/mnt/arcreel/D/ArcReel/ollama/models`, exposed only inside its system service at `/var/lib/ollama-models`; service identity and both model digests preserved. Native chat, embedding and the deployed ArcReel client passed after deleting originals/restart. Evidence/rollback: `media-local-2026-10-30/ollama-D/README.md`.
- Image workflow endpoint `ce-1`, provider `custom-3` "ComfyUI local (RTX 2070)", model `flux2-klein-4b-gguf`, image concurrency 1. Qwen3 Q4_K_M GGUF encoder is used on Turing instead of FP4.
- Fresh inference: 1024 x 1024 benchmark succeeded in 34.787 s client wall time (33.75 s ComfyUI); production project character sheet 1792 x 1008 succeeded in 22.22 s execution timestamps (22.27 s ComfyUI log). Both outputs visually inspected. No Human quality/release acceptance claimed.
- Production proof: `http://127.0.0.1:1251/app/projects/local-media-proof-2026-1-f4bd3cf4/characters`, character "Linh - Local image proof". Existing story project was preserved.
- Evidence: `media-local-2026-10-30/` contains API workflow, saved endpoint definition, upstream model SHA256 pins, installed Python versions, histories, result image, UI screenshot, configuration verification and execution notes.
- Ollama was unloaded (`/api/ps` empty) before image tests; GPU VRAM returned to 417 MiB after inference. Concurrent Ollama/media execution has not been tested; use the GPU serially. Workflow is text-to-image only; reference images and negative prompt are explicitly marked unsupported.
- Wan endpoint `ce-2` and model are installed on D (7.91 GiB, all SHA256 verified). Actual ArcReel UI I2V proof succeeded: 576 x 1024, 49 frames / 24 fps, 2.041667 s silent H.264 MP4, 250.297 s generation, sampled peak GPU 6920 MiB. Native T2V preview 288 x 512 also retained. Both decoded and visually inspected; UI video playback worked. Details/clip/rollback: `media-local-2026-10-30/wan-2.2/README.md`. Current runtime projects this endpoint as I2V; normal text-only app routing is not verified. Longer/higher resolution and automated story authoring remain untested. A later operator-authored three-scene episode proof completed normal storyboard/TTS/video jobs plus native narrated export and FFmpeg assembly; see below.
- Three-scene episode proof now complete in the dedicated project: Episode 1 “Buổi sáng bắt đầu”, UI Done 3/3, all 9 normal app queue jobs succeeded (3 FLUX, 3 VieNeu, 3 Wan). Final MP4 576 x 1024, 24 fps, 6.125 s, Vietnamese narration/captions; native editable draft export has 3 video/audio/text segments. MP4 rendered with FFmpeg from exact app-selected native presentations; full decode, source frame/audio lineage and browser playback passed. Evidence/deliverables/limits: `media-local-2026-10-30/three-scene-proof/README.md`.
- No application source code or database schema was changed. The app remains at deployed HEAD `0cef69a772f1d2946e452b918a8839b0f37fd2d9` (`r2-v2.1.0`).


## Sponsor approvals already given (2026-10-30)

Download and install for local images (≈ 12–13 GB):
- ComfyUI server (github.com/comfyanonymous/ComfyUI) with its own venv (PyTorch CUDA wheels from PyPI, ≈ 6 GB);
- ComfyUI-GGUF custom node (GitHub);
- `unsloth/FLUX.2-klein-4B-GGUF` → `flux-2-klein-4b-Q4_K_M.gguf` (2.6 GB);
- text encoder `Comfy-Org/Flux-2-Klein-4B` `split_files/text_encoders/qwen_3_4b_fp4_flux2.safetensors` (3.85 GB) or a
  Qwen3-4B GGUF equivalent if FP4 does not run on Turing (RTX 2070, FP16 only);
- VAE `Comfy-Org/Flux-2-Klein-4B` `split_files/vae/flux2-vae.safetensors` (0.34 GB).

Wan local download/install and real clip verification were separately authorized by the sponsor later in the same session (`lam luon`, `tiep tuc`). No further download approval is pending for this installed package.

## Next steps

1. Local-image installation/integration/proof is complete. Use the ComfyUI model already selected as the global image default. A project's explicit model override takes priority; inspect it before generating from an existing project.
2. Local video installation and the ArcReel endpoint-test proof are complete. Start with a first-frame image, 2 s, 480p, portrait; this produces 576 x 1024 at 24 fps on RTX 2070. The workflow is silent; keep native video audio off and use narration separately. Run FLUX/Wan/Ollama serially. Expand duration/resolution only with a new measured proof. See `media-local-2026-10-30/wan-2.2/`.
3. Image editing/reference-guided image workflows are not part of the verified text-to-image workflow. They need their own workflow and project-level proof.
4. The operator-authored three-scene media pipeline proof is complete, including normal episode jobs, narration presentation/export and watchable MP4 assembly. Automated source-to-story authoring, editor import and independent Human creative/release acceptance remain open. The current app-native export is an editable draft/bundle; the MP4 was assembled with FFmpeg. M9-C is separate roadmap work.

## Other open work (pointers)

- M9-B accepted with conditions, branch `impl/r2-m9b-acquisition-observations` pushed, not released
  (`.superpowers/sdd/2026-10-20-r2-m9b-manual-recovery-v2/independent-final-review.json` in the r2-m9b worktree).
- Next roadmap packet when resumed: M9-C (signals, candidates, donor parity).

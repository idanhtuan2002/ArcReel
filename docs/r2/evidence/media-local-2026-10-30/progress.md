# Local media execution, 2026-10-30

Base: `96efcf124651be7998ff179a6deb8da2070856db` (m10-c); deployed HEAD `0cef69a772f1d2946e452b918a8839b0f37fd2d9`.

Sponsor authorized resuming the media-provider handoff and production configuration. Existing root dirty files preserved. No application code changes planned.

- Fresh preflight: production /health OK; RTX 2070, 8192 MiB, 244 MiB in use; disk 24 GiB available.
- Dedicated browser session `arcreel-media-20261030`; logged into ArcReel.
- ComfyUI source archive pin b5a432157de6b8884f81104cd02926adf4d597e4; ComfyUI-GGUF 6ea2651e7df66d7585f6ffee804b20e92fb38b8a.
- Model pin FLUX a09d5bb51ac4000ccd9643d10e9db3ed14200508; encoder unsloth/Qwen3-4B-GGUF 22c9fc8a8c7700b76a1789366280a6a5a1ad1120; VAE Comfy-Org/flux2-klein 5b3abca5c0dc1ecd4eaf3340868d09063fc1c965.
- Ruling: use Qwen3 Q4_K_M GGUF instead of FP4 on Turing, as allowed by the accepted handoff. Compatibility must be proved by inference.
- Ruling: use source archives after slow Git clone; stop only our own clone. Archive pins retained above.
- PyTorch install initially failed due to /tmp quota; retry uses TMPDIR=~/comfyui/.tmp and no uv cache.
- Workflow follows official Comfy-Org/workflow_templates image_flux2_klein_text_to_image distilled subgraph: euler, CFG 1, Flux2Scheduler 4 steps; only loaders replaced by GGUF, SaveImage added.

Pending: install dependencies; verify CUDA sm75; verify hashes; run actual 1024-square image; persist service; configure ArcReel endpoint/provider; prove project generation and record evidence.

## Verified installation gates

- Git clones eventually completed: both exact source HEADs match the pins. No source modifications.
- `torch 2.9.1+cu128`, CUDA available, GPU NVIDIA GeForce RTX 2070, built arch list includes sm_75. Actual CUDA FP16 matrix multiplication returned 256.0 as expected.
- All three model sizes and SHA256 match upstream LFS metadata; see model-lock.json.
- ArcReel endpoint `ce-1` (record id 1) and provider `custom-3` (id 3), model `flux2-klein-4b-gguf` (id 6), saved through UI. API GET confirmed image price 0, model enabled, endpoint bindings persisted. No default changed yet.
- Preview proved both scheduler and latent receive the same 1008 x 1792 for portrait 1K; prompt and randomized seed propagated.
- Workflow explicitly marks negative_prompt and reference_images unsupported.

## Inference gates

- Benchmark 1024 x 1024: success, 34.787 s client wall time, ComfyUI 33.75 s. Prompt 3199f7bd-9c0f-4be7-a667-3c879d4538ca.
- Project `local-media-proof-2026-1-f4bd3cf4`, character `Linh - Local image proof`: UI Generate Asset Sheet -> Done 1 / Failed 0. Real Comfy prompt 0c66895c-91af-4860-9847-9881bb74cf7e, 1792 x 1008, 22.220 s execution timestamps; ComfyUI log 22.27 s.
- Both images visually inspected; character sheet shows front/profile/back views with white blouse and office setting. No quality panel claimed.
- Ollama /api/ps was empty before inference. After first run VRAM dropped to 417 MiB at idle (no manual /free call needed). Concurrent story-authoring and media generation remain untested; serialize operator use.
- User service arcreel-comfyui.service enabled, loopback only. /system_stats OK.

## Final verification

- Global image default saved and browser reloaded: ComfyUI local (RTX 2070) / flux2-klein-4b-gguf. API diff against private pre-change snapshot contains exactly `.settings.default_image_backend`; value `custom-3/flux2-klein-4b-gguf`.
- TTS remains `custom-2/vieneu-tts-v3-turbo`; video remains paid `gemini-aistudio/veo-3.1-generate-preview`.
- With queue empty, `systemctl --user restart arcreel-comfyui.service` succeeded; subsequent `/system_stats` reports ComfyUI 0.43.0. Unit enabled; actual host reboot was not performed.
- `systemd-analyze --user verify` exited 0; it emitted an unrelated installed spice-vdagent unit warning about StandardError in [Install].
- Final `/health` OK, ComfyUI and VieNeu user services active. Disk remains 11 GB available; no additional video models downloaded.
- JSON parsing, both inference-success assertions, image-default assertions, and `git diff --check` passed. No application source/tests/schema changed, so application suites were not run.
- ComfyUI startup warns optimized CUDA kernels need cu130; this installation uses the eager backend with cu128 and passed both real inference runs on sm75. Do not silently upgrade torch without rerunning these probes.
- Evidence and handoff are limited to text-to-image production usability. No video, image-reference/editing, concurrent GPU workload, complete episode, quality-review or release gate is accepted by these runs.

## Operation and recovery

- App: http://127.0.0.1:1251 . ComfyUI: http://127.0.0.1:8188 . TTS: http://127.0.0.1:23340/v1 .
- Service: `systemctl --user status arcreel-comfyui.service`; logs: `journalctl --user -u arcreel-comfyui.service`.
- Sources: `~/comfyui` and `~/comfyui/custom_nodes/ComfyUI-GGUF`; dependencies in `~/comfyui/.venv`; local constraints retain torch 2.9.1+cu128 and torchvision 0.24.1+cu128.
- Existing project model overrides may supersede the new global image default. Select ComfyUI explicitly for such projects.
- Use story generation and image generation serially on the shared GPU. Check Ollama `/api/ps` before a measured image run; no automatic cross-service mutual exclusion was added.
- A private pre-default-change config snapshot is at `~/comfyui/arcreel-config-before-image-default.json`, mode 0600. It is not in the repository. To restore only the old image default, select AI Studio / Gemini 3.1 Flash Image in Settings -> Default models -> Save; do not replay the whole config blindly.
- Next open media gate: choose/research free video with enough disk or a sponsor-supplied cloud account/key. Current free disk is less than the planned Wan download plus working space.

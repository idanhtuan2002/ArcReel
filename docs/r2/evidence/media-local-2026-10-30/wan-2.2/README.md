# Wan 2.2 5B local — verified 2026-10-30

Installed 8,497,662,272 bytes (7.91 GiB) of SHA256-verified Q4 GGUF model/encoder and official VAE on D. Exact upstream revisions, names, sizes and hashes: model-lock.json. Reused installed ComfyUI/GGUF and native video nodes; no packages, application code or schema changed.

Evidence checkout base: 482687e35a2af355add4dd3e7f0d67a620d32cdc (`design/r2-m10-c-operator-surface`). Deployed checkout: 0cef69a772f1d2946e452b918a8839b0f37fd2d9. This record covers live operational configuration and the two retained outputs, not a new application release.

## Use

ArcReel: http://127.0.0.1:1251 . Global video model is `custom-3/wan2.2-ti2v-5b-gguf`, endpoint `ce-2`. Select 2 seconds, 480p, 9:16, and supply a first image. Exact dimensions are 576 x 1024 because the request builder preserves the ratio with 32-pixel steps. Generate Video with Audio is off; add narration separately with the existing VieNeu default. Explicit project overrides still take priority over the global model.

The native workflow is hybrid and can render without an image; current ArcReel runtime capability projection exposes this bound endpoint as I2V only. Native T2V is verified at 288 x 512, not accepted as normal app text-only routing. Do not infer 720p/1080p/4K, longer duration, last-frame/reference support or simultaneous GPU workloads from generic UI options. Video model is deliberately configured for 2 s; use GPU serially with FLUX/Ollama.

## Results

- `t2v-proof.mp4`: 288 x 512, 49 frames, 24 fps, H.264, 2.041667 s, silent. First inference 91.017 s ended in an export configuration error; corrected export reused cached frames in 0.338 s. See both histories rather than treating the first failed queue status as success.
- `i2v-proof.mp4`: generated through ArcReel endpoint-test UI using the existing single-view FLUX office image. 576 x 1024, 49 frames, 24 fps, H.264, 2.041667 s, silent. ComfyUI execution 250.297 s, sampled GPU peak 6920 MiB. All four UI stages completed and browser playback succeeded.
- ffprobe metadata, SHA256, full ffmpeg decoding and adjacent-frame differences: clip-verification.json. Representative frame contact sheets and UI screenshots retained. Numeric differences establish changing frames, not creative quality; visual smoke inspection found subject retention and subtle head/eye motion in I2V. Human acceptance and full story-to-video remain separate.
- Only default_video_backend and video_generate_audio changed among captured global settings; see config-verification.json. Provider models and price 0 readback: provider-models-verification.json. Image FLUX, text model and narration VieNeu preserved.

Original MP4s remain under `/mnt/arcreel/D/ArcReel/media/comfyui/output/video/`. Models/media continue using the already-tested UUID automount. Root has about 33 GiB free and D about 150 GiB; no partition resize or reboot was performed for this setup.

## Reproduce / rollback

Use `saved-endpoint-definition.json` for a complete ArcReel endpoint import, or `wan-api-workflow.json` for raw ComfyUI import. SaveVideo uses flattened dynamic prompt keys (`format` and `format.codec`); a nested dict validates initially but omits the required argument at execution in this ComfyUI version. Static builder fixtures are retained, and i2v-history.json records the actual production trial graph/seed.

To return to the previous global behavior, Settings → Default models → choose AI Studio / Veo 3.1 and re-enable video audio, then Save. That previous provider is paid. To disable Wan while retaining local FLUX, disable only the Wan model under ComfyUI provider; leave ce-1/image configuration and services intact. Remove ce-2 or its three model files only after no project/job refers to them and ComfyUI is idle. No destructive rollback was performed.

Raw download progress logs: `/mnt/arcreel/D/ArcReel/operations/wan22-20261030/`. Full application test suites were not run because no application source/test/schema changed; actual inference, artifact decode/playback, API readback, queue and health checks are the relevant operational verification.

# Wan 2.2 local video setup — 2026-10-30

Base HEAD 482687e35a2af355add4dd3e7f0d67a620d32cdc. Sponsor authorized download/install and a real video proof. Existing image/TTS/Ollama setup and unrelated dirty root checkout remain preserved.

1. Pin QuantStack Wan 5B Q4_K_M, city96 UMT5 encoder Q4_K_M, and official Wan 2.2 VAE; download directly to D and verify LFS SHA256. Total 8497662272 bytes.
2. Reuse official Comfy-Org workflow_templates video_wan2_2_5B_ti2v.json at e7cd011d4ded3411c2f481200544f0be6fdc962e, existing ComfyUI b5a432157de6b8884f81104cd02926adf4d597e4 and GGUF node 6ea2651e7df66d7585f6ffee804b20e92fb38b8a. Keep 20 steps, CFG 5, uni_pc/simple, sampling shift 8. Use GGUF loaders and tiled native VAE decoding for 8 GB VRAM.
3. Confirm deployed ArcReel request builder supports optional first-frame pruning, width/height step 32, 4n+1 frames and fps 24. Probe T2V and I2V graph construction before GPU execution.
4. First benchmark: 288 x 512 portrait, 49 frames / 24 fps (about 2 seconds), text-to-video. Record GPU use, timing, result history, decoded video metadata and representative frames.
5. Import the hybrid workflow in ArcReel, bind parameters, add a zero-price video model to the existing local provider with serial GPU usage. Test real UI image-to-video using an existing generated FLUX image; inspect/download/decode the result. Set video default only after actual success.
6. Retain evidence, exact scope/quality/runtime limits and rollback. No paid provider calls, application code/schema changes or release approval is implied.

Ruling: use native SaveVideo/CreateVideo rather than adding VideoHelperSuite dependencies. Use native optional Wan22ImageToVideoLatent.start_image so one endpoint can serve T2V and I2V. Initial preview size is deliberately small; no claim about unmeasured 720p/long-duration performance.

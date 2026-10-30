# Wan local video execution ledger

Base HEAD 482687e35a2af355add4dd3e7f0d67a620d32cdc.

- Fresh preflight: root 33 GiB free, D 158 GiB free; RTX 2070 8192 MiB with 460 MiB in use; ComfyUI queue empty, Ollama unloaded, production health OK.
- Model files total 8497662272 bytes, all downloaded to D and verified against upstream LFS SHA256. See model-lock.json for exact revisions, sizes and hashes. No Python packages or application code changed.
- Official workflow template pinned e7cd011d4ded3411c2f481200544f0be6fdc962e, path templates/video_wan2_2_5B_ti2v.json. Existing ComfyUI b5a432157de6b8884f81104cd02926adf4d597e4 / GGUF 6ea2651e7df66d7585f6ffee804b20e92fb38b8a reused. Native node schemas captured.
- Replaced native FP16/FP8 loaders with Q4 GGUF loaders for Turing. Kept official 20 steps, CFG 5, uni_pc/simple and shift 8. Switched decode to native tiled VAE (512 tile, 32-frame temporal chunks) for bounded VRAM. Native CreateVideo/SaveVideo writes H.264 MP4; no external video-node package added.
- Draft binding probe initially exposed a configuration-key mismatch (first_frame vs the actual start_image key). Read deployed builder/bindings and corrected the draft; no product code was changed. Both probes now pass: T2V drops LoadImage 56 and optional Wan start_image; I2V retains it. Both have 49 frames at 24 fps.
- Exact aspect/step behavior: preview native 288 x 512; selecting ArcReel 480p at 9:16 with required step 32 yields 576 x 1024. This is recorded rather than silently claiming a 480-pixel width.
- Graph Tier 2 discovery/traces/snippets for ComfyuiVideoBackend.generate and build_workflow, coverage checked for backend/builder/bindings/inference_rules.video.json (no recorded gap, best-effort only). Deployed source read at 0cef69a772f1d2946e452b918a8839b0f37fd2d9. Static rules explicitly support Wan22 optional start_image and step sizes.
- ComfyUI restarted when idle; all three new model names discovered. Native T2V benchmark submitted as c709ca59-8e36-4cff-9d98-cb7a0e62032d; submission returned no node errors. GPU/time/history capture running.

Pending: benchmark result/decode/visual motion inspection; save endpoint/provider model; UI I2V proof; choose video default only after success; final rollback/handoff.

## Completed live verification

- First native run completed sampling/decoding in 91.017 s but failed at SaveVideo: the new dynamic combo API requires flattened prompt inputs, not the execution-time nested dict. Read the installed native node/schema and dynamic input parser; changed only workflow configuration to `format: "mp4"`, `format.codec: "h264"`. Cached export retry 44dd6929-b0c0-4649-a0da-082ed3f2842b succeeded in 0.338 s, reusing the first run's frames. No second full T2V timing is claimed.
- Reimported and saved endpoint ce-2, then reloaded before testing so the old test-panel draft could not be used. Saved definition read back through API and retained as saved-endpoint-definition.json.
- Real ArcReel UI I2V trial b31e373a-05c1-4810-ae90-ffb3f34372d0 succeeded in 250.297 s at 576 x 1024, 49 frames / 24 fps (2.041667 s). Submit, poll, result, and artifact fetch all show done. Browser decoded/played video (readyState 4, advancing time and presented frames, no video error). Sampled peak GPU use 6920 MiB; no OOM in this run.
- Both MP4s independently inspected with ffprobe and fully decoded with ffmpeg. H.264, no audio, all 48 adjacent frame pairs differ. Contact sheets at frames 0/24/48 were visually inspected. Native T2V has visible camera/head movement with softer rendering; I2V retains the input office/subject and subtle head/eye motion. This is technical/visual smoke verification, not Human creative or release acceptance.
- Provider custom-3 now contains flux2-klein-4b-gguf (ce-1) and wan2.2-ti2v-5b-gguf (ce-2), both price_input 0; image/video concurrency 1. Video configured for 2 s and resolution 480p. Provider model database row IDs changed on UI full save; stable model identifiers/endpoints are authoritative.
- After successful trial, saved global default_video_backend custom-3/wan2.2-ti2v-5b-gguf and video_generate_audio false. API readback compared selected defaults against pre-change snapshot: exactly these two fields changed. Image, text, narration model/voice and poll timeout preserved.
- Current runtime API advertises ce-2 as first-frame video, text_to_video false. Native no-image rendering works, but normal ArcReel text-only model routing is NOT accepted by this proof. No model capability overrides were written. The picker may show generic higher resolution/audio labels; actual verified workflow is silent, 2 seconds, portrait 480p (576 x 1024). Do not treat those labels as tested capability.
- Final root free about 33 GiB, D about 150 GiB; GPU returned to about 534 MiB after inference. ComfyUI queue empty and ArcReel health OK. Model download logs moved to /mnt/arcreel/D/ArcReel/operations/wan22-20261030/; no model payload is stored in Git.

Complete for local Wan installation, native T2V smoke proof, ArcReel I2V endpoint proof, and global video default. Full episode/story execution, longer clips, landscape/higher resolution, reference/last-frame workflows, narration mux and simultaneous Ollama inference remain untested. See README.md for use/rollback.

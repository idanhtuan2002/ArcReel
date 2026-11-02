# Still-image narration clip endpoint (local narration video route)

Wan 2.2 TI2V 5B is verified on the RTX 2070 only for 2-second clips (about 250 s each), while a narrated segment
read by VieNeu lasts about 7 s (3.7 syllables/s measured on a real run). Under `use_tts` every narration unit then
fails `request_duration_exceeds_maximum`; splitting units to 2 s would need 33-47 Wan clips (2.3-3.3 GPU hours)
per 45-second episode. For local runs, whose purpose is proving the automatic pipeline, the narration launch profile
therefore uses this endpoint: the unit's storyboard is the first frame, held for the requested frames.

- Graph: `LoadImage → ImageScale (576×1024, center crop) → RepeatImageBatch (frames) → CreateVideo (24 fps) →
  SaveVideo (H.264 MP4)`; the prompt binds to an unconnected `PrimitiveStringMultiline` (the clip has no prompt).
- `validate_comfyui_definition`: no errors, no warnings. Derived capabilities: first frame, no text-to-video, no
  references, silent.
- Real render (2026-11-02): a generated storyboard held for 169 frames = 7.04 s, 576×1024, in 3.1 s.
- Host setup: endpoint `ce-4` on the ComfyUI provider, model `still-clip-local` with supported durations 1-30 s (the clip has no length limit; 30 s holds about 110 narrated words), and
  the project's `video_backend` `custom-3/still-clip-local`. Wan stays configured for the drama profile and for
  production with stronger or cloud video models.

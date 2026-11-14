---
status: accepted
---

# An instrumental music bed under every episode

Decided 2026-11-13 by the main agent (craft program P0-5).

The automatic film had narration only: no music anywhere in composition or render.

1. **The cue.** The project overview (LLM, structured output) writes `music_caption`, an English description of an instrumental underscore (genre, mood, lead instruments and timbre, era and production texture; no vocals, no tempo numbers, no clashing styles), and `music_bpm` (50–160). This follows the ACE-Step 1.5 tutorial: the caption decides most of the result and tempo belongs in metadata, not in the caption.
2. **The generator.** A local ACE-Step 1.5 REST server (`acestep-api`, upstream code used as is) runs the 2B turbo DiT with its language model off: caption, tempo and length are given, so it has nothing to plan. With CPU offload of the DiT it needs about 5.4 GB of VRAM while generating and about 0.4 GB when idle, so it shares the RTX 2070 with ComfyUI. Before each request the client asks ComfyUI to free its models (`/free`). The episode's music is the episode's length plus 4 s at a fixed seed, cached under `production/music/<cue digest>.wav`. Without `ARCREEL_MUSIC_URL` the render has no music; a failed music request renders without music and logs it.
3. **The mix.** The renderer lays the music under the whole episode: 1.5 s fade in, 2.5 s fade out, set 10 LU under the speech, and ducked by `sidechaincompress` keyed on the speech (threshold 0.02, ratio 9, attack 200 ms, release 500 ms; VGA `tools/audio/audio_mixer.py@e46e9d3`, whose graph fed the compressor one input and is corrected here). The existing loudness master follows. The manifest records the music file, both loudnesses, the gain and whether it ducked.
4. **The master keeps the film's length.** Re-encoding in the loudness master could lengthen the audio by about 0.1 s when `loudnorm` falls back to dynamic limiting (real narration with sharp peaks), enough for a many-unit film to fail `FINAL_DURATION_MISMATCH`; the mastered audio is now cut to the film's length.

Host setup (done by the Human): run `/mnt/arcreel/D/ArcReel/ace-step-api.sh` (installed on the data disk; ACE-Step checkpoints about 10 GB there) and export `ARCREEL_MUSIC_URL=http://127.0.0.1:8001` and `ARCREEL_MUSIC_FREE_URLS=http://127.0.0.1:8188/free` in the app's start script.

Not covered: several candidates and a music judge, per-scene cues and leitmotifs (P2-13), ambience (P1-11).

Amended after the release review (M1): only a WAV answer is cached; any music failure (server, bad file, a silent bed) renders the episode without music, recorded as `{"skipped": <code>}` in the manifest, instead of blocking the render. The same holds for ambience (ADR-0150). Temporary download paths are unique per write.

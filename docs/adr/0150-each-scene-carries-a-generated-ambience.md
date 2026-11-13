---
status: accepted
---

# Each scene carries a generated ambience

Decided 2026-11-14 by the main agent (craft program P1-11).

The script already wrote `ambiance_audio` per shot, but the still-clip route has no sound, so the film had narration and (since ADR-0143) music over silence: no room, street or weather.

1. **The scene look names its ambience.** `SceneLook` (ADR-0141) gains `ambience`: two to four steady sound sources in English (the sound model reads English), derived from the set and the time of day, no speech, no music; a silent room is "quiet room tone".
2. **A local generator.** A small HTTP shim in front of MMAudio (text-to-audio, `large_44k_v2`, float16 on the RTX 2070) returns an 8-second clip for a prompt at a fixed seed; the model sits in host memory and moves to the GPU only while generating (6.4 GB peak, 0.15 GB idle). Clips are cached under `production/ambience/<digest>.wav`. Without `ARCREEL_AMBIENCE_URL` there is no ambience; a failed clip renders that scene without it and logs it. Stable Audio Open, the other candidate, is gated behind a Hub licence acceptance on the sponsor's account.
3. **The mix.** The renderer loops each scene's clip over that scene's window (0.6 s fades), 20 LU under the speech, before the music bed is laid and ducked and before the loudness master. The manifest lists each layer with its start and gain.

Setup and measurements: `docs/r2/evidence/media-local-2026-11-14-audio/`.

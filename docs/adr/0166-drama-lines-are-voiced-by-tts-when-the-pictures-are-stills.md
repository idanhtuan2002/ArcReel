---
status: accepted
---

# Drama lines are voiced by TTS when the pictures are stills

Decided 2026-11-15 on the sponsor's catalog (rank 5, dialogue drama with per-character voices; re-ranked after the no-video forms because local i2v costs about 250 s per 2 s of video). Research: [voiced dialogue on stills](../research/2026-11-15-r2-voiced-dialogue-on-stills.md). Donor: huohuo-drama @ f104b85, which voices each line with its speaker's TTS voice, muxes the lines with FFmpeg and assigns voices with `drama_voice_assign`.

## Decision

1. **The project chooses who delivers character speech.** The new project field `character_speech_delivery` takes `video` (the default, today's behaviour: the video model speaks and needs lip sync) or `tts`. With `tts`, a `CHARACTER_SPEECH` unit gets its sound from TTS like a narrator unit, and its video is a silent picture (still clip or silent motion). Narrator units are unchanged. A unit still never mixes character and narrator speech (`MIXED_SPEECH` stays a replan).
2. **Every speaking character has a TTS voice.** The character asset gains `tts_voice`, scoped to the audio route that chose it (`{provider_id, model_id, voice}`). It is assigned once from the route's voice catalog by the text route, using huohuo's criteria: sex, age band, temperament, prominence, leads easy to tell apart, the narrator's voice not reused. It is kept across episodes and editable by the user. A voice chosen for another route is re-assigned when the audio route changes.
3. **The unit's speech audio is one artifact.** It contains each utterance in its speaker's voice, in order, joined with a 250 ms gap. Its basis (`narration-delivery/tts-audio`, kind version 2 for character units) lists `[speaker, voice, text]` per utterance plus the route and speed. The artifact keeps the unit's existing path, version store and currency rules, so the presentation, render, review and export paths read it unchanged. Subtitles come from the utterances, as they do today.
4. **The automatic path.** A launch profile `fiction_drama_vi_v2` uses the narration profile's pictures, `requires_lip_sync: false` and `character_speech_delivery = tts`. A drama reviewer prompt variant drops "narrated" and asks for distinct, fitting voices per character. Reviewer qualification is bound to the new profile id, as every profile is (ADR-0165).

## Phases

- A: `tts_voice` on characters, the assignment step (text route plus catalog, checked: every speaking character has a voice from the catalog, and the leads' voices are distinct), and the project field.
- B: the TTS task, currency and admission for character units under `tts`; per-utterance synthesis and join.
- C: launch profile, reviewer prompt variant, qualification, and a smoke run on a two-character story.

Not covered: lip sync, voice cloning, emotion tags per line (the Gemini cue tags of ADR-0156 can follow).

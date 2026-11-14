---
status: accepted
---

# The narrator voices a delivery cue

Decided 2026-11-14 by the main agent (craft program P0-6) after the sponsor listened to samples and confirmed the cues sound real.

The deployed VieNeu-TTS v3 Turbo voices inline non-verbal tags (`[thở dài]`, `[cười]`, `[hắng giọng]`; README "Emotion cues", marked experimental upstream). The narration had no way to sigh or laugh.

1. **Prompt authoring picks the cue.** Each narration segment's visual layer carries `narration_cue` (`none`, `sigh`, `laugh`, `clear_throat`; default `none`), at most about one in five segments and only where the text shows the emotion (a sigh, wry laughter, a solemn announcement). Merging writes it on the segment.
2. **It is part of the spoken text, not the subtitles.** Speech preparation carries the cue for narrator voice-over; `canonical_narration_text`, which both the TTS request and the narration audio basis use, leads with the tag (`[thở dài] …`), so changing a cue regenerates that line. Subtitles come from the utterances and never show it.
3. **Only voices that speak the tags get them.** `synthesis_text` keeps the tags for `vieneu-tts-v3-turbo` and `vieneu-tts-v3-nano` and strips them for any other TTS model, which would read them aloud.

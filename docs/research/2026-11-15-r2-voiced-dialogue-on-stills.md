# Voiced dialogue on stills: per-character TTS for drama films without generated video

Date: 2026-11-15. Question: how can a drama film (V4, catalog rank 5) speak its characters' lines with distinct voices when the pictures are stills (no video model, no lip sync)? Sponsor priorities: quality first, free tiers, Vietnamese first.

## Facts: ArcReel today (impl/r2-film-quality @ r2-v2.5.34)

- **Unit speech modes.** `lib/speech_composition/__init__.py:177-215`: each script unit is `CHARACTER_SPEECH` (only character utterances), `NARRATOR_VOICEOVER` (only narrator text) or `SILENT`. Mixing the two in one unit is a `MIXED_SPEECH` problem that sends the unit back to replanning. A character unit may hold several speakers.
- **Drama scripts carry ordered utterances** `{kind: dialogue|voiceover, speaker, text}` per scene (`lib/script_models.py:506-541`, ADR 0040).
- **Character speech is routed to the video model.** The drama video prompt takes the dialogue and the provider renders the speaking (`lib/script_models.py:210-220`). TTS is narrator-only: `build_narration_audio_basis` refuses anything but `NARRATOR_VOICEOVER`, and `canonical_narration_text` keeps only narrator utterances (`lib/narration_delivery.py:328-361`). A character unit's TTS status is `NOT_APPLICABLE` (`lib/narration_delivery.py:425-440`).
- **The drama launch profile requires lip sync.** `fiction_drama_vi_v1` has `requires_lip_sync: true` with Wan 2.2 i2v. Preflight refuses it with `DRAMA_ROUTE_NOT_QUALIFIED` (`server/production_run/preflight.py`). Local i2v costs about 250 s per 2 s of video (catalog re-rank note).
- **Characters have no TTS voice.** They have `voice_style`, a text written by the LLM for video prompts, and an optional `reference_audio` for video-native voice (`lib/asset_types.py:87-96`, `lib/character_voice.py`). Audio backends expose voice catalogs: Gemini TTS has 30 named voices with style labels (`lib/audio_backends/gemini.py:32,117`), and OpenAI-compatible and DashScope backends have their own lists.

## Facts: donors

- **huohuo-drama @ f104b85** works the way this note proposes.
  - Each line is spoken by TTS in its speaker's voice and then muxed with FFmpeg. `workbench-server/src/services/drama/compose-dialogue.ts` parses `speaker: line` and skips ambience/SFX "speakers" and "no dialogue" placeholders.
  - The voice-assignment skill `agent-skills/drama_voice_assign/SKILL.md` picks one `voice_id` per speaking character from the current audio provider's catalog. It matches on sex, age band, temperament (lively → bright and slightly fast; calm → lower; gentle → soft; commanding → full) and prominence (leads get distinctive voices, extras get neutral ones). A character keeps the same voice across episodes, the leads' voices must be easy to tell apart, and a narrator voice is assigned the same way.
- **DramaClaw and ViMax** let the video model speak (Seedance 2.0 voice references, Veo native audio): video-native lip sync, not usable here (catalog inventory §dialogue drama).
- **DramaAgent (paper)**: per-line emotion and delivery on multi-speaker dialogue (sweep doc).

## Inference

- A stills drama whose character units get their lines from TTS needs neither generated video nor lip sync. This is the format of the many "AI drama story" channels: pictures of the scene, each character's line in its own voice, subtitles naming the line. A still face that does not move its lips is the accepted look of the format, and the narration format already shows stills while the narrator speaks.
- The change stays inside one boundary: who delivers a `CHARACTER_SPEECH` unit. Today that is the video model. With a still-clip video route, which cannot speak, it has to be TTS. Narrator units are unchanged.
- The voice choice belongs to the character asset (`tts_voice`, scoped to the audio route's provider and model). It is assigned once per character by the text route from the route's catalog (huohuo's criteria), then kept.

## Unknowns

- How well Gemini TTS and VieNeu keep a voice's identity across separate calls. Gemini voices are named presets, so they should be stable; VieNeu needs its voice list checked.
- Whether the reviewers' prompts need a drama variant. The current prompt says "narrated story film".

## Options

1. **Character units spoken by TTS per utterance, joined with short gaps** (huohuo). Chosen.
2. Gemini multi-speaker TTS: one call per unit with up to two speakers. Rejected because it caps at two speakers, couples the voices to one model, and does not apply to other routes.
3. Rewrite every line as narrator speech (narration mode already does this). This is the existing narration film, not a drama.

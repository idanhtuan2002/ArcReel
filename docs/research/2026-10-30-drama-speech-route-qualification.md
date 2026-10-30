# Drama speech route qualification — 2026-10-30

Status: **BLOCKED — fiction drama/storyboard is not a qualified automatic launch profile.**

This is a bounded, source and fixture review for the approved autonomous-production design. It does not submit a provider job, download a model, change a configured provider, or make a release claim. The narration profile is outside this decision.

## Scope and decision

The proposed route is per-character VieNeu speech through the existing speech-composition path, followed by `custom-3/wan2.2-ti2v-5b-gguf`. A qualified launch requires all of: multiple character voices with durable ownership, measured timing that constrains the generated visual unit, and lip synchronisation for an on-screen speaking character.

The current route clears only part of the first requirement. It has useful speech ownership and voice-provenance machinery, but the deployed Wan TI2V endpoint is explicitly silent and its retained graph has no audio input. VieNeu output can therefore be mixed *after* video generation, which preserves audio provenance but cannot establish mouth-to-audio synchronisation. The design's rule that a silent Wan clip plus overlay is insufficient remains binding.

## Pinned local evidence

All local source statements below were read at implementation checkout `947e805a6cef0b6687c70dfc167b01c180d07dcc`; the retained operational proof cites deployed release `0cef69a772f1d2946e452b918a8839b0f37fd2d9`.

| Requirement | Evidence | Result |
| --- | --- | --- |
| Character identity and ordered dialogue | `lib/speech_composition/__init__.py` derives `CHARACTER_SPEECH` only for nonblank speakers, keeps utterance order, and blocks mixed narrator/character units. `lib/speech_artifact_provenance.py` records effective speaker, style and optional reference-audio digest in the video basis. | **Partial.** Ownership and provenance exist; no test proves two individually synthesized VieNeu character outputs were admitted to a drama shot. |
| Voice selection or cloning | The configured local proof uses `custom-2/vieneu-tts-v3-turbo`; the prior measured note reports 20 built-in Vietnamese voices and a shim mapping ArcReel voice IDs to preset voices. `lib/character_voice.py` permits only prompt or reference-audio binding; prompt is the default soft constraint. | **Partial.** There is no run-pinned per-character VieNeu adapter, no voice-enrolment custody, and no fixture for more than one speaker. |
| Measured timing | `lib/speech_rate.py` computes an estimate from reading units. `lib/data_validator.py` merely warns when estimated dialogue/voice-over exceeds a scene budget. The retained three-scene proof validates source-WAV correlation and timeline starts, not per-dialogue visual timing or lip sync. | **Not qualified.** An estimate/warning and post-hoc narration timing are not measured character-speech timing used to drive video. |
| On-screen lip sync | `docs/r2/evidence/media-local-2026-10-30/wan-2.2/README.md` records **Generate Video with Audio off** and calls both retained TI2V outputs silent. Its frozen `saved-endpoint-definition.json` contains image, text, latent, video and save nodes only; no audio load/encoder or audio binding. The three-scene proof ran silent Wan clips and then placed narrator WAVs on a presentation. | **Fails.** No audio-conditioned video operation is available in the configured route. |
| Existing “lip sync” wording | `tests/unit/lib/reference_video/test_reference_video_script_preview.py` keeps dialogue utterances even for a silent episode so a capable provider *may* use them. `lib/prompt_utils.py` serializes dialogue as `speaker,line` for a video YAML. | **Not evidence of capability.** These are preparation/prompt data; the current Wan endpoint consumes neither an audio waveform nor a lip-sync control. |

The existing local media proof is real but is a deliberately limited narration smoke fixture: three 2.0417-second, silent Wan clips, three VieNeu WAVs and a 6.125-second FFmpeg assembly. Its own README excludes complex motion, multi-shot identity continuity and creative/human speech acceptance. It is therefore unsuitable as a drama qualification fixture.

## Primary upstream evidence and retrieval pins

VieNeu's own streaming API accepts a selected or enrolled voice per speech request and reports `output_samples`, `sample_rate` and `seconds` in its completion event. Its v3 Turbo implementation documents reference-audio enrolment as a speaker embedding plus reference codes, reusable across chunks. This makes it a plausible speech producer, subject to a run-owned voice/reference policy and measured output capture; it says nothing about visual lip synchronisation. The reviewed branch head is `04044e1b8f822f946bafb2c88b716459f4164152`; pin the review to its [streaming API](https://github.com/pnnbao97/VieNeu-TTS/blob/04044e1b8f822f946bafb2c88b716459f4164152/docs/streaming.md) and [v3 Turbo implementation](https://github.com/pnnbao97/VieNeu-TTS/blob/04044e1b8f822f946bafb2c88b716459f4164152/src/vieneu/_v3_turbo_engine/inference_v3_turbo.py).

The official Wan repository distinguishes TI2V from `s2v-14B`. Its `generate.py` routes TI2V with text and image but routes S2V with an image plus an audio path, and merges that audio into the S2V output. The upstream project describes S2V as audio-driven and ships inference code and weights. The reviewed branch head is `1ea34ff48f87168174e12956e200b1d908b1c5ff`; pin the implementation review to [that generator](https://github.com/Wan-Video/Wan2.2/blob/1ea34ff48f87168174e12956e200b1d908b1c5ff/generate.py), not `main`.

The currently configured TI2V workflow is already pinned to the official Comfy-Org `workflow_templates` commit `e7cd011d4ded3411c2f481200544f0be6fdc962e`, path `templates/video_wan2_2_5B_ti2v.json`, in `workflow-source.json`. It is the relevant exact proof of the shipped silent graph. No third-party workflow is used as authority in this report.

## Candidate comparison for this 8-GiB host

| Candidate | Primary-source interface and host evidence | Current decision |
| --- | --- | --- |
| **MuseTalk 1.5** | [Pinned source, `0a89dec45a0192b824e3cf4daf96c239440c5ed8`](https://github.com/TMElyralab/MuseTalk/tree/0a89dec45a0192b824e3cf4daf96c239440c5ed8) accepts an existing video or face image plus `audio_path`; its authors report a 4-GiB RTX 3050 Ti minimum test and about five minutes for eight seconds in FP16. It prepares each avatar and warns that face-region placement affects output. It also documents face-region resolution, identity-detail loss, and jitter limits. | **Best local candidate to investigate.** This is post-Wan audio-driven lip synchronization, so it can consume exact VieNeu output and an existing Wan visual shot without replacing the video generator. It is still uninstalled, unmeasured and unqualified on the RTX 2070. |
| **Wan2.2-S2V-14B** | [Pinned official generator, `1ea34ff48f87168174e12956e200b1d908b1c5ff`](https://github.com/Wan-Video/Wan2.2/blob/1ea34ff48f87168174e12956e200b1d908b1c5ff/generate.py) takes image and audio together. | **Architecturally direct but a poor near-term host fit.** It requires a different 14B S2V model and audio encoder; the existing 8-GiB TI2V proof is not resource evidence for it. Keep as a later candidate, not a default replacement. |
| **Wav2Lip** | [Pinned source, `bac9a81e63ecc153202353372e5724b83d9e6322`](https://github.com/Rudrabha/Wav2Lip/tree/bac9a81e63ecc153202353372e5724b83d9e6322) runs inference with a face image/video and an audio file, but its upstream requirements pin Python 3.6 and Torch 1.1. The README describes face-detection padding and resolution as material output controls but gives no authoritative 8-GiB inference budget. | **Not the preferred candidate.** It needs a separate legacy environment and face-detection/model inventory; no reliable host-time or VRAM figure is available from upstream. It can be reconsidered only if MuseTalk fails a fixture gate. |

### S2V details and why it is not the current answer

`Wan2.2-S2V-14B` can consume the actual per-shot VieNeu WAV plus an identity image, which creates the necessary technical path for audio-conditioned mouth movement. It is **not selected or qualified**:

- Current installed pin is QuantStack `Wan2.2-TI2V-5B-GGUF` revision `57437632ddd08bdcbd1508c866aa22e126ed51d2`, not S2V. The current endpoint has no S2V graph or audio encoder.
- The installed RTX 2070/8-GiB proof gives no admissible VRAM, latency or output-quality evidence for the 14B model, its audio encoder, or an S2V graph.
- No ArcReel adapter currently binds an exact VieNeu output, actor image/identity, S2V workflow digest, audio duration, generated duration, mouth-visibility condition and post-generation lip-sync score into one immutable receipt.
- Local provider price is currently zero for the existing route, but storage, compute envelope, adapter work and any future provider cost for S2V are **unknown**. This research does not authorize a download, provider change or paid fallback.

## Qualification gate before drama can be enabled

1. Establish a versioned, explicitly selected audio-driven replacement route. The first investigation should be post-Wan MuseTalk; S2V remains an alternate. Do not replace TI2V silently.
2. Pin its exact source, model and runtime inventory; demonstrate resource admission on the 8-GiB RTX 2070 before automatic dispatch. For MuseTalk, include the source-video/face preparation and face-region parameters in the receipt.
3. Add a run-scoped character-voice adapter: immutable speaker-to-preset/reference binding, reference-asset authority, VieNeu request/response receipt, actual sample count/sample rate/duration, and rejection for missing or duplicated actors.
4. Create fixtures with at least two Vietnamese character voices, a visible speaking face, reference identity across shots, and audio whose duration drives the generated shot. Test the complete adapter without treating prompt text as audio conditioning.
5. Measure video/audio alignment with an agreed objective probe plus independent visual review; establish threshold, failure cases, identity/continuity checks, and repair policy. A decoded MP4, matching WAV digest, or inferred speech-rate estimate does not satisfy this.
6. Record resource and cost limits for the selected replacement, then qualify it through the normal profile/Quality release process. Until then, preflight must return an explicit unsupported/blocking result for fiction drama and may not fall back to narration, silent TI2V, cloud, or a paid route.

## Facts, inference, and remaining unknowns

**Facts:** the current TI2V graph is silent; existing source protects dialogue ownership/provenance; VieNeu can select/enrol voices; upstream Wan provides an audio-driven S2V family.

**Inference:** MuseTalk is the best first local investigation because primary upstream evidence gives an audio-plus-face/video interface and a tested 4-GiB minimum, while retaining the existing WAN visual route. S2V is a more direct generator but has no admissible 8-GiB resource evidence. Post-production overlay alone cannot modify generated mouth motion.

**Unknown:** Vietnamese dialogue accuracy, multi-character shot routing, face-detection/occlusion behavior, identity continuity, MuseTalk or S2V feasibility on this host, actual duration following, objective alignment threshold, and quality/cost/reliability. No one of these may be inferred from the narration proof.

## Graph and coverage limits

Graph query used `r2-v2-main`, fast generation `2026-10-15T01:19:44Z`, which predates the active checkout. It positively located `SpeechComposition.prepare`; the one-hop trace had no recorded callers/callees but is not a negative claim. Coverage for `lib/speech_composition/__init__.py`, `lib/config/resolver.py`, `lib/video_backends` and `lib/audio_backends` had no source gaps except excluded `__pycache__`; the test scope itself is excluded/old, so exact current fixture/source was read directly. The conclusion relies on those direct reads and retained production evidence, not graph completeness.

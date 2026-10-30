# Three-scene local pipeline proof

Base evidence HEAD cb95fbb1babe613e70d1aa38299cc31b4d82f2f5. User approved 3 scenes, FLUX images, 2 s Wan clips, Vietnamese VieNeu narration and final MP4. Scope is operator-authored smoke fixture in existing dedicated local-media-proof-2026-1-f4bd3cf4 project; preserve existing character and real story project. No paid text/story model calls or release approval are implied.

Pending: persist validated fixture through ProjectManager (no validation/manifest guards disabled); run normal app storyboard/TTS/video jobs serially; export native draft; render final MP4 and decode/playback/inspect; retain evidence and limitations.

- Fixture persisted through deployed ProjectManager with default schema validation, formal write transaction, no-overwrite fingerprint and manifest reconciliation; existing character unchanged. Initial E1S1 storyboard job b654a515492741bda4a845db291675e6 was refused before provider execution because the formal script lacked an upstream source/plan and thus had no registered claim. No model error or inference occurred.
- Root cause confirmed in artifact_input_claims and TargetStatePlanner: registered episode source plus formal script_plan are required to derive the script basis. Uploaded authored episode_1.txt through app source API; saved content-only 3-segment plan through script-review/content API (E1S01..03); re-saved own fixture with canonical fingerprint through ProjectManager. Standard resolve_usable_episode_script_input now succeeds. No validation, manifest, review or release gate disabled. Script-review API reports confirmed with null confirmed_at under its existing-script compatibility behavior; no Human confirmation/release is claimed.
- UI saved project model_settings Wan resolution 480p and default_duration 2; global model choices unchanged. Serial app job runner submits storyboard → TTS → video through production REST routes, preserving task IDs for resume and stopping on failure.

- All three normal app storyboard jobs succeeded (custom-3). Visually inspected office desk, hands/laptop, and office worker at window; all retain warm morning visual direction. All three normal TTS jobs succeeded (custom-2); measured durations 1.44 / 1.52 / 1.12 s, 48 kHz mono PCM, peak below -5.6 dBFS and zero clipped samples.
- First Wan video job running through normal app generate/video, submitted native dimensions 576 x 1024, length 49. Native endpoint tests are not being substituted for production jobs.
- Native narration export is a presentation/draft bundle (separate video/audio/subtitle timeline), not a renderer; final MP4 will be rendered with FFmpeg from the app-selected timeline and retained alongside the native editable export. No app code change or claim of native one-click MP4 export.

- E1S01 video succeeded through production worker: app task b514a7c9dd3e42f389059fbe4473f32c, ComfyUI b530816a-4d80-44e3-8dd0-62e8993387fa. use_tts presentation API and native bundle export succeeded: provenance verified, current video/audio, 2.041667 s video, 1.44 s narration, 0..1.44 s mechanically timed subtitle, native video audio disabled. Bundle retains native MP4/WAV/presentation JSON/VTT; final assembly consumes these exact selections.

## Complete

- All 9 app production jobs succeeded. Final E1S03 video: task 2f2f2f80e64c47da9b4715a09cd26587, native job 82fa4045-4b92-4055-b9bb-fd0045086a2f. App episode UI Done 3/3.
- Native use_tts bundles verified for all three units; raw selected media hashes checked. Native editable episode ZIP exported through normal token + jianying-draft route: 3 video / 3 audio / 3 text segments, 6125001 us. No token retained in evidence.
- Final FFmpeg MP4: 576 x 1024, H.264/AAC, 24 fps, 147 frames, 6.125 s, captions from native subtitles. Full decode, frame order/lineage, narration waveform correlation >0.9999 and browser playback with decoded audio/video all pass. See final-verification.json and screenshots.
- Global defaults preserved, existing character retained; app health OK, ComfyUI queue empty. No app code/schema/dependency changes or Human release claim. Final README documents scope and recovery.

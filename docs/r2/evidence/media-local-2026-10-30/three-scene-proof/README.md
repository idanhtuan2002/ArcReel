# Three-scene local pipeline proof — 2026-10-30

Completed an operator-authored narration episode in the dedicated `local-media-proof-2026-1-f4bd3cf4` project. UI: http://127.0.0.1:1251/app/projects/local-media-proof-2026-1-f4bd3cf4/episodes/1 . Episode 1 **Buổi sáng bắt đầu** shows Done 3/3.

Evidence base HEAD `cb95fbb1babe613e70d1aa38299cc31b4d82f2f5`; deployed checkout `0cef69a772f1d2946e452b918a8839b0f37fd2d9`. No application source/schema/package changes, service restart, paid text-model call or release approval was needed. Existing character and unrelated real story project were preserved.

## Deliverables

- `Buoi-sang-bat-dau.mp4`: 576 x 1024 portrait, 24 fps, 147 frames, **6.125 seconds**, H.264 video / stereo AAC audio, Vietnamese narration and burnt-in captions. SHA256 and precise lineage checks: final-verification.json. This evidence copy matches the D export.
- D export folder: `/mnt/arcreel/D/ArcReel/media/exports/buoi-sang-bat-dau-20261030/`. It contains the final MP4, SRT, three native presentation ZIPs and extracted exact selected media/presentation JSONs.
- `Buoi-sang-bat-dau-editable-draft.zip` in that D folder is the actual native ArcReel Jianying v6 export with `narration_delivery=use_tts`: 3 video segments, 3 audio segments, 3 subtitle segments, duration 6125001 microseconds. API export status, archive inventory and hash: native-export-verification.json. `draft_path` embeds `<D export folder>/editable-draft`; extract the outer project directory there to match its absolute asset paths. Import into an external editor was not tested.

## What ran

1. Authored a short three-segment script and source: “Nắng mai khẽ lên.” / “Một ngày mới đến.” / “Bắt đầu thôi.” The shots depict a sunlit desk, hands at a laptop, and an office worker facing the skyline. No story-generation LLM was used.
2. Saved the fixture through the deployed ProjectManager with schema validation and canonical fingerprint checks. Initial failed storyboard task was refused before inference: the source/plan chain was absent and therefore the script had no registered artifact claim. Uploaded `episode_1.txt` through the source REST route, saved the content-only plan through `script-review/content`, then re-saved the fixture through the normal formal-write/manifest transaction. Formal script input resolution passed. No guard was disabled. Details and failed receipt retained in progress.md / initial-admission-refusal.json.
3. Ran **9 normal production queue jobs**, serially, through `generate/storyboard`, `generate/tts`, and `generate/video`: 3 FLUX images and 3 Wan clips on custom-3, 3 VieNeu WAVs on custom-2. All succeeded. Worker time for videos: 301.226 / 265.512 / 265.526 s; images: 50.204 / 30.082 / 25.074 s. Task IDs, provider IDs and results: task-ledger.json / task-summary.json. Video settings: 480p, 9:16, 2 s; generated 576 x 1024, 49 frames each.
4. Materialized native `use_tts` presentations and downloaded native bundles. All report verified provenance, current video/audio selection and currency, narrator_voiceover, native video audio off, narration gain 1. Checked raw media SHA256 against each native presentation before rendering.
5. Rendered the watchable MP4 with FFmpeg using those exact video/audio selections and subtitle timestamps. The native application exports editable timelines/bundles; the final MP4 is this operator FFmpeg assembly, not a newly implemented native one-click MP4 exporter. Exact command: render-command.json. Original media unchanged.

## Verification and limits

- Full ffprobe/ffmpeg decode passed. Three source videos have 49 frames and all 48 adjacent frame pairs change; final has 147 frames in the correct order. Final scene-start frame differences from source are below 0.28 gray levels after excluding the caption area. Each narration correlation with the original selected WAV exceeds 0.9999 at the expected timeline start; no speech is truncated. All source WAVs have non-zero RMS, peaks below -5.6 dBFS and zero clipped samples.
- Visually inspected all storyboard images, representative source video frames and the final three-scene contact sheet. Warm visual direction, object/subject retention, subtle motion and readable Vietnamese captions observed. Pronunciation/creative quality has not received independent Human acceptance; audio waveform/lineage checks are not a substitute for that.
- Browser playback of the app's TTS overlay succeeded: both media elements advance and decode; native video stays muted and selected narration is audible-enabled. Final MP4 browser playback also succeeded: readyState 4, advancing clock, decoded video frames and nonzero decoded audio bytes, unmuted, no media error. Results/screenshots retained.
- Project UI reports Done 3/3. Final health OK and ComfyUI queue empty. Selected global defaults exactly match the prior Wan checkpoint; only this proof project's model resolution/default duration were saved. Root 32.77 GiB free, D 149.84 GiB free at final check.
- This proves the media pipeline for an operator-authored small script. Automated source-to-story planning, LLM prompt authoring, independent Human script/release approvals, editor import, long-form generation, complex motion/consistent face across shots and higher resolutions remain outside this proof. Script review returned confirmed under its existing-script compatibility path with no Human confirmation timestamp; no Human approval is claimed.

## Resume / preservation

Completed production script and selected versioned asset bindings: completed-script.json. Do not regenerate these jobs to inspect the result. Use the retained exports first. The original pre-fixture project/manifest snapshots are private at `/mnt/arcreel/D/ArcReel/operations/three-scene-proof-20261030/`; restoring them would remove the new episode from the project index, so do so only deliberately after archiving the episode. No rollback was performed.

Graph discovery used older `r2-v2-main` generation 2026-10-15T01:19:44Z with best-effort coverage checks; material configuration/flow claims were verified against deployed source and actual API/job/media outputs. Full application suites were not run for this operational, data-only task.

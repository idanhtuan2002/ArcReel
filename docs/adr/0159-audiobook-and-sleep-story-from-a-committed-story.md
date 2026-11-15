---
status: accepted
---

# Audiobook and sleep story from a committed story

Decided 2026-11-15 on the sponsor's catalog (`docs/r2/R2_CONTENT_FORMS_CATALOG.md` rank 2: audiobook, sleep stories; vision profile "Audiobook", `docs/research/r2-origin/00_PRODUCT_VISION.md` §7). No donor ships an audiobook pipeline; every part already exists here (exported manuscript, narration TTS route, ACE-Step bed, ffmpeg).

1. A committed story's exported manuscript (`# title`, `## chapter`, `* * *`) is spoken chapter by chapter with the project's narration route and voice (`resolve_audio_backend`, `resolve_narration_voice`); delivery cues follow the route (`synthesis_text`). The blurb is not read.
2. Paragraphs are cut into sentence-bounded segments of at most 400 characters; each segment is cached by the digest of its text and voice, so a re-run (a failure, a restart) speaks only what is missing.
3. Presets: `standard` (pauses 0.35/0.7/1.4/2.5 s, bed −26 dB, −18 LUFS) and `sleep` (pauses 0.6/1.2/2.2/4 s, tempo 0.92, soft bed −24 dB, −23 LUFS, 20 s fade-out). The bed is an ACE-Step cue looped under the voice; without the music server the book is voice only.
4. Files under `output/audiobook/<run>-<preset>/`: M4B with chapter marks, MP3, MP4 (first storyboard as the cover, when the project has one) and chapter timestamps for a video description. API: `POST/GET /projects/{p}/story-runs/{run}/audiobook`, file download by kind; UI: two buttons, progress and downloads on the approved story.
5. Jobs run in the app process; a restart loses the job's state but not its segments, and starting again resumes.

Smoke (2026-11-15, VieNeu v3 turbo through the shim): 2 chapters, 5 segments, 35.5 s of audio rendered in 19.2 s; M4B chapter marks at 0.0 and 23.54 s.

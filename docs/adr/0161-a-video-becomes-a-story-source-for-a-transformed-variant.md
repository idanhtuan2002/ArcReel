---
status: accepted
---

# A video becomes a story source for a transformed variant

Decided 2026-11-15 on the sponsor's catalog (rank 6: remakes, recaps and summaries of other people's videos turned into a variant; "đồng ý thêm yt-dlp").

YouTube monetizes reused content only when "viewers can tell that there's a meaningful difference" and names as allowed "Edited footage from other creators where you add a storyline and commentary" and "A scene from a movie where you've rewritten the dialog and changed the voiceover"; it refuses "readings of other materials you did not originally create" ([monetization policies](https://support.google.com/youtube/answer/1311392), read 2026-11-15). So the source video gives only its story material; the app writes and films a new work from it.

1. **Ingest** (`lib/video_ingest.py`): `yt-dlp` (dependency added with the sponsor's consent) downloads the best audio stream of one video (no playlist, at most 3 h); ffmpeg cuts mono 16 kHz 64 kbit/s MP3 chunks of 20 min (under Groq's 25 MB upload limit); an OpenAI-compatible Whisper model transcribes each chunk (`verbose_json`), stitched on one timeline; segments join into paragraphs at pauses ≥ 1.6 s.
2. **Route**: the first enabled custom-provider model whose id names `whisper`, `large-v3` before `turbo` (on this host Groq `whisper-large-v3`, free 1,000 requests/day).
3. **Output**: `source/<slug>.txt` (title + paragraphs), the project's story source, and `source_origins/<slug>.json` (URL, title, uploader, duration, language, "transformed variant only"), never narrated.
4. **The variant**: the existing paths make the new work — a production run "from the project's story" or "variant of a story" with a variant profile (ADR-0115), then the film with the app's own storyboards and voice. No footage of the source is used.
5. API `POST/GET /projects/{p}/video-sources`; UI: "Import from a video (URL)" on the source page with the job's step.

Not covered: recaps that cut the source's own footage with commentary (a later form), downloading video streams.

Smoke (2026-11-15): route picked Groq `whisper-large-v3`; a local Vietnamese clip transcribed to one paragraph, language "Vietnamese". No URL download was run in the smoke.

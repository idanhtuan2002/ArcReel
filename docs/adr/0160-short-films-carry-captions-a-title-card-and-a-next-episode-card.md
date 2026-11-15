---
status: accepted
---

# Short films carry captions, a title card and a next-episode card

Decided 2026-11-15 on the sponsor's catalog (rank 3: micro-drama series polish; TikTok/YouTube Shorts forms first).

The render wrote the narration as a sidecar `.srt` only; the picture carried no text. Short-video viewers mostly watch muted and decide in the first seconds whether to stay, and a series keeps them by the next episode's question. Episode adaptation (ADR-0114) already writes a hook line and a cliffhanger.

1. **Captions burned in**: each cue becomes screens of at most two lines of at most 32 characters, timed in proportion to their length inside the cue, bold white with an outline in the lower safe area (`lib/screen_text.py`, libass via the ffmpeg `ass` filter, Noto Sans for Vietnamese/Chinese glyphs). The sidecar `.srt` stays.
2. **Title card** "Tập N · <episode title>" (localized "Episode N", "第N集") at the top for the first 1.8 s.
3. **Next-episode card** "Tập sau: <cliffhanger>" over the last 2.8 s when a later episode exists; captions stop where it starts.
4. One video re-encode (CRF 18) right after the units are joined; the sound is copied. A failed text pass leaves the film without text and the manifest records `{"skipped": code}`; the manifest records the cards and the script digest (`screen_text`).
5. The adaptation's hook line must be spoken in under 4 s (was 6 s; 3.75 words/s ≈ 15 words).

Checked by eye on a rendered 9:16 frame: Vietnamese diacritics render, captions sit above the lower edge, cards at top and centre.

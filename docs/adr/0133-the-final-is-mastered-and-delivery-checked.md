---
status: accepted
---

# The final is mastered to a loudness target and checked for delivery faults

Decided 2026-11-13 by the main agent under the sponsor's instruction to do every step that needs no new account first. Research: [video-quality donor mechanisms](../research/2026-11-13-video-quality-donor-mechanisms.md) (openfilm loudness recipe, open-edit delivery review), [roadmap synthesis](../research/2026-11-13-r2-quality-roadmap-synthesis.md) gap I6.

Before this decision the native renderer mixed narration and clip audio at their recorded gains and only checked that narration was audible; the final's loudness was whatever the TTS produced. Quality probes measured LUFS but nothing acted on it, and no check looked at dead air or subtitle timing.

1. **Mastering in the renderer.** `RenderContract` carries `loudness_lufs` (default −14 LUFS integrated, the level YouTube and short-video platforms normalize to), `true_peak_db` (−1 dBTP) and `loudness_range` (20 LU, wide so the linear mode is kept). After concatenation the renderer measures the final with `loudnorm` and, unless it is silent (≤ −70 LUFS), re-encodes the audio once with `loudnorm linear=true` and the measured values; the picture is stream-copied. Measured input and output loudness and true peak go into the render manifest under `loudness`. Verification (streams, duration, audible narration) runs on the mastered file. `loudness_lufs=None` keeps the mix as made. This follows openfilm's measure → one gain → limit → re-measure order; ffmpeg's linear `loudnorm` applies the single gain with its own true-peak limiter.
2. **Delivery checks as MINOR findings.** Every review (local frame reviewer and Gemini watch reviewer) now adds: `CHECK_LOUDNESS_OFF_TARGET` (more than 2 LU from −14 LUFS or true peak above −0.5 dBTP), `CHECK_DEAD_AIR` (silence below −50 dB for 3 s or more), `CHECK_SUBTITLE_TOO_FAST` (over 20 characters per second), `CHECK_SUBTITLE_TOO_SHORT` (under 5/6 s) and `CHECK_SUBTITLE_TOO_LONG` (over 7 s). Thresholds are the Netflix Timed Text Style Guide general requirements and its adult reading speed; Netflix's Vietnamese figure could not be retrieved (the article served the English page), so 20 cps is provisional.
3. **Why MINOR.** MINOR findings never send a run back (`REPAIRABLE` needs CRITICAL or MAJOR), so recorded reviewer qualifications keep their meaning and existing corpora are not re-judged. The findings are visible on every run; raising any of them to MAJOR is a later decision taken with measured false-positive rates on real cloud-made finals.

Not decided here: a music/ambience bed with ducking (needs a music source: a generator account or a library) and per-line TTS delivery cues (needs a TTS backend that accepts them). Both follow after the cloud trial.

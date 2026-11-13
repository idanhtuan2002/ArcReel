---
status: accepted
---

# The script prompt teaches shot grammar

Decided 2026-11-13 by the main agent (craft program P0-7). This reverses the design note in `lib/prompt_builders_script.py` that gave no criteria for choosing shot size or camera move ("不强加倾向", "按画面内容自行选择").

With no criteria the visual layer chose sizes and moves freely: no rule opened a scene wide, kept a close-up for emotional peaks or varied neighbouring sizes, and nothing kept moves within what video models execute well. Shot size and framing are the cinematography dimensions models follow and judge best (ShotBench, arXiv 2506.21356: shot size 75 %, framing 85 %, camera movement near chance), and generators do worst on intense rotation (CineTechBench, arXiv 2505.15145).

1. **Shot size grammar** (AIVPE `src/utils/directorAgent.ts` coverage rule and review): a scene's first shot (scene change or time jump) is a long or extreme long shot; objects, hands, details and clues get close-up inserts; emotional peaks, key lines and reactions get close-ups; medium shots carry the rest; the same size is not held for more than two shots in a row. In a vertical frame faces sit in the upper middle and the bottom quarter stays free for subtitles.
2. **Camera angle.** `composition.camera_angle` (`Eye Level`, `Low Angle`, `High Angle`, `Overhead`, `Dutch Angle`; default eye level, drift normalized like `shot_type`) with the conventional meanings, the non-eye-level angles used sparingly. It is rendered into the storyboard prompt only when the shot carries it, so existing storyboards keep their visual basis.
3. **Camera moves.** One slow move per shot; static, push in, pull out, pan and tilt are the reliable ones; orbit and shake are avoided.
4. **A deterministic check.** `lib/shot_grammar.shot_grammar_issues` reports a scene not opening wide, more than two same-size shots in a row, an episode of four or more shots without a close-up, and unreliable moves. Narration prompt authoring logs the findings; they never block a script.

The interactive agent uses the same builders, so it gets the same guidance. The storyboard editor keeps a stored `camera_angle` when a shot is edited (it spreads the stored prompt) but does not show it yet.

---
status: accepted
---

# The render moves held pictures and grades the film

Decided 2026-11-13 by the main agent on the sponsor's instruction to build every ranked addition of `docs/research/2026-11-13-r2-film-craft-quality.md` (P0-1, P0-2), reusing donor work where it exists.

The narration launch profile's video route holds each storyboard still for the whole unit (`still-clip-local`), so the film plays as a slideshow, and independently generated stills drift in colour with nothing unifying them.

1. **A held picture gets a slow camera move.** The renderer checks each unit's window with `freezedetect`; when the picture never changes, it moves a window over a 3× supersampled frame with `zoompan` (sub-pixel steps, no jitter) for the unit's frames. The move follows the shot's planned `camera_motion`: push in or pull out by 10 %, pan or tilt across the 10 % room of a held zoom, a 4 % push for a planned static shot, and a diagonal drift for moves a still cannot carry (orbit, tracking). A clip that already moves keeps its own motion. The move vocabulary and magnitudes follow VGA's still-image camera motions (`remotion-composer/src/components/AnimeScene.tsx@e46e9d3`), rebuilt as an ffmpeg filter because our renderer is ffmpeg. Benchmarks show slow single moves are the ones generators and viewers read reliably (ShotBench, CineTechBench).
2. **The film has one colour grade.** The project overview (LLM, structured output) chooses `color_grade` from a closed set: `neutral`, `cinematic_warm`, `cinematic_cool`, `moody_dark`, `bright_clean`, `vintage_film`, `high_contrast`, each described by the story it suits. Every unit gets that grade, blended at 0.7 with the ungraded picture. A project without a choice gets `neutral`. The profiles are VGA's `tools/enhancement/color_grade.py@e46e9d3` presets; its `vintage_film` used `colorbalance` options ffmpeg does not have (`ms`, `mh`) and is corrected to midtone shifts.
3. The render manifest records each unit's move (or none) and the grade; an unknown move or grade is refused (`UNKNOWN_MOTION`, `UNKNOWN_GRADE`).

Not covered: a per-scene look record and its grade offset (P0-3), and a numeric check of colour consistency between shots (P1-9).

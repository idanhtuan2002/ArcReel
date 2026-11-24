# Film 2 (remake test) — publishing blockers and gaps against the source video

Date: 2026-11-24. Film `/mnt/arcreel/D/ArcReel/assembly/films/01M863VMJQECF8PC9Z6FVNT6AV-ep01.mp4` (51.5 s, 18 beats)
against the sponsor's source Short "Ollie queria ver embaixo d'água" (71 s, wordless 3D animation).
Evidence: frame sheets every 2.5 s of both, the 18 sketches and first frames, beat data from the DramaClaw API,
a faster-whisper large-v3 transcript of the film. Labels: **FACT**, **INFER**, **UNKNOWN**.

## 1. Blockers for publishing

| # | Defect | Evidence | Origin |
|---|---|---|---|
| 1 | Sketch marks leak into the picture: white studio backgrounds, black arrows, panel borders, a magenta mannequin hand (beat 4), two panels side by side in one frame | first frames of about two thirds of the beats; sketch/frame pairs of beats 3, 4, 8, 13 (FACT) | DramaClaw sketches draw every character as a **human-shaped colour-coded mannequin on pure white** (`generators/prompt_builder.py` @ 1277795 lines 3154–3255); the render step must replace it. With an animal hero the replacement keeps the human posture and the white page (INFER); the sketch model also drew arrows the prompt forbids (FACT: line 3203) |
| 2 | Squirrel posed like a person (standing upright, hands on hips) | beats 1–3, 13–15 | same mannequin pose (INFER) |
| 3 | Props change from beat to beat: nut shell, bark hat, wooden stack, honey leaf | first frames | props are not registered as global props, so they have no marker or reference image (INFER, `detected_props` unused) |
| 4 | Video artefacts: purple/magenta colour bands (≈17 s), smears, the last beat fades to near black | frame sheet 17.5 s, 50 s | Wan 2.2 5B at 480×848 upscaled to 720×1280 (FACT: workflow); the last clip diverged (INFER) |
| 5 | No music, no sound effects; narration only | audio stream; project `bgm: null` | DramaClaw compose mixes voice only; no music step configured (FACT) |
| 6 | No captions | frames | DramaClaw has no burned-in subtitle step in our run (INFER); TikTok/Shorts need them |
| 7 | Narration may be mispronounced in places ("vùng vẫy", "bướng bỉnh", "rỗng", "cúi", "sâu", "trượt tuột") | Whisper heard "vùng váy", "bướng bình", "giống", "cuối", "sầu", "chưa tuột"; the beat text is correct | VieNeu voice or Whisper — **UNKNOWN until listened to** |
| 8 | Copyright: the plot is the Netflix Short's | source | test only; a publishable remake must change the story enough (ADR-0161 "transformed variant only") |

## 2. Gaps against the source

| Aspect | Source | Film 2 | Gap |
|---|---|---|---|
| Style | stylised 3D animation, one golden-hour lakeside, shallow depth of field | "realistic" (sponsor's CP1 choice), backgrounds jump between white page, studio and lake | one location/look per film; style reference image from the source |
| Telling | wordless; expressions, gags and music carry it | 18 continuous lines describing what is on screen | narration repeats the picture; for wordless sources prefer music + SFX + few lines (or none) |
| Pacing | 71 s, long holds, comedic timing (close-up face through the helmet, repeated failures) | 51 s, 18 cuts of ~2.8 s, each cut as long as its line | shot length follows the voice line (audio 2.3–3.4 s vs script estimate 11–16 s); no holds or reaction shots |
| Key moments | helmet POV close-up, failed tries, underwater reveal with joy | close-up missing; failure is one beat; ending dark | story-from-frames (24 frames) loses the signature shots; more frames or the source's shot list are needed |
| Story accuracy | the creature applies something green to the helmet | "honey as bait" | the vision model guessed (INFER) |
| Character | one expressive creature, same helmet throughout | squirrel identity holds; helmet does not | props as global references |

## 3. What to improve, in order (INFER; each needs research against donors before building)

1. **Animal / non-human characters in DramaClaw's sketch → frame path** — find whether DramaClaw supports them
   (creature identities, `species`, scene-only sketches) or whether the frame step can skip the sketch; else carry
   "animal, no clothes, natural background" into the render prompt. Blocks every animal film.
2. **Register the story's key props as global props** (helmet, snorkel) so they get markers and reference images.
3. **Music and sound effects**: a donor step for BGM/SFX (old app's ACE-Step/MMAudio are on drive D; OpenMontage has
   music and SFX stages) — compare before wiring.
4. **Captions**: OpenMontage/Remotion word captions on the composed film.
5. **Pacing for wordless sources**: shot length from the source's shots, not from the voice line; fewer, shorter
   lines.
6. **Video quality**: Wan 14B or paid video (D20) — the free 5B model sets the ceiling.
7. **Listen check** of the narration for the words Whisper flagged.

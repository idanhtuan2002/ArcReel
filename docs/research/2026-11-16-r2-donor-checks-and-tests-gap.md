# Donor checks and tests against ours, stage by stage (2026-11-16)

- **Why:** trial 7 episode 2 was adapted by the agent with Ông Ba's line given to Chú Tư (registered, absent from the
  episode) and an invented closing question, and the adaptation passed every check. The sponsor asked for every check
  and evaluation the donors have at each workflow stage, and their tests, against ours.
- **Baseline:** `impl/r2-film-quality` after `b380f168b` (adaptation fidelity checks, tag `r2-v2.5.56`).
- **Donor pins (read only, nothing run):** DramaClaw (DC) `b299bfd`, huohuo-drama (HUO) `f104b85`, ViMax `63bb9c7`,
  OpenMontage (OM) `08e2151`, take `47c1721`. Paths: DC `src/novelvideo/`, HUO `workbench-server/src/`.
- **Method:** a read-only inventory of donor checks by stage (one background agent, cited file:line, wired vs
  unwired), then the main agent read our code for each item and the donors' own tests (DC 750 test files, OM ~45
  project tests outside `.venv`, ViMax 20, take 11, HUO none).
- **Labels:** [F] fact with a citation; [I] inference; [U] unknown.

## 1. Stage matrix

"Wired" = called from the donor's main flow. Most DC verification and every OM agent-run checker is reached through an
API, a CLI or an agent skill, not automatically.

| Stage | Ours [F] | Best donor check [F] | Gap |
|---|---|---|---|
| Asset analysis | name attestation in `lib/asset_extraction.py` (`text_attestation.named_in`) | DC evidence quote must be verbatim in the chunk, unattested names dropped (`structured_extraction.py:284-300,489-512`) | none material |
| Episode plan | anchors exist/unique/contiguous, per-episode size bounds ×3 / ÷4 of target, CJK refused in a Latin source (`lib/episode_planner.py:705-760`, since 2026-10-23) | DC `EpisodePlanReviewer` gaps/overlaps/coverage — **unwired** | none; trial 7's plan predates the size and CJK rules |
| Adaptation | **now:** speaker named in the episode, quoted line keeps the source's speaker, narration dialogue attested, long invented narration refused (`lib/adaptation_fidelity.py`); before: excerpt order, hook, length, cast, CJK | DC literal mode: one beat per source line, the model only labels, speaker from the line (`literal_script_writing.py:296-348,668`) | closed by `b380f168b`; no donor detects invented lines — DC prevents them by construction |
| Script plan / script | narration `novel_text` must cover the adaptation verbatim (`server/text_generation.py:1315,1507`); pydantic structure | OM shot-variety runs ≥ 3, static share, lighting setups (`lib/variation_checker.py`, agent-run); DC render preflight: every beat has an explicit identity state (`render_identity_guard.py:20-37`, wired) | **G2, G3** below |
| Storyboard | decode/orientation/size/blank (`unit_checks.py`), continuity judge 11 checks incl. readable text and cast (ADR-0134), best-of-N judge off until qualified | DC colour prefilter before any VLM, failure-mode registry (text overlays) with yes/no gates, relaxed selection — API/CLI only | small; ours is wired, theirs is not |
| Video | `clip_problem` decode/orientation | OM delivery-promise motion ratio | n/a (still clips by design) |
| Audio / TTS | `narration_problem`: decodes, long enough, audible, no long silence | **OM transcript-vs-script word accuracy ≥ 0.9 and TTS punctuation-leak detection** (`tools/video/video_compose.py:2196-2272`) | **G1** below |
| Render | presentation currency, render manifest; final subtitle ≈ narration similarity, black frames, fill, loudness/true peak, dead air, reading speed, length (`final_checks.py`) | OM `_run_final_review` ffprobe/duration drift/silence/clipping (wired) | none; ours measures subtitle coverage, OM's `coverage_ratio` is a constant 1.0 |
| Quality | two blind reviewers, frame questions, qualification | DC contact-sheet VLM (API), OM host-LLM reviewer | none |
| Package | JPEG thumbnail, archive digests | none in any donor | **fixed here:** metadata texts not in the film's language are left out (trial 7 episode 1's Chinese title) |

## 2. Gaps, ranked by waste avoided per effort

- **G1 — TTS fidelity by ASR (high).** [F] Our audio checks are signal-only; a misread word, a skipped clause or a
  read-aloud symbol passes until a reviewer hears the final, and then the whole episode goes back. [F] OM compares a
  transcript of the rendered narration with the script (word accuracy ≥ 0.9) and flags punctuation spoken by the TTS.
  [I] Per line, right after TTS, is where it saves the most (regenerate one line, not re-render the episode).
  [U] Vietnamese ASR quality and cost on our hosts: Groq `whisper-large-v3-turbo` (free, 1,000 req/day, audio leaves the
  host) or a local whisper on the 8 GB GPU shared with ComfyUI/VieNeu. Needs research-first + ADR: engine, threshold
  measured on our own TTS lines (VieNeu tone marks), what counts as a word, and the retry bound (ADR-0112 style).
- **G2 — Cast pre-check before storyboards (medium).** [F] `characters_in_segment` is set at script-plan time and only
  required to be present (`lib/data_validator.py:874`); a registered character named in the segment's narration but
  missing from the list is discovered after the image, by the continuity judge's cast check. [F] DC blocks a render
  until each beat has an explicit identity state (detected identity or a no-character marker). [I] A deterministic
  check "registered names attested in `novel_text` ⊆ `characters_in_segment`, else an explicit reason" at script-plan
  commit catches it before GPU time; mentioned-but-absent characters (memories, letters) need the explicit marker, so
  it is a contract change → ADR.
- **G3 — Shot variety (low–medium).** [F] OM flags three or more consecutive shots of one size and > 60 % static.
  [F] Our segments carry `image_prompt.composition.shot_type`. [I] A MINOR quality finding (recorded, not blocking) is
  cheap; making it block needs a writer retry, so measure first. OM's tests
  (`tests/lib/test_variation_checker_runs.py`) can be reused as the cases.
- **Not adopted:** DC colour-marker prefilter (needs colour-coded sketches we do not make); OM delivery promise (we
  promise still clips); ViMax portrait guard (we already check orientation per unit); DC/OM "unsure = pass" judges
  (ours already never block on a judge failure).

## 3. Donor tests reused

- [F] OM `tests/tools/test_subtitle_timestamps.py` (millisecond carry across second/minute/hour, well-formed sweep) is
  now `tests/unit/lib/test_subtitle_timestamps.py` against `presentation_renderer._timestamp` and
  `speech_presentation._vtt_timestamp`. Ours already passed: both use integer milliseconds with `divmod`.
- [F] DC `test_literal_script_writing_audio_type.py` cases (dialogue needs a speaker, non-character voices become
  narration, camera prefixes are not speakers) are already covered by our adaptation checks (`settle_speakers`, the
  cast and the new speaker checks); `tests/unit/lib/test_adaptation_fidelity.py` uses the real trial 7 source.
- [F] DC `test_identity_planner_appearance_validation.py` (reasoning leak and corrupted appearance text rejected,
  retry twice then accept) — [I] relevant now that the agent runs on OpenRouter models whose thinking leaked into
  text in the 2026-11-16 session; no field-level leak check exists in our text stages ([F] grep for leak guards found
  none besides Ollama `think: false`). Candidate G4, measured on real outputs before any rule.

## 4. Unknowns

- [U] Whether DC reaches `run_sketch_select` automatically (its agent skills live outside `src/`).
- [U] Vietnamese ASR word accuracy on VieNeu output; no measurement yet.

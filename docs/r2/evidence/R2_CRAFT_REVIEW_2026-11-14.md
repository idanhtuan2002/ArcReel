# R2 craft and identity program: independent release review (2026-11-14)

- Range: `r2-v2.5.17..a623140e3` (branch `impl/r2-film-quality`, 26 commits, ADR-0140 to ADR-0152). This is the candidate r2-v2.5.18.
- Reviewer: an independent subagent. It read the diffs and code, ran tests and a throwaway probe, and changed no code.
- Tests run at HEAD `a623140e3` with `uv run python -m pytest -n 4` on 20 related files: **337 passed, 22 skipped**. The files were the presentation renderer (real ffmpeg), render finish inputs, music bed, scene ambience, face identity, narration cue, prompt builders and prompt utils, scene looks, shot grammar, look consistency, composition, continuity references, preflight, media adapter, workflow state, assets tool, asset extraction, incremental script generator and prompt preview.
- Probe: a throwaway test, written next to `tests/integration/server/services/test_formal_image_finalization.py` and deleted after the run. It generates storyboard E1S02 (Alice + 祠堂 + 玉佩, previous storyboard E1S01) and compares the basis that execution registers with `resolve_current_artifact_basis` from the planner. **The two digests differ** (`2dc71f4c…` vs `df…cd09d`).

## Findings

### H1 HIGH: newly generated storyboards are registered STALE (execution and planner put references in different orders)

- Execution, `server/services/generation_tasks.py:566-629` (`_collect_reference_images`), now orders the references as: character sheets, then the previous storyboard (`:596`), then scene and prop sheets (`:607`), then extras. The visual basis is built from `_visual_references` in this order (`:1743`).
- The currency planner, `lib/artifact_planner.py:566-636` (`_plan_storyboards`) together with `_storyboard_references` (`:692-707`), still builds the expected basis in the old order: products, characters, scenes, props, then the previous storyboard (`:615`). `_reference_evidence` keeps the list order, so the two digests differ.
- `ArtifactManifest.compare_entry` (`lib/artifact_manifest.py:~516`) reports STALE when the registered digest differs from the planner's. The probe above confirms the mismatch.
- **Scenario:** every storyboard has a previous storyboard of the same scene (any shot after the first in a scene) plus at least one scene or prop sheet. In narration this is most shots. Such a storyboard is STALE the moment it is generated, and it is STALE again after every regeneration.
  - The UI shows the shot as stale permanently.
  - `MediaAdapter._episode_media_current` (`server/production_run/media_adapter.py:798-813`) returns False whenever `stale_ids` is not empty.
  - When the plan's next action is `PLAN_EPISODES` (target episode finished, source text remaining), this falls into `_UPSTREAM` and raises `OwnerBlocked("EXTERNAL_INPUT_CHANGED")` (`:211-212`). **This path was traced in code, not run end to end.** When the next action is `EXPORT`, the run still passes.
- ADR-0149 §1 says the order change makes existing storyboards regenerate once. In fact the planner did not change: existing storyboards stay current, and only new ones go stale, every time.
- **Fix:** put the same priority order in `artifact_planner._plan_storyboards`: products, characters, previous storyboard, scenes, props. Add a parity test with scenes and props present, because the existing parity tests at `test_formal_image_finalization.py:267,294,362` clear `scenes` and `props` and so hide the problem. Then correct ADR-0149 §1: after the fix, existing storyboards that have both kinds of reference will go stale once.

### M1 MEDIUM: a bad music or ambience file is cached forever and blocks the render

- `lib/music_bed.py:78` and `lib/scene_ambience.py:74` return any existing `output` file as is. `_place` writes the server's response body without checking it is decodable, non-silent audio.
- `RenderAdapter._with_music` (`server/production_run/render_adapter.py:269-282`) catches only `MusicUnavailable`. These all escape it:
  - a `ValueError` from `response.json()` or `json.loads(item["result"])` in `_submit`/`_wait`;
  - `RenderRefused("MUSIC_SILENT")` (`lib/presentation_renderer.py:552`);
  - a `KeyError` or `ValueError` from `measure_loudness` on a file that is not audio.
- The adapter turns these into `OwnerBlocked("RENDER_MUSIC_SILENT")` or `RENDER_FAILED`. After 2 attempts the run is blocked (`RENDER_RETRY_LIMIT`). Because the file is cached by the cue's digest, every retry and every later run reuses the same bad file.
- **Scenario:** ACE-Step returns 200 with a near-silent or truncated WAV, or the MMAudio shim returns a JSON error body with status 200. The project can no longer render until someone deletes `production/music/<digest>.wav`.
- This contradicts the module's stated design ("a failed music request renders the episode without music").
- **Fix:**
  - Check the audio before `_place` (ffprobe duration > 0 and loudness above the floor). On failure raise `*Unavailable` and do not cache.
  - In the adapter, catch `Exception` (not only `*Unavailable`) and render without the layer.
  - In `_lay_music`, skip a silent bed instead of refusing.

### M2 MEDIUM: look-outlier regeneration can overwrite the face-judged best-of-N choice

- Each inspect runs `_redo_failing_units` before `_select_storyboards` (`media_adapter.py:196-201`). After selection restores the chosen version, the next inspect recomputes `_look_outliers` on the current storyboards (`:627-631`).
- A unit that becomes an outlier only because the judge picked the other candidate is regenerated once. That new, unjudged version becomes current. `select:{unit}:chosen` is already recorded, so the judge never looks at this unit again.
- **Scenario:** a two-character shot where the face-best candidate is darker than the scene's median. The identity win is silently replaced.
- **Fix:** skip outlier checks for units that have a `select:{unit}:chosen` attempt, or run the look check before candidate generation only. Alternatively feed outliers back through selection.

### M3 MEDIUM: derivative sheets now gate the workflow of existing interactive projects

- `lib/workflow_state.py:585,590-615` adds every derivative of a current character to the character sheet collection. A derivative with no sheet, or one not registered in the manifest, goes into `missing_ids`.
- `missing_sheets` (`:1674-1685`) then forces `state="ASSET_SHEETS"` before storyboards and videos are even evaluated.
- **Scenario:** a project on 2.5.17 that has a hand-written derivative with no sheet (ADR-0072 allows this) regresses from STORYBOARD/VIDEO/done to ASSET_SHEETS after the upgrade. This happens even if no shot names that derivative.
- The interactive agent's `generate_assets` tool (`server/media_tools/assets.py:276+`, enum `ALL_TYPES`) cannot route `owner/derivative` names. Only the production `MEDIA_TOOLS` mapping (`handle_generate_sheets`) can. So the agent is handed a next action whose ids its tool rejects. The rejection was not run; it follows from the tool schema.
- **Fix:** gate only on derivatives that the target episode's script references. Expose `character_derivative` in the agent tool, or keep derivative gaps informational for projects not run by automation.

### M4 MEDIUM: incremental rewrite of a scene's first shot splits that scene's look

- When the start entry is rewritten, `looks_to_write` (`lib/scene_looks.py:34-47`) asks for a new look. `apply_looks` (`:50-66`) applies it only to the rewritten segments. Kept segments of the same scene keep the old look, and their storyboard basis does not change.
- **Scenario:** E1S01 is rewritten and E1S02/E1S03 are kept. E1S01's storyboard is regenerated under look A′, while E1S02/E1S03 stay on look A. The look-outlier check then flags E1S01 against the kept majority.
- `tests/integration/lib/test_script_generator_incremental.py::TestSceneLooks` covers only the reverse case (a kept start).
- **Fix:** when a kept scene start exists, reuse its look even if the start entry is rewritten. Otherwise rewrite the whole scene.

### M5 MEDIUM: new required overview fields can fail overview generation

- `ProjectOverview` (`lib/project_manager.py:255-268`) now requires `color_grade` (Literal), `music_caption` and `music_bpm` (`ge=50, le=160`).
- `generate_overview` validates strictly (`:3825`). If a structured-output backend does not enforce numeric bounds (local or Ollama routes may not), a reply such as `"music_bpm": 45` fails the whole overview, and the run's overview step fails with it.
- **Unverified** which backends enforce `minimum`/`maximum`.
- **Fix:** give `color_grade` and `music_bpm` defaults, or clamp them in a `BeforeValidator`, as `CameraAngle` already does.

### L1 LOW: the cast block's "(reference image N)" can point at an image that was never sent

- `render_cast_block` (`lib/prompt_builders.py:266`) numbers the cast over all collected references, products included. The ComfyUI backend then drops everything after `max_reference_images` (`comfyui_image_backend.py:164-173`, now with a warning). The prompt can name a reference image 4 on a 3-slot endpoint.
- **Fix:** pass the backend's slot count, or omit the number for indices beyond it.

### L2 LOW: changing a character's description changes the storyboard prompt but not its basis

- The `Characters:` block and the `Framing:` line are prompt-only. The basis still hashes `image_prompt` and the reference sheets. A description edit without a sheet regeneration leaves storyboards CURRENT that were made from the old text.
- This is acceptable if intended. Record it in ADR-0142.

### L3 LOW: the cast-block de-duplication depends on the exact block text

- `prompt_builders.py:207` skips re-adding the block only if the identical string is already in a text-form prompt. If a reference label index changes between preview and execution (for example, a previous storyboard appears), the prompt ends up with a second, differing `Characters:` block.

### L4 LOW: the frozen face-judge policy can silently do nothing

- `_judge_by_face` (`media_adapter.py:358-383`) leaves the choice at `None` when `self._face` is None, or when the server errors. The error is caught at `:321-324`.
- A run frozen with `image_candidates=2` on a host whose `ARCREEL_FACE_ID_URL` was later removed, or whose face server is down, still pays for two storyboards per shot and selects nothing. Preflight checks only that the environment variable is set, not that the server is reachable.
- **Fix:** add a health probe in preflight, or record `face_unavailable` in `image_selection.json`.

### L5 LOW: synchronous image decoding on the event loop

- `_look_outliers` → `look_stats` (PIL open and convert of every storyboard) runs synchronously inside the async `inspect` on every media inspect, with no cache. `_judge_by_face` → `storyboard_problem` does the same.
- **Fix:** use `asyncio.to_thread`, and cache by mtime as `_unit_problem` does.

### L6 LOW: media cache keys and staging paths

- `MusicCue.digest` and `SceneWindow.digest` do not include the server or model identity. An ACE-Step or MMAudio upgrade reuses the old clips.
- `_place` uses a fixed `.part` path, so two concurrent renders of the same cue race on it.
- Render output depends on host environment variables (music and ambience on or off) that are not part of `RunPolicy`. They are recorded in the render manifest only.

## Checked and found sound

- **Stored-data compatibility (item 2).**
  - `project_storyboard_image_prompt` adds `camera_angle` and `look` only when they are present, so the basis of old scripts is unchanged.
  - The `narration_cue` default `none` maps to no tag, so the TTS basis of old units is unchanged.
  - The frontend editor spreads `...d.image_prompt`, so `look` and `camera_angle` survive a PATCH.
  - Scripts are re-dumped through Pydantic only for fresh LLM output (`script_generator.py:2039,2103`), so kept entries do not gain `camera_angle: "Eye Level"`.
- **TTS cue provenance.**
  - The version record stores the canonical text, tag included (`generation_tasks.py:1954-1990`). The provider receives `synthesis_text` (stripped for voices that do not speak the tags). The restore check `_validated_audio_basis` therefore still matches.
  - Subtitles never show the cue.
- **Launch profile (ADR-0151).**
  - The pinned `judge_prompt_digest` equals `FACE_JUDGE_RULE_DIGEST`. `image_judge_is_qualified` is True at HEAD.
  - The launch qualification record does not include `image_selection`, so there is no spurious `LAUNCH_QUALIFICATION_CHANGED`.
  - Runs already in progress keep their frozen policy.
  - On a host without `ARCREEL_FACE_ID_URL`, the policy falls back to one candidate, and preflight `IMAGE_JUDGE_NOT_QUALIFIED` correctly requires the server.
  - Caveat: the policy digest now depends on the host environment.
- **Renderer (item 4).**
  - Motion, grade, music ducking, ambience looping and the master trim pass the real-ffmpeg integration tests.
  - Zero or negative windows, unknown grades or moves, and a missing music file are refused early.
  - Only held-still units get motion; units with real video keep their own audio.
- **Look-outlier retries** are bounded to one per unit (`unit:storyboards:{unit}`), and only shots that carry a look are grouped (at least 3 per scene).
- **Derivative routing** in the production run splits `owner/derivative` names to `character_derivative` correctly. Extraction keeps only states whose evidence is attested in the source text.

## Missing coverage (item 8)

- Basis parity between execution and planner for a storyboard with a previous storyboard plus scene/prop sheets. This is the H1 gap.
- `RenderAdapter._with_music` and `_with_ambience` given a malformed or silent cached file, or a non-JSON server response.
- Interaction between look outliers and best-of-N selection.
- Workflow state of an existing project whose derivative has no sheet. Agent tool behaviour on `owner/derivative` ids.
- Incremental rewrite of a scene's first shot while its siblings are kept.

## Verdict: REJECT at `a623140e3`. It becomes ACCEPT once the conditions below are met.

Conditions for r2-v2.5.18:

1. **Fix H1:** use the same reference order in `lib/artifact_planner.py` and in execution. Add a parity test with scenes and props present plus a previous storyboard. Correct ADR-0149 §1, which should note that existing storyboards with both kinds of reference go stale once after deploy.
2. **Fix M1:** validate media before caching it. Treat any music or ambience failure, silent bed included, as "render without the layer" instead of blocking the render.
3. **Fix M2:** do not let a look-outlier regeneration replace a version chosen by the judge.
4. **Fix M3 or explicitly accept it:** at minimum, do not gate existing interactive projects on unreferenced derivatives without sheets, and make the agent tool able to act on the ids it is given.
5. M4, M5 and the LOW items may follow as tracked work. M5 is cheap, and doing it before deploy is recommended.

## Dispositions (main agent, 2026-11-14)
| Finding | Disposition |
|---|---|
| H1 | Fixed: planner uses the execution order and resolves derivative names; parity test `tests/integration/lib/test_storyboard_reference_parity.py` (fails on the old planner). ADR-0149 amended. |
| M1 | Fixed: WAV-only cache (music, ambience), adapter catches every music/ambience failure, renderer skips a broken layer with `{"skipped": code}`; unique temp paths (part of L6). Tests: non-audio answer not cached; silent music skipped. |
| M2 | Fixed: look-outlier redo skips units with `select:<unit>:chosen`. ADR-0145 amended. |
| M3 | Fixed: derivative sheets requested only when a shot of the target episode names them; agent tool routes derivative names. Tests in `test_workflow_state.py`, `test_assets.py`. ADR-0146 amended. |
| M4 | Fixed: a rewritten scene start spreads its new look to the kept shots of the scene. Test in `test_script_generator_incremental.py`. ADR-0141 amended. |
| M5 | Fixed: overview fields defaulted, unknown grade → neutral, no tempo bounds. ADR-0140 amended. |
| L1 | Accepted: the numbering names the order sent; a backend that drops trailing references logs which (ADR-0149). |
| L2 | Accepted: a character description change already stales the sheet and through it the storyboard. |
| L3 | Accepted (text-shaped prompts only; numbering is computed by the same assembly in preview and execution). |
| L4 | Accepted for this release: the face server is a local service with a systemd unit; a down server leaves the current version (no wrong pick). |
| L5 | Accepted (small images, bounded count). |
| L6 | Temp paths fixed; cache keys and host env accepted (documented in ADR-0143/0150/0151). |

## Round 2: verification of `cf4b6b70e` (independent reviewer)

**Evidence**

- Read the fix diff: `git diff HEAD~1 -- lib server`.
- Recreated the round-1 throwaway probe. It now generates E1S02 (Alice, 祠堂, 玉佩, previous storyboard E1S01) and asserts that the digest execution registers equals the digest from `resolve_current_artifact_basis`. **It passes** end to end. The probe was deleted after the run.
- Related tests, run with `uv run python -m pytest -n 4`: **357 passed, 22 skipped**. The run included the new `test_storyboard_reference_parity.py`, the renderer, render inputs, music and ambience, look consistency, media adapter, workflow state, the assets tool, incremental script generation, project manager, prompt preview, formal image finalization, execute generation, prompt builders and preflight.

**Per-finding verdict**

- **H1: fixed.**
  - `artifact_planner._storyboard_references` now inserts the previous storyboard before the scene sheets, so its order matches execution: products, cast, previous, scenes, props.
  - Derivative names (`owner/derivative`) now resolve to the derivative's sheet. Before, a shot naming a derivative was not planned at all; now it can be current. This is an improvement, not a regression.
  - Expected one-time effect after deploy: storyboards registered under 2.5.17 that have both kinds of reference go stale once. ADR-0149 now says so.
- **M1: fixed.**
  - `_place` caches only RIFF content of at least 1 KiB, and the staging path is unique per write.
  - The adapter catches every `Exception` (`CancelledError` is a `BaseException`, so cancellation is not swallowed).
  - The renderer skips a layer on any `RenderRefused`, with `measure_loudness` raising `AUDIO_PROBE_FAILED`, and records `{"skipped": code}`.
  - Residual LOW: a valid but silent WAV stays cached, so that cue renders without music every time. It no longer blocks anything.
- **M2: fixed.** An outlier is skipped when `select:<unit>:chosen` has an attempt.
- **M3: fixed.**
  - Only derivatives named by a shot of the target episode gate `ASSET_SHEETS`. Unnamed ones are still reported in `missing_ids`.
  - The agent tool routes `character` + `owner/derivative` names to `handle_generate_derivative_sheets` and refuses mixed batches with a clear problem message.
  - Residual LOW: a script name that differs from the canonical `derivative_reference` spelling (case or spacing) does not gate. That fails safe.
- **M4: fixed.** After `_assemble_script`, a scene's newly written look is applied to every segment of that scene. Kept siblings of a rewritten scene start therefore change basis and are regenerated once. This is intended, but it relaxes the "unchanged entries pass byte-identical" note in that function. LOW: update the comment.
- **M5: fixed.**
  - `color_grade` has a default plus a fallback to `neutral`; `music_caption` defaults to `""`; `music_bpm` defaults to 80 with no bounds.
  - `cue_for` clamps the tempo to 30–300, not to the 50–160 the description states. LOW.
  - Now that these fields are optional, a backend may leave them out. The episode then has no music. That is acceptable.
- **LOW items L1–L6: unchanged.** They are tracked work and do not block the release.

**New issues introduced by the fixes:** none at MEDIUM or above.

**Final verdict: ACCEPT** for r2-v2.5.18 at `cf4b6b70e`. Deployment note: expect one stale-and-regenerate pass for 2.5.17 storyboards that have both a previous storyboard and scene or prop sheets.

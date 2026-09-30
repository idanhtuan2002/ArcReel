# V2-03 ComfyUI port ledger

Plan: `docs/superpowers/plans/2026-09-30-r2-v2-03-comfyui-backport.md`. Rules R1–R6. Branch `impl/r2-v2-03-comfyui` from `r2-v2/main` `2b1623fe`.

**Baseline** (T0, before any change): 1321 passed. The targeted set was `tests/unit/lib/custom_provider`, `tests/integration/lib/custom_provider`, the custom provider, custom endpoint and endpoint-test router tests, `tests/unit/r2/host_hardening`, and `test_custom_provider_repo.py`.

## 69967549 — glossary + ADRs

- `CONTEXT.md` conflicts:
  - The ComfyUI terms block: took the donor's version (R4).
  - The prompt-template block: kept the fork's version. The fork lacks the intermediate upstream template glossary, so the donor's negative-prompt wording hunk did not apply and was dropped.
- ADR-0081 was renamed to `docs/adr/0100-…` and ADR-0082 to `docs/adr/0101-…`, each with an imported-reference note (R4).

## 31618e1e — kind dispatch refactor (prerequisite 1, pre-ComfyUI upstream)

This commit was added to the series ahead of `56cb567d`. The upstream refactor adds a `kind` table in four places:
- the validator;
- the spec projection;
- the capacity-table lane projection;
- the endpoint-test modes.

In every one of them the declarative behaviour is unchanged.
- `tests/fakes.py`: kept the fork's version and appended `bind_safe_session_factory` (R2).
- `test_generation_worker_module.py`: took the donor's move of `TestCapacityTable` into `test_generation_worker_capacity_table.py`. The fork's only change in that region was dropping two local `import logging` lines.
- **R5 extension.** The `generation_worker.py` hunk is `CapacityTable.from_db`, which now reads media types from the resolved endpoint spec and skips unresolvable rows. That is lane configuration, not execution: it is the same seam as ADR-0099 §3.
- **Verify:** 1079 passed. The set was the custom_provider unit and integration tests, the three router tests, the capacity table, the worker module, the resume custom-endpoint chain, and i18n.

## 56cb567d — ComfyUI definition schema, validator, import routing (T1)

- `endpoint_definition/errors.py` was renamed to `lib/custom_provider/definition_diagnostics.py`. This is the donor's rename, and git detected it cleanly. Every fork import was updated by the donor hunks, and a grep found no stale `endpoint_definition.errors` imports. Following the donor layout replaces R1's "remap".
- **R3, market provenance (`927d1125` / `740e7929`), dropped:**
  - `MarketInstallDialog.test.tsx` and `EndpointImportDialog.test.tsx`: the fork has neither file; the second was created by the market commits. T11 adds a ComfyUI import-shape test.
  - All `min_app_version` / `meets_min_app_version` / `parse_semver` hunks in `server/routers/custom_endpoints.py`, `frontend/src/types/custom-endpoint.ts`, `EndpointImportDialog.tsx` and `EndpointsSection.test.tsx`.
  - The `EndpointInstallation` import.
- `comfyui/schema.json`: `$defs.semver` and `$defs.meta` were synced to the fork's declarative schema. That removes the market's `min_app_version` and the semver `maxLength`, and keeps the donor's rule that the two kinds share their defs byte for byte (the `test_shared_defs_are_identical…` test).
- `tests/factories.py`: both sides kept (the fork's narrative factories plus the donor's ComfyUI factories).
- `pyproject.toml`: the donor's import-linter contract "ComfyUI 端点实现不依赖声明式运行时" was added. `lint-imports`: 21 kept, 0 broken.
- **Verify:**
  - pytest: 1119 passed (custom_provider unit and integration, the three router tests, `test_imports`, i18n).
  - `pnpm typecheck`: clean.
  - vitest `settings`: 115 passed.
- The unknown-kind and missing-kind no-regression tests are already in the donor (`test_endpoint_definition_validator.py::test_unknown_kind_*`, `test_missing_kind_is_rejected_at_the_root`).

## 6c0bb0c0 — workflow request builder (T2)

- `lib/prompt_utils.py`, R2:
  - The fork keeps its own `normalize_video_prompt` (`append_video_negative_tail`). The donor's `builtin_templates` render path belongs to the intermediate upstream template work and was not taken.
  - Taken: `_AVOID_LINE`, `_AVOID_SEPARATOR`, `_BLANK_RUN`, `split_avoid_lines` and `append_avoid_text`.
  - Not taken: the intermediate `yaml_section`.
- **Adaptation.** The fork's negative tails are `禁止出现：…。` (video) and `画面避免：…。` (image), not `Avoid:`. `_AVOID_LINE` also recognises those two prefixes and drops a trailing `。`, so a ComfyUI endpoint lifts the fork's tail into the negative-prompt binding. The only callers are `comfyui/request_builder.py`.
  - New test: `TestSplitAvoidLines::test_the_negative_tails_the_prompt_builders_append_are_lifted`.
- `tests/unit/lib/test_prompt_utils.py`: dropped the donor's conflicting template-render tests, which belong to the intermediate template system.
- **Verify:** `test_prompt_utils.py` and `tests/unit/lib/custom_provider/comfyui`: 164 passed.

## 1cf11b02 — ComfyUI provider, bidirectional attachment, lane default (T3)

- Clean apply, no conflicts.
- **R5:** `generation_worker.py` gains `COMFYUI_LANE_DEFAULT = 1` and `CapacityTable._custom_lane_default`. An explicit column wins. This is the ADR-0099 §3 default.
- **Adaptation** (amended into the cherry-pick): `test_custom_providers_comfyui.py::test_an_empty_api_key_is_accepted` read the stored key through `GET /custom-providers/{id}/credentials`. The fork deliberately removed that plaintext endpoint in `daf5755a`, and `test_custom_providers_api.py` asserts 404/405 for it. The test now reads the stored row through `CustomProviderRepository.get_provider`. The endpoint is not restored.
- ComfyUI model discovery returns a structured "not applicable" (donor `discovery_formats.py` plus the router), and the connectivity check is `/system_stats`.
- **Verify:**
  - `test_custom_providers_{api,comfyui}.py`, the capacity table, the provider repo and custom_provider: 1100 passed after the fix (1099 plus the fixed test).
  - `pnpm typecheck`: clean.
  - vitest (settings, shared, utils): 530 passed.

## 1012fe07 — binding-candidate inference and rematch (T4)

- `server/routers/custom_endpoints.py`: took `comfyui_inference` into the router import. Dropped the donor's `_market_installations` imports, `get_app_version_reader` and the unused `logger` (R3).

## 98ee8ffb — stage-1 convergence and AI-review fixes (T4)

- **R3 — dropped as market provenance (`71f7b7ca` / `c5b1e2d7`):**
  - `MarketInstallDialog.tsx`;
  - `export-endpoint-definition.ts`;
  - the export filename with the installation slug;
  - the market-contribute link;
  - the `installation` field on the ComfyUI test fixture.
- **Kept:**
  - `EndpointDetail.tsx`: `savedRecordOf`, `exportable`, the ComfyUI read-only mode, and the shared `exportButton` / `deleteButton`. Export stays on the fork's inline `downloadBlob(definitionFileName(...))`, now typed `AnyEndpointDefinition`.
  - `EndpointsSection.tsx`: `isDeclarativeDefinition` and the custom-image listing.
- `EndpointsSection.test.tsx`: added a local `captureDownloads` helper (the donor's came from market work). The expected export filename follows the fork's `definitionFileName`: `ComfyUI.json`.
- `lib/db/models/custom_endpoint.py`: comments only, so no migration is needed.
- **Verify:**
  - pytest (custom_provider unit and integration, the four router tests, the capacity table, the db repositories, i18n): 1366 passed.
  - `pnpm typecheck`: clean.
  - vitest `settings`: 141 passed.

## d027b2e6 — ComfyUI video backend and failure encoding (T5, prerequisite 4)

- **R5 check, `generation_worker.py`:** `ComfyuiError` was appended to the fork's longer failure-encoder union, after `PaidRouteUnqualifiedError | BudgetScopeMissingError | BudgetExceededError`.
- **R5 check, `media_generator.py`:**
  - Kept the fork's `AttemptSubmitter` type import and `execution_id` metadata.
  - Added `_merge_result_provenance` and its call, which runs after `execution_id`.
  - Did not take the donor's intermediate `_input_path` / `_ledger_inputs`.
- **SECURITY FIX during merge — `lib/video_backends/base.py`:** the donor replaced `current_json` with `_Body(json, files, data)`. The fork's `420b3d89` cross-origin rule (`if url_origin(hop.url) != credential_origin: current_json = None`) auto-merged unchanged. After the merge it assigned a dead variable, so the request body, including multipart `files`, would have been forwarded to another origin on 307/308.
  - The rule is now `body = _Body()`, and the docstring says so.
  - New regression tests: `TestScopedRedirectBody` (a cross-origin 307 drops the multipart body and `X-API-Key`; a same-origin 307 resends the body).
  - The fork's existing `test_submit_redirect_to_another_origin_drops_custom_auth_headers` also covers the JSON body.
- **Adaptation:** the fork's `stream_to_file` requires `max_bytes`. `ComfyuiClient.download_output(max_bytes=...)` now takes it (the same shape as upstream's later code), and `ComfyuiVideoBackend` passes `ARTIFACT_MAX_BYTES_BY_MEDIA_TYPE["video"]`.
- **OPEN — close in T9/T10:** at this donor layer, `comfyui_backend.py` still uses a plain `httpx.AsyncClient(follow_redirects=True)`, not `artifact_http_client`. ADR-0099 §4 requires the guarded client, with link-local/metadata refusal on every hop.
- **Verify:** 2398 passed (`video_backends`, `custom_provider`, `media_generator_module`, `generation_worker_module`, `task_failure_capability`).

## 5b45272e — binding editor UI (T6)

- **R3, dropped:**
  - the market props (`onUpdateFromMarket`, `marketUpdatePending`, `MarketUpdateTarget`);
  - the `min_app_version` notice;
  - `installation` in the fixtures and in the export slug;
  - `EndpointImportDialog.test.tsx` again.
- **Upstream components absent from the fork** (introduced by intermediate upstream commits): `EndpointReferenceList` and `EndpointDuplicateChoices`.
  - `confirmDeleteDialog` was rebuilt from the fork's inline reference list.
  - The import dialog keeps the fork's inline duplicate list, gated by `!toBindings`.
- `export-endpoint-definition.ts` was re-created fork-local, without the installation slug. `EndpointDetail` and `ComfyuiEndpointDetail` share it.
- The duplicate donor `captureDownloads` in the test was dropped in favour of the helper added at `98ee8ffb`. The expected filename is `ComfyUI.json`.
- **Verify:**
  - `pnpm typecheck` and eslint on `settings`: clean.
  - vitest `settings`: 203 passed.
  - pytest (custom_provider, the endpoints and inference routers, i18n): 1185 passed.

## e03491ee — video backend robustness: remote interrupt, resume, failure set, warnings (T6)

- `comfyui_backend.py`: kept the fork's `ARTIFACT_MAX_BYTES_BY_MEDIA_TYPE` import plus the donor's extended failure imports.
- `server/services/generation_tasks.py`:
  - Kept the fork's M7 `attempt_submitter` / `AsyncExitStack` block and the `execution_id` result field.
  - Added `warnings=warnings` inside the fork's block and the donor's `warnings` result key.
- **R5 extension:** the `warnings` channel is a non-blocking list. It goes backend `result.warnings` → `MediaGenerator._collect_result_warnings` → task `result["warnings"]`, the same for the first run and for resume (`resume_executor.py`, `reference_video_tasks.py`, `video_artifact_currency.py`). It adds no state, lane or path. On resume, `_merge_result_provenance` also runs.
- `test_media_generator_resume.py`: kept both the fork's log-redaction test and the donor's resume provenance and warnings tests.
- **Verify:** 2542 passed (media_generator resume, custom_provider, execute_video_task, resume custom-endpoint chain, media_generator_module, video_backends, server/services).

## 1ec7bd84 — video capabilities and size/duration constraints derived from bindings (T6)

- Clean apply.
- **Verify:** 1770 passed (custom_provider, config unit and integration, ComfyUI providers router, model candidates, capability overrides). `pnpm typecheck`: clean.

## fe4bd3a1 — endpoint test for ComfyUI: preview and trial run (T7, prerequisite 1b)

- `trial_run.py`, `cancel` docstring: took the donor's remote-cancel explanation but kept "按失败结算". The code settles with `resume_failed`, and the module docstring says the same. The donor's pre-existing "按取消结算" wording did not match the code.
- `server/routers/endpoint_tests.py`: kept the fork's `PaidRouteUnqualifiedError` import and took the donor's `encode_failure`.
- **ADR-0099 §2 check:** every trial run, ComfyUI included, goes through `TrialRunManager.start`, which calls `require_paid_route(PaidRoute("trial_run"))` (`trial_run.py:297`). ComfyUI's `gate_capabilities=False` skips only the capability gate, not qualification.
- **Verify:** 1634 passed (custom_provider, endpoint-tests router, i18n, `r2/host_hardening`).

## fc3126b9 — seams between the five tickets and AI-review fixes (T7)

- **R3, dropped:** `EndpointImportDialog.test.tsx`, `minAppVersion` and `MarketUpdateTarget`. `detailInstanceKey` no longer takes the market `installation.installed_at` component; only the re-import draft token changes the instance.
- `EndpointImportDialog.tsx`: kept the fork's inline duplicate list, now reading the donor's stale-guarded `result`.
- `test_task_failure_capability.py`: kept the fork's `VideoCapability` import. The donor's `VideoGenerationType` does not exist in the fork and is not used.
- **Verify:**
  - `pnpm typecheck`: clean.
  - vitest `settings`: 221 passed.
  - pytest (custom_provider, task_failure_capability, the three routers, i18n): 1501 passed.

## 9116977e, ac308078 — tier hints and re-import title check (T7)

- Both applied cleanly. They are verified together with T8.

## 62a55eab — image lane: storyboard images and i2i through ComfyUI (T8)

- **R3:** dropped `lib/market/{__init__,entry,generate}.py` and the three market test files. None of them exists in the fork.
- `comfyui_backend.py`: took the donor's move of polling and download into the shared `comfyui_execution.py`.
- **Adaptation:** `ComfyuiExecution` passes `max_bytes=ARTIFACT_MAX_BYTES_BY_MEDIA_TYPE[self._media_type]` to `download_output`, so the image lane is capped at 256 MiB and the video lane at 2 GiB. This is the same shape as upstream's later `comfyui_execution.py:116`.
- **Adaptation:** `test_comfyui_image_backend.py` dropped the `backend.max_reference_images` assertion on the `CustomImageBackend` wrapper. That forwarding property comes from intermediate upstream `d1951f76` (storyboard reference trimming), and the fork's `ImageBackend` protocol and wrapper have no such member and no consumer. `ComfyuiImageBackend` still caps references to its bound slot count itself (`comfyui_image_backend.py:151-153`).
- **Verify:**
  - pytest: 1785 passed.
  - `pnpm typecheck`: clean.
  - vitest `settings`: 222 passed.

## a1ba44db, c8cac44f, d15192b3 — ComfyUI test UI, guide, stage-3 seams (T8)

- `a1ba44db`: `endpoint_tests.py` imports now combine the fork's `PaidRouteUnqualifiedError` with the donor's `parse_failure`.
- `c8cac44f` (R4):
  - Dropped `website/**/guide/market.md`, the market line in `CONTRIBUTING.md` and the market pointer in `providers.md`.
  - Kept the ComfyUI guide, its `CONTRIBUTING.md` row and its `providers.md` pointer.
  - Sidebar order follows the donor minus market: comfyui 4, jianying-export 5, faq 6.
- `d15192b3`: clean apply.

## Checkpoint after Series A (HEAD at time of writing, before the ledger commit)

- **Deletions compared with `r2-v2/main`:** only the donor rename `endpoint_definition/errors.py` → `definition_diagnostics.py`. Every `git rm` during conflict resolution removed a file that does not exist in `r2-v2/main`: market files and the upstream-only `EndpointImportDialog.test.tsx`. It was a "deleted by us" conflict, not fork content.
- **Targeted pytest:** 5103 passed, 1 skipped. The set was custom_provider, image and video backends, the five routers, the worker capacity/module, media_generator, task_failure, prompt_utils, server/services, i18n, `r2/host_hardening`, `lib/db`, `test_imports` and config.
- `lint-imports`: 22 kept.
- **Frontend:** `pnpm typecheck` OK, `pnpm lint` OK, vitest 2556 passed / 4 skipped (218 files).

## T9 — Series B forward-ports

The ports went through the path-remap + `git apply -3` script (upstream pre-image blobs), then an import remap to the flat layout.

- **`42b08c67`** → `56d88e6f`: the whole commit minus market. `lib/generation/task_failure.py` maps to `lib/task_failure.py`. Added an import-linter `ignore_imports` entry `lib.task_failure -> lib.custom_provider.comfyui.artifacts`: the layers contract reached `artifacts` through `video_backends.base → generation_queue → task_repo → task_failure`, and `artifacts` is a static-whitelist leaf.
- **`8faf1450`** → `4b30292f`: only the ComfyUI `/system_stats` probe through `artifact_http_client`. The fork already had the Anthropic discovery guard and the redirect-body scope (`420b3d89`). The donor's metadata-destination probe test is included.
- **`a300b786`**: nothing to port. The fork keeps `_encode_task_failure_message`, and the one ported test call site uses it.
- **`62456ef1`** (+ the ComfyUI call sites of `2c4ca6d6`) → `da466ff3`:
  - Added `lib/container_sniff.py` and `notify_provider_response_to` (prerequisite 2), plus the artifact container whitelist and the image-endpoint trial run.
  - Not taken: the intermediate `CallPurpose` ledger tag, which the fork does not have.
  - `2c4ca6d6` was missed by the gate-1 trace, because it touched the pre-`9d89cc84` flat paths. Its ComfyUI hunks are the `artifact_http_client` switch (video, image, remote stop) and `download_output(max_bytes)`. The fork adaptations made at T5/T8 turned out to be identical to it. **This closes the T5 OPEN item**; new donor tests cover a `/view` redirect to 169.254.169.254 (refused) and a body over `VIDEO_ARTIFACT_MAX_BYTES` (aborted).
- **`301c8a38`** → `6d265a79`: taken in full, not "ADR hunk only" as the plan had it.
  - The fixed-duration hunks are the ComfyUI fix: an endpoint with no `frames` binding was refused at enqueue on both video routes. The fork had the same guard (`reference_supported_durations_missing`).
  - Remaps: `lib/script/reference_video` → `lib/reference_video`, `lib/speech` → `lib`, `server/services/tasks` → `server/services`, and the fork's `capability=` in place of `generation_type=`.
  - Two tests were adapted to the fork's harness: the checkpoint hook takes `api_call_id`, and the second narration code depends on the fixture, so the ordering is asserted instead.
- **`3ff6127f`** → `d9b10dd0`: ComfyUI part only (docstring and `test_comfyui_execution.py`). Not taken: the built-in provider resume-expiry gate, and upstream's removal of the replace-models route (the fork keeps the route and its tests).
- **`ab714d98`** → `6c6590cd`: clean.
- **`24e79da0`**: fixed the missing `Callable` import in `custom_endpoints.py`. It came from the `56cb567d` conflict resolution and was caught by ruff F821.
- **Completeness re-check:** a `git log d15192b3..4b277b4c` over both the flat and the package ComfyUI paths lists only these commits, plus the excluded market commits (`82850227`, `07d84da6`, `074d81ce`) and the reorg commits (`e00e28b8`, `1a943710`, `9d89cc84`). The ComfyUI hunks of the reorg commits are imports and docstrings only.

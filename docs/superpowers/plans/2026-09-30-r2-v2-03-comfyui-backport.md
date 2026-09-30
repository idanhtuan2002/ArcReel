# V2-03 ComfyUI backport — executable plan (gate 3)

**Decisions:** ADR-0099 and its Amendment 1 (`3ecd64ae`).
**Research:** `docs/research/2026-09-29-r2-v2-03-comfyui-dependency-trace.md`.
**Packet:** `R2_V2_03_COMFYUI_PACKET_OPENED_2026-09-29.md`.
**Branch:** `impl/r2-v2-03-comfyui`, from `r2-v2/main` at `3ecd64ae`. Worktree `.worktrees/r2-v2-03`.
**Donor:** upstream `ArcReel/ArcReel` (remote `upstream`).
- Series A is `69967549..d15192b3`, on the flat layout.
- Series B is seven later ComfyUI commits, forward-ported onto the flat layout.

**Constraints:**
- No paid provider calls. Every ComfyUI test uses the donor's mocked HTTP transport.
- No push.
- No full pytest suite. Run targeted tests plus the static gates.
- `lib/generation_worker.py` may change only in three ways:
  - the `ComfyuiError` member of the failure-encoder union;
  - `COMFYUI_LANE_DEFAULT` and its use in `CapacityTable`;
  - nothing else. No new execution path, lane or task state is added.

## Conflict-resolution rules

These rules apply to every cherry-pick.

- **R1 — ComfyUI-owned and new files.**
  - Take the donor file.
  - If a new non-ComfyUI file duplicates a fork module, remap instead of adding it. Example: the donor's `lib/custom_provider/definition_diagnostics.py` duplicates the fork's `endpoint_definition/errors.py`. Record the choice in the ledger.
- **R2 — Conflicted fork files.**
  - Keep the fork's version, then apply only that commit's own hunks (`git show <c> -- <path>`).
  - Never take the whole upstream file with `--theirs`. The probe showed that this pulls in intermediate upstream work (for example `lib.prompt_style`) and breaks import.
  - When a hunk needs an upstream symbol the fork lacks, map it to the fork's equivalent. If there is none, port the smallest self-contained piece and record it.
- **R3 — Market.**
  - Drop every hunk under `lib/market/`, `frontend/**/settings/market/` and the market tests. The fork has no market module.
  - Also drop market-only fields in shared files.
- **R4 — Docs.**
  - Upstream ADR-0081 and ADR-0082 become `docs/adr/0100-…` and `docs/adr/0101-…`. Each gets a header line: "Imported reference from upstream ADR-008x at `d15192b3`; not re-decided here."
  - Merge the CONTEXT.md glossary entries into the fork's CONTEXT.md.
  - Take the website ComfyUI guide and the providers guide ComfyUI section.
  - Drop unrelated guide hunks (faq, jianying-export, market).
- **R5 — Authority.**
  - Hunks in `generation_worker.py`, `media_generator.py`, `server/services/generation_tasks.py` or `resume_executor.py` must match the list below.
  - Anything else in those files stops the series and needs its own ADR check. Allowed:
    - the failure-encoder union;
    - the lane default;
    - `_merge_result_provenance`, which writes to version metadata after a successful call;
    - the ComfyUI resume branch inside the existing resume executor.
- **R6 — Provenance.**
  - Cherry-pick with `-x`.
  - For each commit, the ledger records the conflicted paths, how each was resolved, and any remap or dropped hunk.

The ledger is `docs/r2/evidence/R2_V2_03_PORT_LEDGER.md`: one section per donor commit.

**Import remap table (Series B only).** Series A already uses flat paths.

| Upstream (post-reorg) | Fork |
|---|---|
| `lib.backends.backend_runtime.*` | `lib.video_backends.base` |
| `lib.backends.artifact_download_guard` | `lib.artifact_download_guard` |
| `lib.backends.http_status_errors` | `lib.http_status_errors` |
| `lib.backends.container_sniff` | new `lib/container_sniff.py` |
| `lib.backends.image_backends.base` | `lib.image_backends.base` |
| `lib.infra.{api_errors,logging_utils,retry,validation_messages}` | `lib.{…}` |
| `lib.prompts.prompt_utils` | `lib.prompt_utils` |
| `lib.generation.task_failure_encoding.encode_task_failure_message` | `lib.generation_worker._encode_task_failure_message` |
| `arcreel_market_core.comfyui.*` | `lib.custom_provider.comfyui.*` |
| `arcreel_market_core.video_backend_contract` | `lib.video_backends.base` |
| `arcreel_market_core.auth_section` | `lib.custom_provider.auth_section` |
| `arcreel_market_core.aspect_size` | `lib.aspect_size` |
| `server.i18n.Translator` | `lib.i18n.Translator` |

## Tasks

The per-task verification command is referred to below as **T-verify**. It runs `uv run python -m pytest -q -p no:cacheprovider <task tests>` plus the import smoke check `uv run python -c "import server.app"`. It must pass before the next task starts. Commit each resolved cherry-pick as it lands.

### T0 — Workspace

1. Create the worktree: `git worktree add .worktrees/r2-v2-03 -b impl/r2-v2-03-comfyui r2-v2/main`.
2. Run `uv sync` and `pnpm -C frontend install --frozen-lockfile`.
3. Create the ledger skeleton.
4. Record the baseline by running the targeted test set once before any change:
   `tests/unit/lib/custom_provider tests/unit/server/routers/test_custom_providers_api.py tests/unit/server/routers/test_custom_endpoints_api.py tests/unit/server/routers/test_endpoint_tests_api.py tests/integration/lib/test_generation_worker_capacity_table.py tests/unit/r2/host_hardening`

### T1 — Kind dispatch, definition side (prerequisite 1a)

- **Commits:** `69967549` (docs, glossary; follow R4) and `56cb567d`.
- **Brings:** `endpoint_definition/kinds.py`, the kind-dispatching `validate_definition`, the schema `kind` enum `["declarative","comfyui"]`, the ComfyUI definition schema and validator, and import routing.
- **Must hold:** every existing declarative definition test passes unchanged. `builtin_endpoints/*` still validate.
- **Tests:**
  - `tests/unit/lib/custom_provider/endpoint_definition`
  - `tests/unit/lib/custom_provider/comfyui/test_comfyui_definition_{schema,validator}.py`
  - `tests/unit/lib/custom_provider/test_endpoint_resolution.py`
  - `tests/unit/server/routers/test_custom_endpoints_api.py`
- **Add one test:** a declarative definition whose `kind` is missing or unknown is refused with the same diagnostic code as before.

### T2 — Request builder

- **Commit:** `6c0bb0c0`.
- **Conflict:** `lib/prompt_utils.py` (R2). Take only `split_avoid_lines` / `append_avoid_text` if they are absent.
- **Tests:** `test_comfyui_request_builder.py`, `tests/unit/lib/test_prompt_utils.py`.

### T3 — Provider ↔ endpoint binding, lane default, discovery format (prerequisite 3a)

- **Commit:** `1cf11b02`.
- **Brings:**
  - `discovery_formats.py`: `comfyui`, and `endpoint_attachment_holds`;
  - `DiscoveryFormatLiteral` with `comfyui`;
  - `COMFYUI_LANE_DEFAULT = 1` in `CapacityTable` (R5).
- **Must hold:** `discovery.py` refuses model discovery for `comfyui` with a structured "not applicable". It does not raise `ValueError`. If the donor only reaches this in `8faf1450`, record that in the ledger and close it in T9.
- **Tests:**
  - `tests/unit/server/routers/test_custom_providers_{api,comfyui}.py`
  - `tests/integration/lib/test_generation_worker_capacity_table.py`
  - `tests/unit/lib/db/repositories/test_custom_provider_repo.py`

### T4 — Binding inference

- **Commits:** `1012fe07` and `98ee8ffb`.
- `98ee8ffb`'s frontend conflicts follow R2 and R3.
- **Tests:**
  - `test_comfyui_{inference,inference_rules,import_shapes,graph}.py`
  - `tests/unit/server/routers/test_comfyui_inference_api.py`

### T5 — Video backend and failure encoding (prerequisite 4)

- **Commit:** `d027b2e6`.
- **Conflicts** (R2 and R5):
  - `generation_worker.py`: the union member only;
  - `media_generator.py`: `_merge_result_provenance` and its single call;
  - `video_backends/base.py`: `_Body` / multipart in `request_with_scoped_credentials`, and `VideoGenerationResult.provenance`.
- **Tests:**
  - `tests/unit/lib/custom_provider/test_comfyui_video_backend.py`
  - `tests/unit/lib/video_backends` (the part covering scoped credentials)
  - `tests/integration/lib/test_media_generator_module.py`

### T6 — Bindings UI, robustness, capability derivation

- **Commits:** `5b45272e`, `e03491ee`, `1ec7bd84`.
- **Conflicts:**
  - `e03491ee` touches `server/services/generation_tasks.py` and the resume tests. R5 applies: only the ComfyUI resume branch is allowed.
- **Tests:**
  - `test_comfyui_capabilities.py`
  - `tests/unit/lib/test_media_generator_resume.py`
  - `tests/integration/server/services/test_execute_video_task.py`
  - the frontend `comfyui-bindings.test.ts`

### T7 — Kind dispatch, endpoint-test side (prerequisite 1b)

- **Commits:** `fe4bd3a1`, `fc3126b9`, `9116977e`, `ac308078`.
- **Brings:** `endpoint_test/kinds.py`, `endpoint_test/modes.py`, `endpoint_test/comfyui.py`, and the error keys in `lib/i18n/{en,vi,zh}/errors.py`.
- **Must hold:** the declarative endpoint test (preview and trial run) behaves exactly as before.
- **Tests:**
  - `tests/unit/lib/custom_provider/test_endpoint_test_{modes,comfyui}.py`
  - `tests/unit/server/routers/test_endpoint_tests_api.py`
  - `tests/integration/lib/test_task_failure_capability.py`
  - `tests/unit/lib/i18n/test_i18n_consistency.py`

### T8 — Image lane, settings UI, guide

- **Commits:** `62a55eab` (R3 drops `lib/market/*` and the market tests), `a1ba44db`, `c8cac44f` (R4), `d15192b3`.
- **Tests:**
  - `tests/unit/lib/custom_provider/test_comfyui_image_backend.py`
  - `tests/unit/lib/custom_provider/comfyui`
  - frontend `ComfyuiEndpoint*.test.tsx` and `CustomProviderForm.comfyui.test.tsx`

### T9 — Series B forward-ports (prerequisites 2 and 3b)

Apply each commit with `git show <c> | git apply -3 --include=<comfy-relevant paths>`, then use the remap table. Commit each as `port(comfyui): <subject> (upstream <c>)`.

1. **`42b08c67`:** the artifact-type hint.
2. **`8faf1450`:** the provider probe and model discovery go through the outbound-destination check. Take the `discovery.py` hunks and the ComfyUI probe (`GET /system_stats`, which returns `comfyui_version`). Map `backend_runtime` to `lib/video_backends/base.py`.
3. **`a300b786`:** adapt the test to `_encode_task_failure_message`.
4. **`62456ef1`:** add `lib/container_sniff.py` and `notify_provider_response_to` in `lib/video_backends/base.py`, then the artifact whitelist and the upload convention.
5. **`301c8a38`:** take the ComfyUI and ADR-0082 hunks only. Note in the ledger which fixed-duration and TTS hunks are out of scope.
6. **`3ff6127f`:** take only the `comfyui_execution.py` hunks and the `backend_runtime` pieces they need. Not the resume-expiry rework and not the built-in provider changes.
7. **`ab714d98`:** the Hailuo H3 rule slots and 2 fixtures.

- **Tests:**
  - the whole `tests/unit/lib/custom_provider`
  - `tests/unit/lib/custom_provider/test_model_discovery.py`
  - new `tests/unit/lib/test_container_sniff.py`
  - the tests for `notify_provider_response_to`

### T10 — Fork admission and security checks (ADR-0099 §2–4)

Add these fork tests. None calls a paid provider.

1. **Route class.**
   - A `custom-*` provider with `discovery_format: comfyui` maps to `PaidRoute("custom_media", …)`.
   - In `PRODUCTION_CANDIDATE` it is refused without a current qualification.
   - Location: `tests/unit/r2/host_hardening/test_paid_routes.py`, plus the qualification tests.
2. **Budget.** With empty prices, a ComfyUI generation reserves `MIN_RESERVATION` and reconciles to 0 (`lib/budget_guard.py` tests).
3. **Lane default.** A ComfyUI provider with no `*_max_workers` gets image 1 / video 1. Explicit values win.
4. **Downloads.**
   - Loopback and private `base_url` are allowed.
   - A link-local or metadata `base_url`, or a redirect hop to one, is refused on both `/view` and the probe.
5. **Credentials.** `{{api_key}}` outside `auth` is refused in a ComfyUI definition.
6. **Denylist.** `r2/contracts/provider_syntax.py` still denylists `comfyui`: the existing test passes unchanged.

### T11 — Frontend and docs

- `pnpm -C frontend check`: tsc, eslint, vitest.
- The i18n consistency test.
- `pnpm -C website check`.
- UI copy is short and clear. Darkroom kickers stay fixed English.

### T12 — Gates at the branch head

- `uv run ruff check . && uv run ruff format --check .`
- `uv run basedpyright --warnings`
- `uv run lint-imports`
- `uv run deptry lib server alembic scripts tests r2`
- `uv run python scripts/audit_tests.py --check`
- The union of the T1–T10 test paths, run with `-n 4 --dist loadfile`.
- `pnpm -C frontend check`
- `pnpm -C website check`

The full suite is skipped by standing instruction. Record that as a coverage limit.

### T13 — Gate 4: independent review

- Run a Codex review of `r2-v2/main..impl/r2-v2-03-comfyui` against ADR-0099 and its Amendment 1, the R1–R6 rules and the ledger.
- The stopping rule is amendment 12: model the whole change first, don't bundle peripheral packets, and don't open a new round for Low findings.
- On ACCEPTED:
  - write `docs/r2/evidence/R2_V2_03_IMPLEMENTATION_ACCEPTANCE.json`, bound to the head;
  - merge `--no-ff` into `r2-v2/main`;
  - do not push.

## Stop conditions

Stop and write a handoff in `docs/r2/evidence/` if any of these happen:
- An R5 hunk falls outside the allowed list.
- A donor hunk needs an intermediate upstream subsystem larger than a leaf module.
- A declarative no-regression test fails and the cause cannot be isolated to one hunk.

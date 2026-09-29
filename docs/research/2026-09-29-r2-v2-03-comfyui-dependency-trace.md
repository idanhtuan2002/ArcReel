# V2-03 ComfyUI backport: dependency trace at upstream 4b277b4c

Research note for the V2-03 gate-1 dependency trace. License is out of scope by sponsor decision.
Repository: this fork, worktree `r2-v2-main`, branch `r2-v2/main`. `upstream` = `ArcReel/ArcReel`,
pinned commit `4b277b4c` ("fix(市场): 官方服务接入与分享提交的健壮性修正"). Merge base with this
fork: `6ddedc775e7fe5f398b10081ab741985f7dceda7`. Nothing was checked out from upstream; all upstream
content below is read with `git show 4b277b4c:<path>` / `git ls-tree -r --name-only 4b277b4c` against
the `upstream` remote already present in this worktree's `.git`.

## Facts

### 1. Inventory of ComfyUI-specific files at 4b277b4c

Two passes, both bounded at 300s and completed without truncation:

- `git ls-tree -r --name-only 4b277b4c | grep -i comfy` → **64 files**, all ComfyUI-named
  (path contains "comfy"), 17,889 total lines. Breakdown:
  - Backend runtime (13 files): `lib/custom_provider/comfyui/{__init__,artifacts,capabilities,
    comfyui_backend,comfyui_client,comfyui_execution,comfyui_image_backend,failures,import_shapes,
    inference,inference_rules,inference_rules.schema.json,request_builder}.py` +
    `inference_rules.{image,video}.json`
  - Endpoint test (1): `lib/custom_provider/endpoint_test/comfyui.py`
  - Server router (1): `server/routers/comfyui_inference.py`
  - Market-core package (5): `packages/arcreel-market-core/src/arcreel_market_core/comfyui/
    {__init__,bindings,graph,validator,workflow}.py` + `schema.json`
  - Market-core tests (4): `packages/arcreel-market-core/tests/comfyui/test_comfyui_{bindings,
    definition_schema,definition_validator,graph}.py`
  - Frontend (9): `frontend/src/components/pages/settings/{CustomProviderForm.comfyui.test.tsx,
    endpoints/{ComfyuiBindingTable.tsx, ComfyuiEndpointDetail.tsx(+.test), ComfyuiEndpointTestSection.tsx(+.test),
    comfyui-bindings.ts(+.test), comfyui-import.ts}}`
  - Unit tests + fixtures (23): `tests/unit/lib/custom_provider/comfyui/*` (10 test files + 11 workflow
    JSON fixtures + `__init__.py`), `tests/unit/lib/custom_provider/test_endpoint_test_comfyui.py`,
    `tests/unit/server/routers/{test_comfyui_inference_api.py,test_custom_providers_comfyui.py}`
  - Docs (3): `docs/adr/0081-comfyui-endpoint-as-second-custom-endpoint-kind.md`,
    `docs/adr/0082-node-bindings-are-the-only-truth-of-comfyui-endpoint.md`,
    `website/docs/guide/comfyui.md` (+ its en i18n copy, counted above)
  - i18n: no `frontend/src/i18n/**/comfy*.ts` file — comfy-specific strings live inside the shared
    `dashboard.ts` locale files (see "content-hit" list below), not separate comfy locale files.

- `timeout 300 git grep -l -i comfy 4b277b4c` → **166 files** (completed, no timeout). Subtracting
  the 64 named files above leaves **102 files that mention "comfy" in content but are not
  ComfyUI-named** — these are the integration seams, not ComfyUI-owned code. Key ones, grouped:
  - **Kind-dispatch / endpoint-definition core** (new upstream infra, not comfy-owned):
    `packages/arcreel-market-core/src/arcreel_market_core/endpoint_definition/{__init__,kinds,
    media_type,validator}.py`, `definition_diagnostics.py`, `message_keys.py`,
    `video_backend_contract.py`, `auth_section.py`
  - **Backend runtime split**: `lib/backends/{artifact_download_guard,backend_runtime}.py`,
    `lib/config/resolver.py`, `lib/custom_provider/{capabilities,discovery_formats,
    endpoint_resolution,endpoints}.py`, `lib/custom_provider/endpoint_test/{__init__,kinds,modes,
    preview,trial_run}.py`
  - **Task-failure encoding** (touched by fe1e15e2): `lib/generation/{generation_result,
    generation_worker,media_generator,task_failure,task_failure_encoding}.py`
  - **DB/router glue**: `lib/db/models/custom_endpoint.py`, `lib/db/repositories/
    custom_provider_repo.py`, `server/routers/{custom_endpoints,custom_providers,
    endpoint_tests}.py`, `server/services/tasks/generation_tasks.py`
  - **Market submission**: `lib/market/submissions.py`,
    `packages/arcreel-market-core/src/arcreel_market_core/market/entry.py`
  - **Security**: `lib/backends/artifact_download_guard.py`, `docs/security/threat-model.md`
    (loopback/private-address allowance "such as ComfyUI or Ollama" — already known from the prior
    research note)
  - **Frontend generic endpoint UI**: `EndpointSelect.tsx`, `EndpointDetail.tsx`,
    `EndpointImportDialog.tsx`, `EndpointsSection.tsx`, `endpoint-definition-draft.ts`,
    `customProviderHelpers.ts`, `CustomProviderForm.tsx`, `CustomProviderDetail.tsx`,
    `useModelCapabilities.ts`, `provider-models.ts`, `endpoint-catalog-store.ts`, plus
    `types/{custom-endpoint,custom-provider,project}.ts` and the three `dashboard.ts` i18n files
    (en/vi/zh) — comfy strings are inline i18n keys inside the shared dashboard bundle, not a
    separate module.
  - **Docs**: `website/docs/guide/{market,providers}.md` (+ en i18n copies), `CONTEXT.md`,
    `CONTRIBUTING.md`, `CHANGELOG.md`, `README.md`/`README.en.md` (changelog-style mentions).

### 2. Commits that introduced/changed the 64 ComfyUI-named files

`git log --oneline 6ddedc77..4b277b4c -- <64 paths>` → **34 commits**, chronological (oldest first):

```
69967549 docs(comfyui): 登记 ComfyUI 端点与节点绑定术语并记录两份 ADR (#2544)
56cb567d feat(comfyui): ComfyUI 端点定义的 schema、校验与导入分流
6c0bb0c0 feat(comfyui): 实发 workflow 的构造
1cf11b02 feat(comfyui): 设置页可新建 ComfyUI 供应商并挂接 ComfyUI 端点
1012fe07 feat(comfyui): 导入 workflow 时认出节点绑定候选
98ee8ffb fix(comfyui): stage 1 并行票收敛与 AI review 九轮修复
d027b2e6 feat(comfyui): ComfyUI 视频 backend 主路径
5b45272e feat(comfyui): 设置页可逐项确认节点绑定并保存
e03491ee feat(comfyui): 视频 backend 健壮性
1ec7bd84 feat(comfyui): 视频能力与尺寸时长约束改由节点绑定推导
fe4bd3a1 feat(comfyui): 端点测试对 ComfyUI 端点给出预览请求与测试连接
fc3126b9 fix(comfyui): 收口五票之间的接缝与 AI 审查发现
9116977e fix(comfyui): 档位为空的三支提示语
ac308078 fix(comfyui): 重导入节点标题核对
62a55eab feat(comfyui): 图像通道
a1ba44db feat(comfyui): 设置页预览请求与测试连接
c8cac44f docs(comfyui): 文档站 workflow 接入指南
d15192b3 fix(comfyui): 收口 stage 3 接缝
e00e28b8 refactor: 按映射表把核心库与应用服务层搬入领域包        <- NOT comfy-specific, 1132 files
1a943710 refactor(architecture): 强制核心库与服务端分界          <- NOT comfy-specific, 48 files
d3d0c454 fix(agent): 自定义供应商导入 Agent 凭证改为服务端复制密钥 (#2599)
9d89cc84 refactor(backends): 拆分视频契约与运行支持              <- NOT comfy-specific, 107 files
fe1e15e2 refactor(generation): 执行器改由应用装配处注入            <- THE EXCLUDED COMMIT, 28 files
42b08c67 fix(comfyui): 产物类型提示改列扩展名 (#2618)
8faf1450 fix(security): 供应商探针与模型发现走出站目的地校验统一 (#2621)
a300b786 test(comfyui): 用例改用改名后的 encode_task_failure_message (#2625)
62456ef1 fix(comfyui): 产物容器白名单/上传约定对齐 (#2624)
301c8a38 fix(video): 端点固定时长参考视频，TTS 明示不支持 (#2623)
3ff6127f fix(视频): 续跑过期判定、内置供应商出站校验 (#2699)
ab714d98 feat(comfyui): 节点规则登记海螺 H3 首尾帧/参考图槽位 (#2664)
074d81ce refactor(市场): 独立安装市场校验工具
07d84da6 fix(市场): 子包代码指针改为可导航仓库路径
6516e5a5 docs(domain): 旁白交付方式改为项目配置 (#2777)
82850227 feat(市场): 支持分享声明式和 ComfyUI 端点到官方市场
```

18 of the 34 are pure `feat(comfyui)`/`fix(comfyui)`/`docs(comfyui)` commits building the feature
top to bottom (schema → request builder → video backend → bindings UI → image channel → endpoint
test → docs). Interleaved with those are 4 large non-comfy refactors (`e00e28b8`, `1a943710`,
`9d89cc84`, `fe1e15e2`) that happened to also touch one or more comfy-named files as a mechanical
side effect of a repo-wide move/rename, plus later `fix(comfyui)` commits landing *after*
`fe1e15e2` that depend on its renamed symbols.

### 3. `fe1e15e2`'s actual footprint on ComfyUI code

`git show --format="" --name-status fe1e15e2` touches 28 files; **exactly one** is comfy-named:
`tests/unit/lib/custom_provider/comfyui/test_comfyui_video_backend.py`. The diff is a single import
rename:

```diff
-from lib.generation.generation_worker import _encode_task_failure_message
+from lib.generation.task_failure_encoding import encode_task_failure_message
```

`fe1e15e2`'s commit message confirms scope: "生成 Worker 不再知道服务端的存在：任务执行器与续跑执行器
成为 GenerationWorker 构造器的必填参数，由 server/app.py 的 create_generation_worker 注入" (executor
and resume-executor become required constructor args, injected by `server/app.py`), and pulls
restart-recovery/resume/failure-encoding into new sibling modules under `lib/generation/`. **None of
this changes ComfyUI's runtime code** (`comfyui_backend.py`, `comfyui_client.py`,
`comfyui_execution.py`, `comfyui_image_backend.py`, `request_builder.py`, etc. — zero diff lines).
The only coupling is that `lib.custom_provider.comfyui.failures.ComfyuiError` gets encoded through
whatever function is named `encode_task_failure_message` at generation-execution time — a private,
already-existing str-encoding leaf utility, not the executor injection mechanism itself.

`9d89cc84` ("拆分视频契约与运行支持", 107 files, 9 comfy-named) is the commit that actually created
`lib/backends/backend_runtime.py` and moved video-backend contract types into
`arcreel_market_core.video_backend_contract`. `e00e28b8` (1132 files, 14 comfy-named) and `1a943710`
(48 files, 1 comfy-named) are the mass `lib/` → domain-package reorg and the core/server boundary
enforcement; their comfy touches are mechanical import-path fixups from the reorg, not new comfy
logic.

### 4. Imports of non-ComfyUI project symbols from the 19 core ComfyUI source files

Checked: `lib/custom_provider/comfyui/*.py` (13 files), `lib/custom_provider/endpoint_test/
comfyui.py`, `server/routers/comfyui_inference.py`, `packages/arcreel-market-core/src/
arcreel_market_core/comfyui/{__init__,bindings,graph,validator,workflow}.py`.

| Upstream symbol | Fork status at HEAD | Detail |
|---|---|---|
| `arcreel_market_core.*` (the whole package: `aspect_size`, `auth_section`, `definition_diagnostics`, `definition_schema_errors`, `endpoint_definition.kinds`, `validation_messages`, `video_backend_contract`, `comfyui.{bindings,graph,validator,workflow}`) | **Package does not exist.** `ls packages/` fails; no `arcreel_market_core` in `pyproject.toml`/`uv.lock`. | Upstream extracted this into an installable sub-package (`packages/arcreel-market-core/`) at commit `9d89cc84` and later. This fork's equivalent logic lives inline in `lib/` (flat) — e.g. `lib/aspect_size.py` exists with plain functions, but `resolution_to_short_edge` needs checking name-for-name; `lib/custom_provider/endpoint_definition/` exists but has **no `kinds.py`, no `media_type.py`, no `definition_diagnostics.py`, no `video_backend_contract` equivalent, no `auth_section.py`**. |
| `arcreel_market_core.endpoint_definition.kinds.{DECLARATIVE_KIND, COMFYUI_KIND}` | **Missing — no kind-dispatch layer at all.** | Fork's `lib/custom_provider/endpoint_definition/validator.py` is a single monolithic declarative validator with no `kind` branching (confirmed: no `"kind"` string appears in `validator.py`; `schema.json` requires a `"kind"` field but only as an opaque enum, not dispatched on). `docs/adr/0067` (present in fork, unchanged) explicitly reserved the `kind` slot for a second implementation form ("容器以 `kind` 字段为其预留槽位") but the fork never built the second branch. **This is the real prerequisite**: ADR-0081's whole point upstream is "ComfyUI endpoint = second `kind`"; that dispatch mechanism does not exist in this fork yet. |
| `lib.backends.artifact_download_guard.{artifact_http_client, ARTIFACT_MAX_BYTES_BY_MEDIA_TYPE, VIDEO_ARTIFACT_MAX_BYTES, buffered_error_response, stream_body_to_file}` | **Exists, different path.** `lib/artifact_download_guard.py` (flat, not under `lib/backends/`). | Needs a diff of exact exported names/signatures — not done line-by-line here due to time, but the module exists and is actively used by `r2/contracts` per the reuse research note ("Loopback and private addresses are allowed on purpose... such as ComfyUI or Ollama"). |
| `lib.backends.backend_runtime.{ProviderJobIdPersistenceMixin, should_retry_poll, poll_with_retry, notify_provider_response, notify_provider_response_to}` | **Mostly exists, different path; one symbol missing.** `lib/video_backends/base.py` has `ProviderJobIdPersistenceMixin` (line 110 vs upstream 135), `should_retry_poll` (365 vs 228), `poll_with_retry[T]` (572 vs 377, **identical signature**: `*, poll_fn, is_done, is_failed, max_wait`), and `notify_provider_response` (matching signature `(request, stage, body) -> None`). **`notify_provider_response_to` is genuinely new upstream** (not found anywhere in fork) — introduced by `9d89cc84` alongside the video/backend split. |
| `lib.backends.container_sniff.{CONTAINER_HEAD_BYTES, sniff_container}` | **Missing — new module.** Introduced by `62456ef1` (tagged `fix(comfyui)`, "产物容器白名单与上传约定对齐"). Self-contained ~45-line pure function (magic-byte MIME sniffing for PNG/JPEG/WebP/ISO-BMFF/WebM), zero further imports beyond stdlib `collections.abc.Mapping`. Real prerequisite but trivially portable. |
| `lib.backends.http_status_errors.{AmbiguousSubmitError, ArtifactDownloadError, ProviderRejectedError, provider_rejected_error, redacted_status_error}` | **Exists, different path.** `lib/http_status_errors.py` (flat). Names line up; not diffed symbol-by-symbol. |
| `lib.backends.image_backends.base.*` | **Exists, different path.** `lib/image_backends/base.py` (flat, not under `lib/backends/`). |
| `lib.infra.{api_errors, logging_utils, retry, validation_messages}` | **Exist, different path.** `lib/api_errors.py`, `lib/logging_utils.py`, `lib/retry.py`, `lib/validation_messages.py` (all flat). |
| `lib.prompts.prompt_utils.{append_avoid_text, split_avoid_lines}` | **Exists, different path.** `lib/prompt_utils.py` (flat). |
| `lib.config.resolver.{ImageBucketCapabilityError, VideoBucketCapabilityError}` | **Module exists** at the same path, `lib/config/resolver.py`. Whether these two exception classes exist inside it was not diffed line-by-line. |
| `server.i18n.Translator` | **Path does not exist in this fork.** `server/i18n.py` is present upstream (`git show 4b277b4c:server/i18n.py`, request-scoped `Accept-Language` → translator injection); the fork has no `server/i18n*` file at all (`find server -maxdepth 1 -iname "i18n*"` empty). Fork's i18n lives under `lib/i18n/` only; where/how request-scoped translator injection happens in routers needs a follow-up check — not resolved in this pass. |
| `lib.custom_provider.declarative_backend.DeclarativeRuntimeError` (referenced from `task_failure_encoding.py`, not comfy itself) | Exists in fork: `lib/custom_provider/declarative_backend.py`. |

### 5. Integration seams in this fork (task 5)

- **Custom-provider backend registration**: `lib/custom_provider/factory.py::create_custom_backend`
  looks up `ENDPOINT_REGISTRY` by `endpoint` key via `lib/custom_provider/endpoints.py::
  get_endpoint_spec`, then calls `spec.build_backend(provider, model_id)`. A ComfyUI provider would
  need: (a) `discovery_format == "comfyui"` handling in `lib/custom_provider/discovery.py` (currently
  branches only `"openai" | "google" | "anthropic"`, raises `ValueError` otherwise — a 4th branch,
  not touching the executor); (b) `EndpointSpec` entries whose `build_backend` returns a
  `ComfyuiVideoBackend`/`ComfyuiImageBackend` instead of a declarative-runtime-backed backend — this
  is exactly the kind-dispatch gap in item 4 above.
- **M7 execution attempts**: `lib/generation_worker.py` (flat, pre-`e00e28b8`/`fe1e15e2` shape) still
  builds its executor as a private module-level function (`_execute_task`, line 479) rather than
  receiving it via constructor injection. `CapacityTable`/`SlotTable` (lines 186/319) gate
  provider+media-type concurrency from `lib/capability_buckets.py`-style config; a ComfyUI provider
  slots into this the same way any other video/image provider does — no change to
  `GenerationWorker`'s public shape is implied by adding a provider, only by the (excluded) DI
  refactor.
- **`r2/host_hardening`** and **`r2/contracts/host_hardening.py`** exist in this fork (host-runtime
  hardening contracts referenced by ADR-0094, "V2 treats a pipeline run as a host runtime
  projection"). Not read in depth this pass; flagged as the place a self-hosted ComfyUI's local-GPU
  admission would plug into the V2 host-runtime model, per ADR-0094's framing.
- **Admission/budget ADRs**: `docs/adr/0091` (paid-route qualification, backport, gate evidence),
  `docs/adr/0093` (Agent per-connection budget in release mode — supersedes 0091 amendment item 5
  for the Agent route only), `docs/adr/0094` (pipeline run as host runtime projection; portfolio
  pause/capacity as admission filters). None of these three currently mention ComfyUI or GPU/local
  compute budgeting — per ADR-0081 upstream, ComfyUI has **no provider billing** ("没有供应商账单...
  记账层零改动"); it reuses the existing per-model price fields (0 if empty) and only *records*
  execution duration. The open question from the prior research note stands: how a self-hosted
  ComfyUI's GPU-time enters *this* fork's admission/budget model (0091/0093/0094 predate ComfyUI and
  are paid-route-shaped) is unresolved and belongs in the ADR gate, not this trace.
- **Capability registry**: `lib/capability_buckets.py` (fork, flat) and
  `r2/production_intelligence/capability_registry.py` (fork-specific, R2-only) both exist; upstream
  has no `r2/` tree at all (fork-only addition). A ComfyUI provider's capability declaration would
  need to flow through whichever of these the fork's other custom providers already use — not
  traced symbol-by-symbol this pass.
- **`provider_syntax` denylist**: `r2/contracts/provider_syntax.py` already lists `"comfyui"` in
  `_TOKEN_DENYLIST` (line 34, confirmed) — this fork-only contract predates the ComfyUI packet and
  already anticipated it; no change needed here.
- **Artifact download guard**: `lib/artifact_download_guard.py` (flat) already permits loopback/
  private addresses "such as ComfyUI or Ollama" per the threat model (from the prior research note);
  this is the fork's existing seam for self-hosted-provider network policy and looks pre-adapted for
  ComfyUI already.

## Inference

1. **`fe1e15e2` is cleanly separable from the ComfyUI change set.** Its only intersection with
   comfy-named code is one renamed import in one test file, swapping a private
   `generation_worker._encode_task_failure_message` for a public
   `task_failure_encoding.encode_task_failure_message`. The ComfyUI backend's actual production
   dependency is on *some* function that turns a `ComfyuiError` into a stored `error_message` string
   — that dependency can be satisfied by the fork's current (private, module-internal) equivalent in
   `lib/generation_worker.py` (`_encode_task_failure_message`, confirmed present at line 105) without
   pulling in any of `fe1e15e2`'s constructor-injection/restart-recovery/resume-module split.
2. **The bigger blocker is not `fe1e15e2` — it's that this fork predates three other upstream
   refactors** (`e00e28b8`, `1a943710`, `9d89cc84`) that reshaped `lib/` from a flat module tree into
   packages (`lib/generation/`, `lib/backends/`, `packages/arcreel-market-core/`) and split the
   endpoint-definition/video-contract layer out into an installable sub-package with a `kind`-based
   dispatch mechanism. None of those three commits are excluded by the V2-03 packet scope (only
   `fe1e15e2` is named), but literally importing upstream's ComfyUI files as-is would fail at import
   time against this fork's flat `lib/` layout regardless of `fe1e15e2` — every `lib.generation.*`,
   `lib.backends.*`, and `arcreel_market_core.*` import needs remapping.
3. **The real, load-bearing prerequisite is the kind-dispatch layer (ADR-0081/0082's core idea)**:
   this fork's `endpoint_definition` validator, schema, and endpoint-test framework only know one
   `kind` (`declarative`) and have no branch point for a second, Python-native kind. Upstream's
   `docs/adr/0067` (present in this fork unmodified) already reserved a `kind` slot for exactly this
   ("容器以 `kind` 字段为其预留槽位; 声明式收编的是本可整体表达的那部分，不与 plugin 互斥"), so
   building the dispatch is filling in a slot the fork's own architecture anticipated — it is new
   work, not a deviation from the fork's design, and it does not touch M7 execution-attempt
   authority.
4. **Two small, genuinely new upstream modules are true prerequisites** regardless of kind-dispatch:
   `lib/backends/container_sniff.py` (self-contained magic-byte sniffing, ~45 lines, zero further
   deps) and `notify_provider_response_to` (a `notify_provider_response` variant added in `9d89cc84`,
   not present in fork's `lib/video_backends/base.py`). Both are leaf additions, not architectural.
5. **Path remapping, not architectural conflict, is the dominant integration cost.** For most
   `lib.backends.*`/`lib.infra.*`/`lib.prompts.*` imports, the fork already has an equivalent module
   at a flat path with (where checked) matching function signatures (`poll_with_retry`,
   `should_retry_poll`, `notify_provider_response`, `ProviderJobIdPersistenceMixin`). A backport would
   rewrite ComfyUI's imports to point at the fork's flat paths rather than dragging in the upstream
   package reorg.

## Unknowns

- Exact signature diff for `lib.backends.artifact_download_guard` vs fork's `lib/artifact_download_guard.py`
  (`ARTIFACT_MAX_BYTES_BY_MEDIA_TYPE`, `VIDEO_ARTIFACT_MAX_BYTES`, `buffered_error_response`,
  `stream_body_to_file`) — module confirmed present, symbol-level diff not done.
  `lib.backends.http_status_errors` vs fork's `lib/http_status_errors.py` likewise not diffed
  symbol-by-symbol.
- Whether `lib/config/resolver.py` in this fork already defines `ImageBucketCapabilityError` /
  `VideoBucketCapabilityError` (module path matches; class-level diff not done).
- Where request-scoped translator injection (upstream's `server/i18n.py::Translator`) happens in this
  fork's routers, given `server/i18n.py` does not exist here. ComfyUI's `endpoint_test/comfyui.py`
  and `server/routers/comfyui_inference.py` both import `server.i18n.Translator` upstream; the fork's
  equivalent request-locale-to-translator wiring needs to be found before a backport plan can name
  the exact substitution.
- `lib.aspect_size.resolution_to_short_edge` (upstream aliases it `short_edge_of_resolution`) —
  confirmed the module exists in the fork at `lib/aspect_size.py`, function-level name/signature
  match not verified.
- `r2/host_hardening` and `r2/contracts/host_hardening.py` were located but not read in depth; how a
  self-hosted ComfyUI's execution attempt would flow through host hardening is not established.
- Whether `lib/capability_buckets.py` and `r2/production_intelligence/capability_registry.py` are the
  same registration surface other custom providers use today, or two different registries serving
  different purposes — not traced.
- No content search was run for `arcreel_market_core` version pin / whether upstream's
  `packages/arcreel-market-core` is published anywhere this fork could depend on versus vendoring the
  needed slice inline (Reuse-first would prefer vendoring the specific comfyui/endpoint_definition
  submodules into this fork's existing flat `lib/` layout rather than adopting the whole sub-package
  layout, but that is a design decision for the ADR gate, not this trace).

## Proposed backport boundary (for the ADR gate, not a decision)

**In scope for V2-03** (all 64 comfy-named files, adapted to this fork's flat `lib/` layout):
- `lib/custom_provider/comfyui/*` (13 files) — rewrite imports to flat `lib.*` paths; use fork's
  existing `_encode_task_failure_message` (or expose it as `lib.task_failure_encoding` if a clean
  public split is wanted, independently of `fe1e15e2`'s DI change) instead of importing from a
  `lib.generation.*` package that doesn't exist here.
- `lib/custom_provider/endpoint_test/comfyui.py`, `server/routers/comfyui_inference.py`.
- The `arcreel_market_core.comfyui.*` (bindings/graph/validator/workflow, ~5 files, pure functions,
  no framework deps beyond `jsonschema`) — vendor directly into
  `lib/custom_provider/comfyui/` or a new `lib/custom_provider/endpoint_definition/comfyui/` rather
  than creating a `packages/arcreel-market-core` sub-package this fork has no other use for yet.
- Tests and the 11 workflow fixtures, frontend components, docs (ADR 0081/0082, the guide).

**Prerequisite, non-comfy work** (must land first, own review, no executor authority change):
- Kind-dispatch in `lib/custom_provider/endpoint_definition/{validator.py,schema.json}` and
  `lib/custom_provider/endpoint_test/*` — fill the `kind` slot `docs/adr/0067` already reserved.
  This is the largest real prerequisite; it is new capability, not a deviation from `fe1e15e2`.
- `lib/backends/container_sniff.py` equivalent (trivial port).
- `notify_provider_response_to` equivalent in `lib/video_backends/base.py` (or wherever the fork
  keeps `notify_provider_response`).
- `discovery_format == "comfyui"` branch in `lib/custom_provider/discovery.py` (mechanical addition,
  raises today instead of silently misrouting).
- Resolve the `server.i18n.Translator` unknown above before writing router code.

**Explicitly excluded** (per the packet's own scope, confirmed separable by this trace):
- `fe1e15e2` itself — zero production comfy code depends on it; only one test import needs the
  fork's already-existing private equivalent instead of upstream's renamed public one.
- `e00e28b8`/`1a943710`'s package-reorg *as upstream did it* — the fork does not need to adopt
  `lib/generation/`, `lib/backends/`, or `packages/arcreel-market-core/` as directory structures; it
  only needs the *symbols* those reorgs exposed, reachable from wherever they already live flat.
- Any admission/budget/host-hardening redesign — ADR-0091/0093/0094 are untouched by this trace;
  ComfyUI's "no provider billing, record duration only" model (per ADR-0081) should compose with the
  fork's existing `CapacityTable`/`SlotTable` without new authority.

## Answer to "can the ComfyUI change set be separated from `fe1e15e2`?"

**Yes, and it already is, almost for free.** `fe1e15e2` touches exactly one comfy-named file (a
test), via one renamed import of a leaf string-encoding function. The 18 pure comfy commits (and the
5 comfy-tagged fix commits after `fe1e15e2`) do not depend on the executor-injection mechanism
`fe1e15e2` introduces. The minimal prerequisite non-comfy work this backport would drag in is **not**
`fe1e15e2` or its sibling architecture commits — it is (a) building the `kind`-dispatch layer in
`endpoint_definition`/`endpoint_test` that ADR-0081 relies on and that this fork's own `docs/adr/0067`
already reserved a slot for, and (b) two small new leaf modules (`container_sniff`,
`notify_provider_response_to`) plus a `discovery_format` branch. None of these touch
`lib/generation_worker.py`'s execution-attempt authority or M7.

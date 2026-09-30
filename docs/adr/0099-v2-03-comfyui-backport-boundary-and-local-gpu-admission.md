---
status: accepted
---

# V2-03 backports the upstream ComfyUI endpoint on this fork's flat layout, and admits local GPU work through the existing route, budget and capacity seams

V2-03 reuses upstream ArcReel's ComfyUI provider as a self-hosted image and video backend
(`R2_V2_03_COMFYUI_PACKET_OPENED_2026-09-29.md`). Gate 1 traced its dependencies at upstream
`4b277b4c` (`docs/research/2026-09-29-r2-v2-03-comfyui-dependency-trace.md`). Gate 2 decides the
backport boundary and the local-GPU budget and admission policy. The sponsor delegated the choice.

## Facts

- **Upstream design.** Upstream's ComfyUI design is ADR-0081 and ADR-0082 (upstream numbering):
  - one ComfyUI workflow plus its node bindings is a custom endpoint of `kind: comfyui`;
  - one ComfyUI server is a custom provider with `discovery_format: comfyui`;
  - the two bind to each other both ways;
  - there is no GPU pricing: existing price fields apply, and an empty price means 0;
  - execution time is recorded, not priced;
  - provider concurrency defaults to 1;
  - on cancel or timeout, a best-effort cancel is sent to ComfyUI.
- **Upstream code.**
  - 64 ComfyUI-named files make up about 17.9k lines; 34 commits touch them.
  - The executor re-architecture `fe1e15e2` touches exactly one of them: a renamed import in a test.
  - Three other upstream refactors reshaped `lib/` into packages: `e00e28b8`, `1a943710` and `9d89cc84`. This fork keeps the flat layout. Most ComfyUI imports have a flat equivalent here with a matching signature.
- **What this fork lacks.** The fork is missing:
  - the `kind` dispatch in `lib/custom_provider/endpoint_definition` (the schema enum is `["declarative"]` only; `docs/adr/0067` reserved the slot);
  - `container_sniff`;
  - `notify_provider_response_to`;
  - a `comfyui` branch in `lib/custom_provider/discovery.py`;
  - the `arcreel_market_core` package.
- **Translator.** Upstream routers take `server.i18n.Translator`; this fork's routers take `lib.i18n.Translator`.
- **Admission.** In `PRODUCTION_CANDIDATE`, a custom provider (id `custom-*`) is the paid route class `custom_media`. It needs a current qualification (ADR-0091), and every call reserves budget of at least `MIN_RESERVATION` (0.01), reconciled to the settled cost (`lib/budget_guard.py`). In `DEV`, neither applies.
- **Concurrency.** `GenerationWorker`'s `CapacityTable` limits concurrency per provider and media type. Custom providers carry `image_max_workers` and `video_max_workers`.
- **Outbound destinations.**
  - `lib/artifact_download_guard.py` refuses link-local and cloud-metadata destinations. It deliberately allows loopback and private addresses for self-hosted services "such as ComfyUI or Ollama".
  - A custom provider's `base_url` is set by an authenticated administrator. That is the explicit operator enablement the threat model's controlled-outbound invariant asks for.
- **Existing denylist.** `r2/contracts/provider_syntax.py` already denylists the token `comfyui`, so ComfyUI syntax cannot enter R2 contracts.

## Decision

### 1. Backport boundary

**In.** The ComfyUI feature set of upstream `4b277b4c`, rewritten onto this fork's flat layout:
- the runtime `lib/custom_provider/comfyui/*`, the ComfyUI endpoint test, and the inference-rules router;
- the frontend binding, detail and test-connection components;
- the tests and the 11 workflow fixtures;
- the operator guide.

The pure `arcreel_market_core.comfyui` modules (`bindings`, `graph`, `validator`, `workflow` and its
schema) are vendored into `lib/custom_provider/comfyui/definition/`. No sub-package is created.
Imports are remapped to the fork's flat modules, and routers take `lib.i18n.Translator`.

**In, as separate prerequisite steps before the ComfyUI code.** Each has its own tests:
1. `kind` dispatch in the endpoint definition schema and validator, and in the endpoint-test framework (fills ADR-0067's slot). A declarative definition validates and behaves exactly as today.
2. The leaf modules `container_sniff` (magic-byte sniffing) and `notify_provider_response_to`.
3. The `comfyui` branch of `discovery.py`. Connectivity is `GET /system_stats`, which returns `comfyui_version`. Model discovery returns a structured "not applicable".
4. Failure encoding through the fork's existing task-failure encoder. `fe1e15e2`'s rename is not adopted.

**Out.**
- `fe1e15e2` and the three package-reorg commits, as structure.
- The market sharing of ComfyUI endpoints (`82850227` and the market UI).
- Hosted ComfyUI services, which stay declarative endpoints.
- WebSocket progress.
- Any change to M7 execution authority. A ComfyUI generation is an ordinary generation task on `GenerationWorker`; there is no new execution path, lane or state.

### 2. Budget: no GPU pricing; the paid-route machinery applies unchanged

A ComfyUI provider is a custom provider, so it is the `custom_media` route class, with nothing
special:
- In `PRODUCTION_CANDIDATE` it needs a qualification like any other custom route, and each call makes the standard budget reservation.
- Its estimate comes from the model row's price fields. With empty prices the estimate is 0, so the call holds `MIN_RESERVATION` and reconciles to 0.
- No GPU-time price, budget scope or ledger kind is added. Execution time is recorded as today.

Exempting zero-priced routes from qualification or budget would add a second admission policy. That
policy would need its own review, and it is not needed: the reservation is 0.01 and it is released at
reconciliation.

### 3. Admission: one job per GPU by default, through the existing capacity table

- A provider with `discovery_format: comfyui` defaults to concurrency 1 on each of its lanes, image and video. The operator can raise `image_max_workers` and `video_max_workers` like any custom provider.
- ComfyUI's own queue serializes the prompts the server accepts.
- The endpoint's configurable poll timeout bounds the wait.
- When ArcReel abandons a generation (user cancel or timeout), the backend sends ComfyUI a best-effort cancel. That is upstream behaviour, and it lives inside the backend. The local task state machine is unchanged; a failed remote cancel is only logged.
- There is no per-GPU scheduler across lanes. A server that should run one job at a time across image and video is configured with one lane.

### 4. Security

- ComfyUI requests go to the administrator-configured `base_url`.
- Artifacts come from `/view` on that host through the existing artifact download guard. The guard applies its per-media size caps and its link-local and metadata refusal on every hop.
- Uploads go only to the same host.
- The endpoint's credential template follows the declarative `auth` section rules: `{{api_key}}` may appear only there.

## Consequences

- Gate 3 writes an executable plan: first the four prerequisite steps, then the ComfyUI runtime, router, frontend and docs. Every step carries targeted tests. The backport's own review follows under the amendment 12 stopping rule.
- The upstream ADR texts are imported as reference under this fork's numbering. They are not re-decided.
- If a later need arises for GPU cost accounting or a cross-lane GPU scheduler, that is a new decision. It is not part of V2-03.

## Rejected

- **Adopting upstream's package layout** (`lib/generation/`, `lib/backends/`, `packages/arcreel-market-core/`). It is a repo-wide move with no V2-03 benefit.
- **Exempting ComfyUI from qualification and budget in release mode.** This would create a second admission policy for one provider kind.
- **A GPU-time price.** Upstream deliberately does not price user-owned hardware, and no evaluation requires it.
- **ComfyUI as an orchestrator or as the Canvas.** This was already excluded by the packet.

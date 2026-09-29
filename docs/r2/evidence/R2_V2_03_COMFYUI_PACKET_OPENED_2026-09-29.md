# V2-03: ComfyUI provider backport, packet opened

**Sponsor decision (2026-09-29):** open V2-03 as a separate V2 packet. It reuses the upstream ArcReel ComfyUI provider as a self-hosted image and video execution backend (the "Visual Asset Factory" of R-A5.4). The research is in `docs/research/2026-09-29-r2-comfyui-reuse.md`.

## Scope

- **In:** the ComfyUI custom-provider protocol, workflow import and node bindings, image and video endpoints, endpoint preview and test connection, and their tests and docs. They are taken from upstream at a pinned commit.
- **Out:**
  - the ComfyUI editor as the Creative Canvas (M8-B stays on React Flow);
  - ComfyUI as an orchestrator (M7 remains the execution authority);
  - the upstream executor re-architecture (`fe1e15e2`) and any change that re-opens M7.

## Gates, in order

1. **Research: dependency trace.** At pinned upstream `4b277b4c`, list every ComfyUI file and every non-ComfyUI symbol it imports, and whether this fork has it with a compatible signature. Separate the ComfyUI change set from the executor re-architecture. Map it to this fork's seams: the custom-provider runtime, endpoint test, artifact download guard, provider-syntax denylist, M7 execution attempts, admission and budget, and the capability registry.
2. **ADR.** Decide the backport boundary and the local-GPU budget and admission policy before any code.
3. **Plan, then a bounded backport** with its own tests and evidence.
4. **An independent review** on its own track under the amendment 12 stopping rule.

V2-03 does not gate M8-B, and M8-B does not gate V2-03.

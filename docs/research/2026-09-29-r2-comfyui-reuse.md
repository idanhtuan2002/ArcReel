# Should ArcReel reuse ComfyUI, and where?

Research note for the sponsor question of 2026-09-29, under the reuse-first rule. It proposes an option and decides nothing. License is out of scope by sponsor decision.

## Facts

### Inside this repository (r2-v2/main)

| Source | What it says about ComfyUI |
|---|---|
| `docs/research/r2-origin/03_ARCHITECTURE.md` | Places ComfyUI in the **Execution layer**, next to DC-Media, H3, Seedance, Veo and Kling. Its reuse table lists "Visual execution engine: reuse **ComfyUI** (external)". The flow diagrams show ComfyUI producing images before the video models. |
| `docs/research/r2-origin/02_SYSTEM_REQUIREMENTS.md` R-A5.4 | "ComfyUI = Visual Asset Factory": character sheets, expressions, costumes, location plates, props, keyframes, storyboards, control images, masks, depth, pose. Image and asset generation usually comes **before** video generation. |
| `docs/research/r2-origin/01_RESEARCH_SYNTHESIS.md` | ComfyUI is a tier-B "specialized high-value" donor. It records that the DramaClaw DC-Media gateway has a ComfyUI adapter. |
| `docs/r2/R2_01_FROZEN_ARCHITECTURE.md` | Lists "ComfyUI/local services" among the capability sources. |
| `docs/security/threat-model.md`, `lib/artifact_download_guard.py` | Loopback and private addresses are allowed on purpose, because self-hosted providers "such as ComfyUI or Ollama" run there. |
| `r2/contracts/provider_syntax.py` | `comfyui` is on the provider-syntax denylist. Brand names must not appear in provider-neutral semantic contracts; only the PromptCompiler translates to provider syntax. |
| `docs/research/2026-09-28-r2-v1-06-paid-routes-and-e1-remediation.md`, `docs/r2/evidence/R2_V1_06_UPSTREAM_BACKPORT_2026-09-28.md` | The upstream ComfyUI backends are "the largest change" ahead of this fork. They were **deferred** as "not V1 needs" (ADR-0089, option U2 rejected). Upstream also re-architected the executor (`fe1e15e2`), which overlaps the M7-A/C domain. |

### Upstream ArcReel (`upstream/main` 4b277b4c, 2026-09-29; 311 commits ahead of the merge base 6ddedc77)

- **A complete ComfyUI provider.** It spans about 64 files and about 17,900 added lines:
  - `lib/custom_provider/comfyui/request_builder.py` and `lib/custom_provider/endpoint_test/comfyui.py`;
  - `server/routers/comfyui_inference.py`;
  - the market-core `comfyui/{bindings,graph,schema.json,validator,workflow}.py`;
  - image and video backend tests, and 11 workflow fixtures (Flux Kontext, Wan 2.1/2.2/VACE, LTXV, MiniMax H3 i2v/ref2v, Qwen Image Edit, SDXL, SDXL+SVD);
  - the guide `website/docs/guide/comfyui.md`.
- **How it works** (from that guide):
  - The operator creates a `comfyui` provider (a Base URL and an optional API key) and imports an **API-format** workflow as an image or video endpoint. One workflow is one model row.
  - ArcReel infers **node bindings**: positive and negative prompt, first frame, last frame and reference images, width and height, frames, fps (read-only), seed, and the output node. An operator can pin a node with the title `ARCREEL:<key>`, or through the ComfyUI-Deploy, comfy-pack and Serving-Toolkit input nodes.
  - All traffic is HTTP: `/upload/image`, `/prompt`, `/history` and download. No shared filesystem is needed.
  - A settings page previews the request and runs a real test connection.
  - The record keeps the seed that actually took effect and the fingerprint of the submitted workflow.

### ComfyUI itself (primary sources)

- Server API ([docs.comfy.org, server routes](https://docs.comfy.org/development/comfyui-server/comms_routes)):
  - `POST /prompt` queues a workflow; `GET /history/{prompt_id}` returns results;
  - `/upload/image` and `/upload/mask` take inputs; `/ws` streams progress; `/interrupt` stops a run;
  - `/queue`, `/object_info`, `/models` and `/system_stats` describe the server.
- Its frontend ([Comfy-Org/ComfyUI_frontend](https://github.com/Comfy-Org/ComfyUI_frontend)) is a workflow editor built on **LiteGraph**, not React Flow. Its README does not describe embedding it as a component.
- Large graphs of 100+ nodes lag in its editor (see the M8-B canvas-scale note).

## Inference

1. **Reuse ComfyUI as an execution backend.** It is a self-hosted image and video generation provider: the "Visual Asset Factory" of R-A5.4. This matches every internal architecture document and what upstream built.
2. **Do not use it as the Creative Canvas (M8-B).**
   - ComfyUI's graph is an *execution DAG*: model loaders, samplers, VAE. M8-B's Canvas is a *creative storyboard graph*: beats, frames, groups, bookmarks and promotion.
   - M8-B is bound to DramaClaw parity on React Flow (the M8-B plan and the sponsor-approved envelope).
   - Embedding the LiteGraph editor would bring in a second graph model and a second history, and nothing would say which graph is authoritative. That conflicts with M8-A's exploration authority.
3. **Do not use it as the orchestrator.** M7 execution attempts, admission, the paid-route gate and budget are the execution authority. ComfyUI is called *by* an execution attempt, one workflow submission at a time, like any other provider.
4. **Reuse upstream's integration rather than build one.** About 17,900 lines of tested code, fixtures and docs already exist.
   - A backport is not a cherry-pick. The upstream range also changes the executor (`fe1e15e2`), which re-opens M7.
   - The ComfyUI files must be separated from that range, and their dependencies checked against this fork's custom-provider, endpoint-test, artifact-download-guard and M7 execution seams.

## Unknowns

- Whether the upstream ComfyUI provider depends on the upstream executor re-architecture or on market-core packages this fork does not have. That needs a dependency trace at a pinned upstream commit.
- Whether the DramaClaw DC-Media ComfyUI adapter recorded in the research synthesis exists at the pinned donor commit `b299bfd9`. No file name matches, and a content search timed out. Upstream ArcReel's version is the better-evidenced donor either way.
- The hosting and GPU plan for a real ComfyUI server: whether it runs locally or on a remote GPU, and on which models. It has no provider cost but uses GPU time. How it enters the budget and admission model is also open.

## Options

| | Where | Effort | Effect on M8 |
|---|---|---|---|
| **1. A V2 provider packet (recommended)** | A new V2 packet, for example "V2-03 ComfyUI provider backport". First a research-and-ADR step: dependency trace, seam mapping to M7 execution attempts and the capability registry, and the budget and admission policy for local GPU. Then a bounded backport with its own review track under the amendment 12 stopping rule. | Medium; reuses upstream | None. It runs separately from M8-B |
| 2. Defer | Keep ComfyUI out until a GPU host exists | None | None |
| 3. ComfyUI editor as the Canvas | Rejected (inference 2) | High | It would replace the accepted M8-B plan and conflict with M8-A authority |

# M8-B Canvas scale: measured and estimated inputs for the production graph envelope

**Purpose.** The M8-B plan requires a sponsor-approved production graph envelope (execution contract `packet_inputs.M8-B`) and forbids the executor from choosing it. This note gathers the evidence the sponsor needs. It recommends no envelope.

## Facts (measured or read from source)

| Source | Finding |
|---|---|
| ArcReel projects on this machine | Only one real project exists, `~/arcreel-v1-trial/data/du-an-01-649c62c1`, and it has no content: 0 episodes, 0 characters, 0 scenes, 0 props. **There is no real ArcReel usage to measure.** No test fixture holds a populated project. |
| ArcReel code | Canvas does not exist yet. The M8 contract (`r2/contracts/advanced_creative.py`) sets no cap on nodes, edges or payload, so the envelope sets them. |
| ArcReel code | `DEFAULT_PLANNING_MAX_EPISODES = 20` (per planning batch). The ad default target duration is 60 s. The number of shots in an episode follows `episode_target_duration`, divided by the model's `supported_durations`. One backend (agnes) accepts clips of 1–18 s, and the pricing bucket defaults to 6 s. |
| DramaClaw donor `b299bfd9` | 18 node types: upload, image edit/gen, export image, beat context, text annotation, group, storyboard split/gen, video, audio, video story/compose, script, pano360, 3D world, skill, style. |
| DramaClaw donor | `MAX_HISTORY_STEPS = 50`. No node, edge or payload limit is declared. |
| DramaClaw donor, `canvasLod.ts` | The only recorded performance measurement: **69 nodes at zoom 0.1 on one machine.** Baseline 62.3 fps, p90 frame 26.6 ms (1 dropped frame in 10). With the LOD (effects off during gestures, video replaced below zoom 0.35) 74.5 fps, p90 14.1 ms, against a 13.3 ms budget line. `onlyRenderVisibleElements` is on outside low-detail zoom. Zoom range is 0.1–8. |
| DramaClaw donor tests | The largest collection in the Canvas tests has 150 items, and it is an asset list, not a graph. No large-graph test exists. |

## Inference (structural estimate for one episode Canvas; not measured)

A donor-style Canvas for one ArcReel episode holds about 3–4 nodes per video unit (beat/script, storyboard image, video, sometimes audio), plus the episode's asset nodes and groups.

| Profile | Episode length / clip length | Units | Unit nodes | Asset + group nodes | Nodes | Edges (≈1.2–1.8 × nodes) |
|---|---|---|---|---|---|---|
| Small | 60 s / 8 s | ~8 | ~28 | ~12 | ~40 | ~50–70 |
| Typical | 90–120 s / 6 s | 15–20 | ~60–70 | ~25 | ~90–100 | ~110–180 |
| Large | 180 s / 5 s | ~36 | ~130 | ~45 | ~180 | ~220–320 |
| Multi-episode Canvas (5 large episodes) | — | ~180 | ~650 | ~100 | ~750 | ~900–1350 |

The donor's measured working Canvas (69 nodes) falls between Small and Typical.

## Unknowns

- Whether a Canvas covers one episode, a batch of episodes or a whole project. The spec does not say; this choice changes the envelope by about 5–10×.
- The reference hardware and browser for the budget. The donor's 13.3 ms line implies a 75 Hz display; a 60 Hz display gives 16.7 ms.
- Payload size per node (script text, image references). The M8-A server revision has no size cap.
- Real operator behaviour: there is no populated project.

## What the sponsor needs to decide (the envelope fields, spec §7)

1. The **top rung of the graph-size ladder**: maximum nodes and edges in one Canvas, and the Canvas scope (one episode or more).
2. The **operation mix** to benchmark: add, edit, drag, connect, group, undo/redo, and their proportions.
3. The **reference environment**: browser, build and hardware.
4. The **pass thresholds**: p50/p95 interaction latency (or frame time), peak memory and allowed bundle delta.

The ladder's lower rungs, repetitions and the protocol file are then frozen by M8-B Task B1 before any result exists.

## External references (checked 2026-09-29)

| Source | Fact |
|---|---|
| DramaClaw donor `frontend/src/api/canvas.ts` | Canvases are scoped: `FreezoneCanvasScope = "default" \| "episode" \| "beat" \| "asset"`. A project has many canvases, one per episode, beat or asset, not one project-wide graph. |
| React Flow docs ([performance](https://reactflow.dev/learn/advanced-use/performance)) | Guidance only (memoize, avoid depending on the `nodes` array, hide collapsed subtrees, simplify CSS). No node-count threshold or benchmark. |
| React Flow [stress example](https://reactflow.dev/examples/nodes/stress) | The default grid is 10 × 10: 100 nodes and 90 edges. |
| RealFlow benchmark ([repo](https://github.com/olbboy/realflow)) | 10,000 nodes, Chromium software rendering. React Flow default: 4 pan fps, 239 MB heap, 10,000 DOM nodes. React Flow with `onlyRenderVisibleElements`: 9 fps, 34 MB, 49 DOM nodes. RealFlow (spatial-hash culling): 43 fps, 18 MB. |
| xyflow discussion [#4975](https://github.com/xyflow/xyflow/discussions/4975) | Users report slow updates at 80+ nodes when state is held outside React Flow. Local state fixed it. |
| ComfyUI ([troubleshooting](https://docs.comfy.org/troubleshooting/overview), issues [#3913](https://github.com/comfyanonymous/ComfyUI/issues/3913), [#6513](https://github.com/Comfy-Org/ComfyUI/issues/6513)) | Reports say 100+ node workflows stress the browser renderer. The advice is to split workflows, collapse groups and turn off live previews. |
| n8n community ([thread](https://community.n8n.io/t/performance-issues-with-large-workflow-including-many-http-nodes-need-help/167668)) | Editor lag is reported at about 50 heavy nodes. No documented node limit. |
| tldraw ([performance docs](https://tldraw.dev/sdk-features/performance)) | `maxShapesPerPage` defaults to 4,000 (raisable to 10,000). Viewport culling is built in. `p95FrameTime` is its interaction metric. Zoom is debounced above 500 shapes. Its shapes are much lighter than media nodes. |
| LibTV / liblib (the donor's reference) ([overview](https://www.uied.cn/114196.html)) | An infinite canvas with 5 base node types; it generates 9/25-panel storyboard grids in one step. The donor measured it at 74.6 fps and p90 14.1 ms, the same as the donor after LOD. No published node limit. |
| web.dev [INP](https://web.dev/articles/inp) | Good ≤ 200 ms, poor > 500 ms, at the 75th percentile. |
| web.dev [RAIL](https://web.dev/articles/rail) | Respond to input within 100 ms (handle it within 50 ms); produce each animation frame in ≤ 10 ms (16 ms is the hard limit at 60 Hz). |

**What they imply:**

- Media-heavy node canvases (ComfyUI, n8n, the donor) start to struggle at about 50–100 nodes unless culling and LOD are on.
- Lightweight-shape canvases (tldraw) stay smooth into the thousands.
- The donor already needed LOD to stay within budget at 69 nodes.
- Scoping one Canvas to an episode, as the donor does, keeps graphs in the tens to low hundreds.

## Options for the sponsor

| | A: conservative | **B: recommended** | C: ambitious |
|---|---|---|---|
| Canvas scope | one episode | one episode (donor precedent) | one episode, or a batch |
| Graph-size ladder (nodes) | 25 / 50 / 100 / **200** | 25 / 50 / 100 / 200 / **400** | 50 / 100 / 250 / 500 / **1000** |
| Top rung edges | 300 | **600** | 1500 |
| Headroom over the Large episode estimate (~180 nodes) | 1.1× | **2.2×** | 5.5× |
| Frame time while panning, zooming or dragging, at zoom 0.5–1 | p95 ≤ 16.7 ms at every rung | p95 ≤ 16.7 ms up to 200 nodes; p95 ≤ 33 ms at the top rung | p95 ≤ 33 ms at every rung |
| Discrete operations (add, connect, delete, group, undo/redo, edit commit) | p95 ≤ 100 ms | p95 ≤ 100 ms | p95 ≤ 200 ms |
| Open the top-rung Canvas until interactive | ≤ 1.5 s | ≤ 2 s | ≤ 3 s |
| Canvas-attributable JS heap at the top rung | ≤ 80 MB | ≤ 120 MB | ≤ 250 MB |
| Bundle | Canvas lazy-loaded; initial app bundle +0; Canvas chunk ≤ 250 KB gzip | same | same |

In every option:

- **Reference environment:** the Playwright-pinned Chromium on a production build. The machine identity (CPU, RAM, GPU, display Hz) is recorded. A second, low-end profile runs with 4× CPU throttling and must meet the discrete-operation threshold at the 100-node rung.
- **Operation mix:** pan/zoom 35%, node drag 20%, node text edit 15%, add node 10%, connect edge 10%, group/ungroup 5%, undo/redo 5%.
- **Repetitions:** at least 30 per operation per rung, over 3 cold runs.
- **Failure:** per spec §7, a failure blocks the React Flow adapter, not the M8-A exploration authority.

Option B covers the largest estimated episode with about 2× headroom. It keeps the high-frequency interaction inside one 60 Hz frame at realistic sizes, and it allows 30 fps only at the stress rung, which is where the external evidence shows media-node canvases degrade.

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

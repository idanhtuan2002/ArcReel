# R2 shot output custody: where an M8-C generated shot becomes a master

Basis: `r2-v2/main` at `0be0726f`. Decision recorded in [ADR-0104](../adr/0104-r2-shot-output-enters-gate-c-episode-video-slot.md).

## Facts (source-checked)

- **Packet 2 output.** `server/services/r2_shot_worker.py` writes `r2/shot_tasks/<task>/output.mp4` and returns it in the task result. No candidate, version or master is registered.
- **Gate C is episode-video only.**
  - `server/routers/gates.py` `final_cut_approval` stages a file under `production/` into `GoldenAHostIntegration`, keyed `ArtifactKey.episode_video(req.episode, req.target_ref)`.
  - A non-composite request is a shot approval with contract type `ShotSpec`.
  - `server/services/master_authority.py:191` states that no host route approves another kind.
- **Take shots already use that slot.**
  - `scripts/r2/v1_operator.py` approves each Take shot (`<scene>-TAKE-1`) with `episode=1, target_ref=shot.id`.
  - The V1 golden restore drills record `source_master_refs` such as `s-scene-1-TAKE-1:CAND-s-scene-1-TAKE-1-V1:1`.
  - `GoldenAComposer` reads shot masters by the same key.
- **Spatial sources need episode-video masters.** `server/services/spatial_source.py:318` refuses a frame parent that is not an episode-video artifact.
- **Target IDs fit Gate C's rule.** The registry target IDs (`scene-1-TAKE-1`) pass `validate_m3_target_ref`, which requires one safe filename component with no `:` or `/`.
- **No episode in Take.** `TakeDirectorAdapter` and the target registry carry no episode.
- **Provenance limits.**
  - `RenderedCutAsset.tool` and `FinalCutRenderedAssetRequest.tool` are `Literal["remotion", "ffmpeg"]`.
  - `stage_candidate` stamps `provider_execution_ref="local:ffmpeg:<fingerprint>"`.
  - `ProductionMethod.GENERATED_VIDEO` exists, but no Gate C caller uses it.
- **Roadmap.** M6 (`R2_06`) requires the flow `TakeDirector → ShotSpec → production → ApprovedShotMasters → final drama`. R2-M2 forbids a second artifact authority.

## Inferences

- Option B (a new R2 shot artifact kind) would need a new Gate C route, master projection, resolver arm, spatial-source arm and composition reader. It duplicates an authority that already handles these shots.
- Option C (candidates only) blocks final assembly and spatial reuse of M8-C shots, so it can only be an interim state.
- Option A needs a provenance extension, because Gate C today cannot truthfully describe a provider-generated file, and a server-derived staging step, so that task evidence rather than client-declared metadata defines the candidate.

## Unknowns

- How a multi-episode R2 screenplay should map to episodes. This is out of scope; current R2 projects use episode 1.
- Whether an ArcReel script segment ID can equal a Take target ID in the same project. ADR-0104 makes the staging step refuse a slot owned by another contract instead of resolving the collision.
- External donors were not compared. The question is internal authority placement, and no donor in `docs/research` defines Gate C or master custody.

## Options

| Option | Reuse | New authority | Reaches final cut |
|---|---|---|---|
| A. Episode-video slot via Gate C (chosen) | Gate C, master head, manifest, composition, spatial source | none; adds a provenance arm and staging step | yes |
| B. New R2 shot artifact kind | low | second route, projection and resolver | only after parallel work |
| C. Candidates only | n/a | none | no |

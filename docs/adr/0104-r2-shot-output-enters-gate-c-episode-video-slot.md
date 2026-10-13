---
status: accepted
---

# An R2 Take shot output becomes a Gate C shot candidate in the episode-video slot of its target

**Sponsor delegation (2026-10-13):** the sponsor asked the agent to research the option set and choose the best decision ("nghien cuu, chon quyet dinh tot nhat"). This ADR records that choice. It fixes the custody mapping; the implementation packet still needs its own spec, tests and review before use.

M8-C packet 2 generates a Take-derived shot through `r2_shot_generation_v1` and leaves the file at `r2/shot_tasks/<task>/output.mp4`. Nothing registers it as a candidate or lets a human approve it. Three options were open: map the shot into an existing Gate C episode-video slot, add an R2 shot artifact kind with its own Gate C route, or keep R2 outputs as candidates only.

## Decision

1. **Slot.** The output of an R2 shot task for registry target `target_id` (a Take shot such as `scene-1-TAKE-1`) is a candidate of `ArtifactKey.episode_video(1, target_id)`. Episode `1` is the fixed episode of a single-screenplay R2 project, as in the V1 operator path; Take derivation carries no episode.
2. **Approval stays Gate C.** Only the existing human Gate C approval makes the candidate an approved master, through the same `serialized_artifacts` lock, `promote_staged` database head (ADR-0096), projection and receipt. Generation success never selects a master, and nothing auto-approves.
3. **Server-derived candidate, no client provenance.** A new server-internal staging step takes only the R2 task identity. Under the slot lock it:
   - re-verifies the stored task evidence, the succeeded M7 attempt and the output bytes;
   - copies the output under `production/`;
   - registers a version with `method=GENERATED_VIDEO`, execution fingerprint = the task's `host_request_digest`, provider execution ref = the M7 execution/provider job, and cost from the ledger.

   The Gate C request for this candidate names the staged R2 candidate; it does not send `produced` file metadata, a content fingerprint or dependencies. The server derives them from the task's target registry version and binding snapshot.
4. **Slot ownership.** The staging step refuses a slot whose manifest entry already belongs to a non-R2 contract, or to another R2 target, instead of overwriting it.
5. **Consumers unchanged.** Spatial frame sources, composite finals and `verify_masters` keep reading episode-video masters. An approved R2 shot master is therefore usable by them with no new authority.

## Why this option

- **Reuse of a live authority.** Gate C, the master database head, the manifest projection and the export are episode-video-specific (`master_authority.py`: "Gate C masters are episode videos; no host route approves another kind"). Golden A, the M6 acceptance and the V1 operator path already approve Take shot IDs at `episode_video(1, shot.id)`.
- **Downstream consistency.** The M8-C spatial source requires its parent frames to come from episode-video masters (`spatial_source.py`), and final composition reads shot masters by the same key. A separate artifact kind would need a second approval route, projection, master resolver and frame-source arm — a second artifact authority, which R2-M2 forbids.
- **Roadmap.** M6 requires `ApprovedShotMasters` before final assembly. Keeping outputs as candidates only would leave the M8-C path unable to reach a final cut.

## Consequences

- `FinalCutRenderedAssetRequest.tool` and `RenderedCutAsset.tool` accept only `remotion`/`ffmpeg`, and `GoldenAHostIntegration.stage_candidate` stamps `provider_execution_ref="local:ffmpeg:..."`. The packet must add a typed provider-generated provenance arm rather than relabel a provider output as FFmpeg. Existing request digests and stored versions stay byte-identical.
- The route body for an R2 shot approval is a public contract change and needs review before use.
- Multi-episode R2 projects are out of scope. A screenplay that maps to several episodes needs a later decision on the episode component.
- Not decided here: regenerating a shot while an approved master exists keeps the master (R2-M2 rule); candidate retention and cleanup of `r2/shot_tasks` follow the existing version retention.

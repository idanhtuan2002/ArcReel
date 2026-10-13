# M8-C packet 4: R2 shot output custody through Gate C

**Basis:**
- [ADR-0104](../../adr/0104-r2-shot-output-enters-gate-c-episode-video-slot.md), with the decision delegated by the sponsor on 2026-10-13.
- The [research note](../../research/2026-10-13-r2-m8c-shot-output-custody.md).
- Packet 2 (shot worker) and packet 3 (promotion).

## Facts established before deciding

- **The worker records no output digest.**
  - The M7 attempt for an R2 shot records `ACCEPTED` at submit.
  - After the worker returns, `GenerationQueue.mark_task_succeeded` mirrors a `SUCCEEDED` observation whose `evidence_digest` hashes `legacy-mirror:<task>:SUCCEEDED`, not the output bytes.
  - Nothing durable therefore binds the downloaded file to the attempt.
- **A precedent exists.** `SpatialExecutionService._mark_succeeded` applies its own `SUCCEEDED` observation, with `evidence_digest` equal to the response byte digest, in the transaction that stages its evidence. The mirror then becomes a no-op, because it skips terminal attempts.
- **Observations are durable.** `provider_observations` stores `observation_id`, `kind` and `evidence_digest` append-only. No migration is needed.
- **Staging re-checks the bytes.** `GoldenAHostIntegration.stage_candidate` copies `produced.path` into the version store and re-checks `produced.sha256`, so the bytes the approval saw are the bytes promoted.
- **Gate C is mostly reusable.**
  - The Gate C core (stage → `promote_staged` under `serialized_artifacts` → `project_if_current` → `FinalCutReceipt`) depends only on the request's target, episode, semantic fields, produced asset, approval record and request digest.
  - `RenderedCutAsset.tool` is `Literal["remotion", "ffmpeg"]`, and `stage_candidate` stamps `provider_execution_ref="local:ffmpeg:..."`.

## Decisions

1. **The worker seals the output.**
   - After a successful download, both `execute_r2_shot_task` and `resume_r2_shot_task` hash the output file.
   - In one transaction they apply a `SUCCEEDED` observation with `observation_id="<execution_id>:output"` and `evidence_digest="sha256:<hex of output bytes>"` to the task's attempt.
   - The attempt must be the task's attempt 1, carry the task's `host_request_digest`, and be non-terminal or already sealed with the same digest.
   - A different sealed digest refuses. The mirror then finds a terminal attempt and does nothing.
2. **Provenance arm.**
   - `RenderedCutAsset.tool` gains `"provider"`, and the dataclass gains an optional `provider_execution_ref`.
   - `stage_candidate` uses that ref when set, and the existing `local:ffmpeg:` form otherwise.
   - `FinalCutRenderedAssetRequest` (the public body) is unchanged, so existing request digests stay byte-identical.
3. **Shared Gate C core.** The body of `final_cut_approval` after request validation moves into `_approve_cut(...)`, with no behaviour change. Both routes call it.
4. **R2 route.** The new route is `POST /projects/{project_name}/gates/r2-shots/{target_id}`, with body `{task_id, approval_record}` and `CurrentUser` authentication. The server:
   - Loads the task. It must be `r2_shot_generation_v1`, `succeeded`, and belong to the caller's user and project, and its evidence must verify against its profile with `target_id` matching the path.
   - Loads attempt 1. It must be `SUCCEEDED`, carry the evidence's `host_request_digest`, and have the `<execution_id>:output` observation. The file `r2/shot_tasks/<task>/output.mp4` must hash to that observation's digest.
   - Requires the current binding snapshot digest and target registry version to equal the evidence. A stale output is refused with 409, and the caller regenerates.
   - Requires the slot `episode_video(1, target_id)` to be absent or to already hold `ShotSpec` metadata for this `target_id`. Otherwise it refuses with 409 `slot_owned`.
   - Derives the semantic fields:
     - `content_basis` and `schema_version` from the current `ShotSpecV2`;
     - `contract_version` = the target registry version;
     - one dependency `r2-binding-snapshot:<target_id>`, version = registry version, fingerprint = the binding snapshot digest;
     - `content_fingerprint` = `compute_content_fingerprint(shot, deps)`.
   - Derives the produced asset:
     - `method=GENERATED_VIDEO`, `tool="provider"`, `tool_version` = execution profile ref;
     - `execution_fingerprint` = `host_request_digest`;
     - `provider_execution_ref="m7:<execution_id>"`;
     - cost and wall time from the ledger call bound to the execution.

   It then calls `_approve_cut` with episode 1 and returns the same body as Gate C.
5. **Not here.**
   - Frontend UI.
   - Multi-episode mapping.
   - Back-filling outputs generated before this packet. Those have no sealed digest and are refused, so the operator regenerates.
   - The binding currentness check runs before the slot lock, not under it. A later binding change marks dependants through the normal stale path rather than blocking the approval.

## Slices and tests

- **4a. Worker seal.**
  - The success test asserts a `SUCCEEDED` attempt whose output observation digest equals the file's.
  - The resume test asserts the same.
  - A second seal with different bytes refuses.
- **4b. Provenance arm and Gate C core extraction.** The existing Gate C tests (`test_gates_export` and the other `gates` router tests) pass unchanged.
- **4c. R2 route, tested through the app:**
  - happy path: master at `episode_video(1, target)`, receipt, `GENERATED_VIDEO` version, provider execution ref;
  - exact replay;
  - tampered output file;
  - foreign or unsucceeded task;
  - unsealed attempt;
  - stale binding;
  - slot owned by a non-R2 entry;
  - wrong target.

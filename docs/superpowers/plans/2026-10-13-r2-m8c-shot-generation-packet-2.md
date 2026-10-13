# M8-C packet 2: one reachable shot generation entrypoint that consumes the spatial snapshot

## Basis

- ADR-0102, decision 4.
- Spec `2026-09-30-r2-m8c-binding-authority-design.md`, section "Read and consumer protocol". The route, task, admission and fingerprint fields come from there.
- Research:
  - `2026-10-03-r2-m8c-first-video-route-comparison.md`: route selection, prompt rewrite, M4 identity gap;
  - `2026-09-30-r2-m8c-m7-submit-boundary.md`;
  - `2026-10-03-r2-m8c-runtime-submit-projection.md`.
- Packet 1 (`1b5c08a6`): typed set, snapshot read, fingerprint v2, prompt consumer.

## Facts that shape the slices

- **No M7 change is needed for preplanning.** `AttemptSubmitter.submit` reuses an existing `(task_id, attempt 1)` row: it takes the stored `execution_id` and `created_at` and requires an exact digest and route replay. `ExecutionAttemptRepository.plan` is idempotent. An admission transaction can therefore stage the `PLANNED` row with the exact host request, and the worker continues from it.
- **DashScope never sends `prompt_extend`,** and the official API defaults it to `true`. The first profile must pin `false` in the captured payload.
- **The M4 decision hash omits `positive_prompt`.** The R2 identity therefore binds the full compiled-request and host-request digests.

## First execution profile (fixture contract, not a paid authorization)

`r2-wan27-r2v-two-view@1` maps to:

| Field | Value |
|---|---|
| provider | `dashscope` |
| model | `wan2.7-r2v-2026-06-12` |
| endpoint | `video-synthesis` |
| adapter | `host-video-v1` |
| capability | `dashscope-video-synthesis@host-video-v1` |
| duration | 5 s |
| resolution | `720P` |
| watermark | `false` |
| seed | none |
| `prompt_extend` | `false` |

Inputs are exactly two reference images: `Image 1` is the front (MASTER) frame and `Image 2` is the reverse (REVERSE) frame.

Admission refuses before queueing:
- `silent`, `narration` or `dialogue` controls;
- identity locks;
- extra media;
- a non-5 s target;
- a prompt over the route limit.

## Slices (each committed with its tests)

- **2a. Profile and prompt projection (pure).**
  - `R2ExecutionProfileV1` and the profile registry.
  - `admit_shot_for_profile`, which returns refusal reason codes.
  - `project_spatial_prompt`, a deterministic Wan prompt:
    - the shot's subject, composition, camera and timing;
    - the `Image 1`/`Image 2` role line;
    - one clause per constraint;
    - no INFERRED or GAP clause.
  - A same-fixture test where mutating one clause changes the prompt digest.
- **2b. Captured provider payload.**
  - A typed `prompt_extend` request option on the DashScope backend, emitted only when set, so legacy payloads are byte-identical.
  - A builder that constructs the exact payload once from pinned frame bytes and returns it with its digest.
- **2c. Identity contracts.**
  - The `R2ShotGenerationTaskV1` payload, with the spec's field list.
  - The submit fingerprint, domain `r2.m8.spatial.submit.v1`, computed after the host request digest.
  - The `r2_shot_generation_v1` queue task type.
- **2d. Route.**
  - `POST /projects/{p}/r2/shots/{target_id}/generate`, taking `(command_id, expected_target_registry_version, expected_binding_snapshot_digest, execution_profile_ref)`.
  - It resolves the current snapshot, runs admission, compiles, captures and persists immutable task evidence.
  - An exact replay returns the same task; a changed body conflicts.
- **2e. Worker.**
  - Re-resolve and byte-compare the evidence at claim.
  - `admit_and_plan_spatial_attempt` locks admission, target, binding, pair, and source masters/frames in the shared order, rechecks currentness and stages the M7 `PLANNED` row in one commit.
  - The submit runs through `AttemptSubmitter` with the captured payload.
- **2f. Integration.** A route-to-M7-submit test with a fake DashScope at the provider boundary. Stale snapshot, changed frame bytes and spatial-only mutation must each fail before submit.

## Not in this packet

- Typed promotion (packet 3).
- A live provider call.
- Qualification of this route.
- The ADR-0103 operator activation.

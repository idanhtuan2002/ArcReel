# M8-C C2: server-owned spatial execution and revision append

**Status:** design accepted for implementation by sponsor delegation on 2026-10-13
(see `docs/r2/evidence/R2_M8C_COMPLETION_PATH_DECISION_2026-10-13.md`). It closes
the C2 part of Gate C. It does not cover promotion: `PRODUCTION_BINDING` previews
and promotions keep failing with `m8_promotion_target_unavailable` (ADR-0095,
contract amendment 2).

## Sources

- **M8 spec §8.** Spatial calls are bounded M7 executions. Each one keeps the raw
  response digest, the model/route fingerprint, the prompt/schema version, the
  source media digests and the normalizer version. A malformed response, a missing
  source, a provider failure or a normalization mismatch produces no revision.
- **M8 spec §12, Gate C.**
- **Research:**
  - `docs/research/2026-09-30-r2-m8c-spatial-append-boundary.md`
  - `docs/research/2026-10-04-r2-m8c-spatial-completion-evidence.md`, which proposes
    the DB sidecar; the vector is `tests/fixtures/r2/m8c_spatial_completion_evidence_vector.json`
- **Frame source.** The frame receipt slice from commits `229a22ba..fab08ab5`
  provides:
  - `server/services/spatial_source.py` (`FrameDerivationService`);
  - `server/services/spatial_frame_reader.py`, a current receipt reader that
    returns verified bytes.
- **M7.** `r2/host_hardening/host_submit.py`'s `AttemptSubmitter.submit(task_id,
  api_call_id, route, request, submit)` is provider-agnostic. Video is the only
  current caller. `lib/video_backends/execution_adapter.py` provides
  `terminal_submit_receipt` for synchronous providers.
- **Model call.** `lib/text_backends/base.py` `TextGenerationRequest` already
  carries `images` and `response_schema`.
- **Donor.** DramaClaw `b299bfd9`, `scene_spatial_contract.py`:
  - `run()` builds one MASTER|REVERSE sheet, calls `build_prompt(scene_name,
    overlap_analysis)`, makes one vision call, then calls `parse_json` and
    normalizes.
  - Overlap analysis is an optional, externally produced file. When it is
    absent, the donor uses `None`.

## Decisions

1. **Entry point.** An internal `SpatialExecutionService.execute(command)` takes
   these inputs:
   - user and project scope;
   - `command_id`;
   - `candidate_id`;
   - `expected_head` (CAS on the M8 candidate head);
   - `scene_name`;
   - the MASTER and REVERSE frame receipt IDs.

   No client field is copied into the candidate. The service derives `execution_id`,
   the source refs, source digests and spans, and the prompt. The generic append
   route keeps rejecting `SPATIAL`, as C1 already does. No public route is added in
   C2; one route can be added later behind the same service.
2. **Sources.** Both frames are read through the existing current frame receipt
   reader as verified PNG bytes. The two receipts must be distinct and have the
   roles MASTER and REVERSE. A missing, stale or corrupt source denies before any
   provider call.
3. **Execution.**
   - **Route.** One M7 attempt per command:
     - `task_id = "m8c-spatial:" + sha256(scope, command_id)`;
     - adapter version `host-spatial-v1`;
     - a new route inventory family whose capability profile ref is
       `<provider>-spatial-vision@host-spatial-v1`;
     - `require_submit_route` / `require_enabled_capability` still gate the
       route.
   - **Request.** `ProviderRequest.payload` binds the prompt version and digest,
     the response schema version, and the ordered frame receipt IDs and digests.
     The image bytes themselves are not part of the payload. The M7
     `request_digest` therefore binds the exact inputs.
   - **Submit.** The submit callable calls the text backend with both images and
     returns `terminal_submit_receipt(raw_bytes)`.
   - **First route and tests.** The route uses the Gemini text backend, which
     already supports image input and response schemas. Gate C tests replace only
     the provider transport (the repository boundary). No live paid call is
     part of Gate C.
4. **Overlap analysis.** C2 passes `overlap_analysis=None`, matching the donor
   when its file is absent. The evidence body records `overlap_response: null`,
   and the vector gains that case. A producer of overlap analysis is a later
   packet.
5. **Evidence sidecar.** Migration `8c8c4a0e0001` adds `spatial_execution_evidence`:
   - **Key:** `(user_id, project_name, execution_id)`, unique.
   - **Columns:** the receipt digest; the canonical body from the vector domain
     `r2.m8.spatial.execution.evidence.v1`; the raw response bytes, capped at
     256 KiB; the candidate ID and revision. There is no overlap bytes column.
   - **References:** a composite `RESTRICT` FK to `execution_attempts`; the
     scoped frame receipt rows; and a scoped one-to-one link to the M8 revision.
   - **Reads** rehash the raw bytes and the body.
6. **One transaction.** After the attempt reports `SUCCEEDED`, the service
   performs these steps:
   - re-read the attempt and require it to be `SUCCEEDED`, with the same request
     digest;
   - re-verify both frame receipts;
   - `json.loads` the raw response, then validate it and run
     `normalize_spatial_candidate`;
   - set `SpatialPayload.execution_id` to the execution ID;
   - stage the evidence row, the M8 revision (through the existing
     `ExplorationStore.append_revision` CAS) and the command receipt;
   - commit once.

   Any failure rolls back everything, so there is no revision without evidence and
   no evidence without a revision.
7. **Replay and conflict.**
   - **Exact replay.** Same command and same body: the stored evidence and
     revision are returned without a provider call.
   - **Same command, different body:** `CommandConflictError`.
   - **Attempt already crossed submit, no evidence row.** The crash fell between
     the provider result and the commit. A synchronous call has no poll, so the
     command fails closed with a typed unavailable error and creates no revision.
     The caller issues a new command. This may cost one extra provider call; it
     never creates a fact.
8. **No-fact and no-direct-write proof.**
   - A `GAP` stays `GAP`.
   - The service holds no master writer, `ProductionBinding` writer or promotion
     path. An import-contract test pins this.
   - Previewing or promoting a completed spatial candidate still returns
     `m8_promotion_target_unavailable` with no rows.

## Tests (Gate C corpus)

**Pure (unit):**
- normalization fixtures: the C1 suite, already present;
- the evidence vector including the `overlap_response: null` case;
- prompt version and digest pinned against the donor `build_prompt` output.

**Service (SQLite and real PostgreSQL), each showing zero new revisions and
evidence rows unless noted:**
- success: the evidence, revision and command receipt are created together;
- exact replay: no second provider call;
- changed-body conflict;
- malformed JSON;
- schema-invalid JSON;
- partial response (missing walls);
- normalization error (a visible item without a span);
- provider failure observation;
- ambiguous or unknown submit;
- stale source (the frame parent advances) before submit, and again between the
  provider result and the commit;
- crash between the provider result and the commit (the injected storage failure
  rolls back);
- candidate head CAS conflict.

**PostgreSQL concurrency:** two concurrent identical commands produce one revision
and one provider call. The loser either replays the winner or receives the typed
in-progress error.

**Boundary:**
- the generic route still rejects `SPATIAL`;
- promotion of the completed candidate is refused without writes;
- the lint-imports contract still holds.

## Unknowns carried forward

- The live provider and model, and its capability profile evidence, for a real
  run. Gate C does not need them.
- An overlap-analysis producer.
- A public route and its UI.

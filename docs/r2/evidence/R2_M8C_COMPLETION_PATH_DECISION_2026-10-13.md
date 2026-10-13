# M8-C completion path decision — 2026-10-13

**Status:** sequencing decision, delegated by the sponsor ("làm tất cả các bước thích hợp để nhanh chóng hoàn thành phần M8-C"; research first, reuse first). It reorders work on accepted contracts. It does not accept any new authority.

## Facts (accepted sources)

- The M8 spec (§8, §12 Gate C, §13) and the plan `docs/superpowers/plans/2026-09-13-r2-m8c-spatial-candidates.md` define M8-C as three tasks:
  - **C1:** normalization;
  - **C2:** server-owned bounded execution, then revision append;
  - **C3:** parity seal.
- Gate C requires pinned fixtures; a malformed, partial and model-failure corpus; deterministic normalization; and no-fact/no-direct-write proof.
- ADR-0095 (accepted) and `R2_M8_EXECUTION_CONTRACT_AMENDMENT_2_2026-09-29.json` limit the missing ProductionBinding authority to `M8_REQUIRED_EVIDENCE_MISSING` **for the promotion step only**. A `PRODUCTION_BINDING` preview or promotion keeps failing closed with `m8_promotion_target_unavailable`.
- ADR-0102 (binding authority) and ADR-0103 (Showrunner grants and review custody) are **proposed**. The branch `impl/r2-m8c-frame-receipts` builds on them: about 247 commits on 774952b2, latest `227d6824`. It covers frame receipts, the target registry, pair decisions, Governance grants, the checkpoint archive and the startup attestor.
- Two research notes state what C2 needs: `docs/research/2026-09-30-r2-m8c-spatial-append-boundary.md` (commit `366c9496`) and `docs/research/2026-10-04-r2-m8c-spatial-completion-evidence.md`. Both exist only on `impl/r2-m8c-frame-receipts`, and step (1) brings them over:
  - (a) MASTER/REVERSE frame derivation receipts;
  - (b) a bounded M7 execution that retains the exact raw model response;
  - (c) a spatial execution evidence receipt, with a proposed DB sidecar and the vector fixture `tests/fixtures/r2/m8c_spatial_completion_evidence_vector.json`.
- Current code: M7 `AttemptSubmitter` is wired only to the media/video paths (`lib/video_backends/execution_adapter.py`, `lib/media_generator.py`). `lib/text_backends` calls bypass M7.
- C1 is committed as `75ef822c` on `impl/r2-m8c-spatial-candidates`.
  - Donor parity covers 4 PARITY cases and 1 IMPROVED case, plus the IMPROVED correction `visible_object_requires_source_span`.
  - Selection results: 104 passed, 1 skipped.
  - Static gates passed.

## Decision

1. **M8-C is done when Gate C closes through C1–C3** on `impl/r2-m8c-spatial-candidates`, integrated into `r2-v2/main`. SpatialCandidate promotion is not part of this exit. It stays fail-closed under amendment 2.
2. **The frame-receipts/Governance branch becomes the separate "M8-C promotion prerequisite" packet** (ADR-0102/0103). Work on it pauses at `227d6824`; its handoff `R2_M8C_FRAME_CUSTODY_HANDOFF.md` stays the resume point. Its host custody, attestor and READY gates do not block Gate C.
3. **Reuse for C2:**
   - Bring only the frame derivation receipt slice from that branch: contracts, migration, repository, service and reader, from the early commits `229a22ba..b75fc3ae` plus the reader review fixes. These commits went through several completed Codex review rounds. Before reuse, verify their dependencies on the cherry-picked base and rerun their tests on PostgreSQL.
   - Base the C2 evidence receipt on the existing proposed sidecar design and its vector fixture.
   - Wrap the vision-model call with M7 `AttemptSubmitter` following the `lib/video_backends/execution_adapter.py` pattern. Do not add a parallel execution store.
4. **Order:** (1) frame-receipt slice → (2) a short C2 design citing the research above → (3) C2 with TDD on real PostgreSQL → (4) C3 parity evidence `R2_M8_C_SPATIAL_PARITY.json` → (5) exact-HEAD review → (6) integration and acceptance record.
5. **Review:** the sponsor chose the reviewer: Claude self-review, with no external Codex transmission. The acceptance record must state this limit.

## Unknowns

- Whether the frame-receipt slice cherry-picks cleanly without the target registry or the M7 caller-session lock changes made later.
- The vision provider and model for the first spatial execution, and whether the existing M7 request/route digests fit a text/vision request without schema changes.
- Effort: C2 is expected to take several sessions.

## Progress checkpoint — 2026-10-13 (same session)

Branch `impl/r2-m8c-spatial-candidates` was rebased onto `r2-v2/main` `0ac1a565`; the pre-rebase head is kept at `backup/r2-m8c-c1-pre-rebase-20261013`. Commits, oldest first:

| Step | Commit(s) | What | Evidence |
|---|---|---|---|
| C1 | `75ef822c` → rebased | Spatial normalization port | 4 PARITY, 1 IMPROVED, plus the IMPROVED span correction |
| 1 | 17 commits cherry-picked with `-x` from `229a22ba..fab08ab5`; then `9dbf73af`, `fe5da851` | Frame receipt slice, C2 research and vectors, the M8B fixture format fix | 157 passed on PostgreSQL 18; 154 passed and 3 skipped on SQLite |
| 2 | `1f7f7684` | C2 design `docs/superpowers/specs/2026-10-13-r2-m8c-c2-spatial-execution-design.md` | — |
| 3 | `0aef0dee`, `a0e5d1ae` | Prompt and parse, evidence contract, migration `8c8c4a0e0001`, `SpatialExecutionService`, `host-spatial-v1` route | 819 passed on PostgreSQL 18 (affected selection, before the rollback test); the C2 file and the evidence migration then 15 passed on PostgreSQL; repository static gates pass |

Design corrections found while implementing step 3:

- The donor prompt forbids image coordinates, but C1 requires spans. The R2 prompt keeps the donor's coordinate contract and rules and asks for the R2 schema.
- M7 forbids `SUBMITTING → SUCCEEDED`. The submit records `ACCEPTED`; the `SUCCEEDED` observation commits in the same transaction as the evidence and the revision.
- The spatial route stays out of the frozen `PAID_ASYNC_SUBMIT_FAMILIES`, whose ADR-0091 evidence is recorded. It lives in a separate `SPATIAL_SUBMIT_FAMILIES` tuple.

Remaining before acceptance:

- **C3:** the parity seal `R2_M8_C_SPATIAL_PARITY.json`, run against the donor at `~/.cache/r2-donors/dramaclaw`.
- **Review:** the exact-HEAD self-review recorded in the acceptance file.
- **Integration:** merge into `r2-v2/main`.
- **Full gate:** one full backend suite on the final HEAD.

No live provider call was made; Gate C does not need one.

The disposable containers were removed.

## C4: public route (decided 2026-10-13, after merge `dbf64003`)

The sponsor asked for a public route before M8-C is closed, overriding C2 spec decision 1 ("no public route"). Research facts:

- No spatial service is wired to the app. That includes `FrameDerivationService`, so a client could not create the frame receipts an execution needs. C4 therefore exposes both steps.
- The existing M8 API is `server/routers/advanced_creative.py`, the fixed ADR-0097 exploration surface. It maps `M8Error` codes to i18n keys in `lib/i18n/{en,zh,vi}/errors.py`.
- Text calls go through `TextGenerator.create(task_type, project)`. Its `Ledger` records usage. `VISION_REQUIRED_TASKS` fails loud when the configured model cannot see images (ADR-0051).
- The only registered spatial route is `gemini` / `gemini-generate` / `host-spatial-v1`. `GeminiVideoBackend` records its submitted base URL as the AI Studio URL or `vertex://{project}/global`.

Decisions:

1. A separate router `server/routers/spatial.py`, registered like the exploration router (session user plus project-migration guard). It does not extend the fixed ADR-0097 surface. Endpoints:
   - `POST /projects/{project}/m8/spatial/frames` derives one frame and returns the receipt id and digest.
   - `POST /projects/{project}/m8/spatial/executions` runs one spatial execution and returns `CandidateHead`.
2. A new `TextTaskType.SPATIAL_ANALYSIS`, in the SIMPLE tier and vision-required. The router builds a `TextGenerator` for it, so usage is recorded in the ledger. The resolved provider must be `gemini`; any other provider returns 503 `m8_spatial_unavailable` before a provider call. `GeminiTextBackend` gains a `submitted_base_url`, mirroring the video backend.
3. The vision call is a FastAPI dependency. Tests replace it through `app.dependency_overrides`, so no provider call is made.
4. R3 is fixed at the route: `scene_name` is trimmed and must be 1–120 characters.
5. The episode lineage is resolved before the provider call, so a bad episode never costs a call.
6. Error mapping:
   - `M8Error` keeps its existing keys;
   - `SpatialExecutionUnavailableError` returns 503 `m8_spatial_unavailable`;
   - `FrameSourceConflictError` returns 409 `m8_spatial_source_conflict`;
   - a frame request `ValueError` returns 422 `m8_spatial_request_invalid`.

   All three new keys are added in en, zh and vi.

Limits:
- Usage is recorded but not bound to the M7 `execution_id` (`usage_binder=None`), because the ledger call opens inside the provider call.
- No frontend UI.
- The profile stays `UNQUALIFIED`, so release mode still refuses the route.
- Verification: the targeted route tests, the affected selection, and static gates. Per the sponsor, there is no full suite or separate review round.

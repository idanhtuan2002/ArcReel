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

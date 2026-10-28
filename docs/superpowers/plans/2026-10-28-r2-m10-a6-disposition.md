# M10 A6 Human Disposition Implementation Plan

> Execute serially with TDD. Spec: [2026-10-28-r2-m10-a6-disposition-design.md](../specs/2026-10-28-r2-m10-a6-disposition-design.md).

- [ ] Task 1: pure rules `r2/quality/dispositions.py` (PASS/WAIVE/REWORK admissibility, waiver coverage, TTL, readiness) with RED unit tests.
- [ ] Task 2: models, migration after `57f67bae0cb4`, `QualityDispositionRepository` (authorization record/load, receipt replay, append disposition/outbox, head CAS) with migration/repository tests.
- [ ] Task 3: `DispositionCustodian` + `DispositionService` + `quality_readiness`; refactor A5 validity to run in the caller transaction; PostgreSQL integration tests incl. races and crash cuts.
- [ ] Task 4: gates, independent review, adjudication, `R2_M10_A6_CANDIDATE.json`, checkpoint.

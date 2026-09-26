# R2 M7 H6: `ApiCall.output_path` production-use audit

Date: 2026-09-26

Checkout: `feat/r2-m7e-v1-lineage` at
`38a01b6e4d67c9d56be21f2ce66769a244cb9150`.

Status: source research only. This note does not decide the H6 inventory,
backup, restore, or file-authority policy.

## Question and method

This bounded audit asks where the persisted `api_calls.output_path` column is
written or read by first-party production source, and whether a discovered
consumer opens it as a file or treats it as the current-media authority. It
does **not** concern generic backend request/result fields also named
`output_path`.

The graph project available for discovery was
`home-anhtuan-content-production-os-m7`, generation
`2026-09-18T10:57:40Z`, rooted at a different M7 worktree. Its relevant
metadata was stale for `lib/db/models/api_call.py`,
`lib/db/repositories/usage_repo.py`, `lib/ledger.py`, and
`lib/media_generator.py`; current-worktree source was therefore read directly.
Coverage reported only excluded `__pycache__` subtrees for the queried
`lib/db/repositories`, `server/routers`, and `server/services` scopes. This is
best-effort coverage, not a completeness proof.

Direct source searches covered Python production files under `lib/` and
`server/`, plus TypeScript/TSX under `frontend/src/`, for `ApiCall.output_path`,
`row.output_path`, ledger output-path arguments, and the usage-call response
path. Tests were deliberately excluded from the findings below. A parent
follow-up searched persisted-field access patterns in `r2/` and `scripts/`:
none was found in `r2/`, while the one-time legacy SQLite-to-ORM migration
copies `row.get("output_path")` into `ApiCall` without opening that path
(`scripts/migrate_sqlite_to_orm.py:156-176`). This migration is an additional
historical write path, not a normal runtime media reader.

## Confirmed writes

1. `ApiCall.output_path` is a nullable text column (`lib/db/models/api_call.py:14-30`).
   The normal runtime persistence write is `UsageRepository.finish_call()`: it
   accepts an optional `output_path` argument and includes it in the SQLAlchemy
   `update(ApiCall).values(...)` call (`lib/db/repositories/usage_repo.py:394-442`).
2. `Ledger.record()` accepts that optional value but does not persist it at
   start. On a successful context-manager exit it passes the value to
   `_finish_success()` (`lib/ledger.py:98-150`), which invokes `finish_call()`
   with it (`lib/ledger.py:217-221`). Failed, direct-cost, and resume-finalize
   paths shown here call `finish_call()`/`finalize_pending_by_call_id()` without
   an output path (`lib/ledger.py:156-162,190-211,223-236`).
3. The observed first-party media-generation callers pass the normal intended
   output location as a string for image, audio, and video respectively
   (`lib/media_generator.py:614-637,730-750,995-1019`). The backend request may
   instead receive a staging path (for example, image request construction at
   `lib/media_generator.py:633-640` and audio request construction at
   `:741-750`), so the persisted value is not established by this evidence as
   the exact file a backend wrote at every intermediate step.

## Confirmed reads and effects

| Consumer | Observed use | File/current-media behavior |
| --- | --- | --- |
| `UsageRepository._row_to_dict()` → `get_calls()` → `/usage/calls` | Serializes `row.output_path` into usage-call history, then returns those items through the route (`lib/db/repositories/usage_repo.py:134-165,670-708`; `server/routers/usage.py:56-80`). | It is response data; these functions do not open the value as a filesystem path. |
| Frontend usage drawer | `UsageCall` models the returned nullable string; the drawer fetches `/usage/calls`, splits it on `/` to render a basename, and uses the full string only as a tooltip (`frontend/src/stores/usage-store.ts:21-40`; `frontend/src/api.ts:2813-2828`; `frontend/src/components/layout/UsageDrawer.tsx:77-100,233-269,482-486`). | No link, media request, `File`/`Path` construction, or filesystem operation was found in this display path. |
| `get_project_image_costs_by_asset_type()` | Selects and groups successful project-level image rows by `ApiCall.output_path`, then `_classify_asset_output_path()` lowercases/splits the string to derive an accounting bucket (`lib/db/repositories/usage_repo.py:116-131,743-775`). `CostEstimationService` consumes only that aggregate (`server/services/cost_estimation.py:674-691`). | String-prefix classification only; no file open or current-media lookup. |
| Budget cost evidence | `BudgetReservationService` obtains a serialized call row and reads its cost and currency (`server/services/budget_reservation_service.py:241-257`). | The returned row contains `output_path`, but this consumer does not access it. |

## Bounded conclusion

Within the checked first-party runtime source, every confirmed persisted
`ApiCall.output_path` write is ledger settlement metadata, and every confirmed
read is usage-history serialization/display or accounting classification. No
checked consumer opens the persisted value as a file, resolves it into a media
artifact, or uses it as the current-media authority. The actual current/staged
media operations observed in `MediaGenerator` use that method's local
`Path` values and formal-version commit flow, not a value read back from
`ApiCall` (`lib/media_generator.py:981-1019,1101-1119`).

This is evidence about present checked call sites, not a policy determination
that a historical value may be discarded, copied, or ignored. A database dump
would still preserve the column's stored value as data. Whether an H6 recovery
inventory should classify any such value as a required file remains an
unresolved authority decision.

## Limits

- The code graph was from a different worktree and has stale metadata for
  material files; direct source, rather than graph absence, supports the
  findings.
- The negative claim is bounded to the searched first-party source trees and
  exact repository version above. It does not prove behavior for a live
  database value, external integrations, generated/plugin code, future code,
  or dynamic runtime evaluation.
- This audit did not inspect every generic backend `output_path`, test-only
  fixture, database migration/history, or every field in project metadata;
  those are outside the stated `ApiCall.output_path` production-use question.

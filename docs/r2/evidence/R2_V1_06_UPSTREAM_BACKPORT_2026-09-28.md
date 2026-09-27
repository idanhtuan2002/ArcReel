# R2 V1-06 — upstream backport (U3), packets P1 and P2 (2026-09-28)

> **Corrected after the independent review (F10).** The dispositions below match `R2_V1_06_UPSTREAM_INVENTORY_2026-09-28.json`, where the E1 verifier proved them against the host range: 4 UNCHANGED (equal stable patch-id) and 12 ADAPTED (named by a cherry-pick or `Upstream:` marker). `3ff6127f` is ADAPTED only in part: its guard, Gemini-resume and base-URL-pinning parts are taken, and its settings and dead-code parts are deferred.

**Decision:** ADR-0091 (U3).

**Plan:** `docs/superpowers/plans/2026-09-28-r2-v1-06-paid-routes-e1.md`.

**Upstream range:** from the merge base `6ddedc77` (release 0.29.0) to
`upstream/main` `317a7d0d`.

**Base:** before the packets, the branch head was `20a030d8`.

## Dispositions of the selected commits

A **pick** below is `git cherry-pick -x`: the upstream commit is applied
unchanged, and its message carries `(cherry picked from commit …)`. An
**adapted** commit re-implements the fix against this lineage and names the
upstream commit in an `Upstream:` trailer.

| Upstream | Disposition | Host commit(s) | V1 defect confirmed on this lineage |
|---|---|---|---|
| `108d1680` | UNCHANGED (pick; equal stable patch-id) | `180ff5bb` | A download token (`purpose: download`) was accepted as a session token: probe returned 200, now 401. |
| `c1cf1c62` | ADAPTED (clean pick, but the patch-id differs against this lineage; proven by its cherry-pick marker) | `ae3e8229` | Anonymous `GET /files/{p}/project.json` and `/files/{p}/source/*` returned 200 with content; now 404. |
| `9317ae46` | ADAPTED (pick with a test conflict resolved; marker) | `ae990d31` | Task cancel looked tasks up by id without `_scope_query`. |
| `5839ef3b` | UNCHANGED (pick; equal patch-id) + a separate test adaptation | `d353a80f`, `843910a2` | Retry-download lookup had no scope. The test was adapted to V1's `payload.api_call_id` link. |
| `31c5e985` | UNCHANGED (pick; equal patch-id) | `d6c7f22e` | Bulk cancel returns early when no queued tasks are in scope. |
| `e6e60d0c` | ADAPTED (pick with import paths mapped; marker) | `109241e2` | Project-name validation on project-addressed routes. |
| `6a3e6cd8` | UNCHANGED (pick; equal patch-id) | `10b104e3` | The source ledger followed symlinks. |
| `eec3c21e` | ADAPTED (pick with import paths mapped; marker) | `6bf80309` | Version snapshot paths were not resolved or validated. |
| `d3d0c454` | ADAPTED | `daf5755a` | `GET /custom-providers/{id}/credentials` returned the key in plaintext; removed. The Agent import now copies the key on the server. The dependent base-URL normalization is not taken: its migration would fork Alembic. |
| `2c4ca6d6` | ADAPTED | `5ed579b9` | Provider artifact downloads had no destination guard and no byte cap. |
| `8faf1450` | ADAPTED | `420b3d89` | Anthropic discovery skipped the destination guard. A cross-origin 307/308 forwarded the request body. |
| `3ff6127f` (guard part) | ADAPTED | `cef142d5` | Built-in direct-HTTP submits and polls were unguarded. A source-scan test now pins this. |
| `3ff6127f` (Gemini resume part) | ADAPTED | `2907dcec` | An artifact 404 after a finished paid Gemini job was classified as expired. Proven: 6 tests fail on the old code. |
| `3ff6127f` (base-URL pinning part) | ADAPTED | `8c0591fa` | Kling, Ark and OpenAI resumed at the current base URL, not the submitted one. Proven: 3 tests fail on the old code. |
| `39fe7611` | ADAPTED (clean pick, patch-id differs; marker) | `25e12509` | Veo with no resolution set was priced at 1080p; the provider renders 720p. |
| `0f8a4e1f` | ADAPTED | `d2b09b64` | The storyboard cost estimate substituted the 1080p fallback that execution does not send. |
| `7e994e5f` | ADAPTED | `d893941a` | Episode-scope generation re-enqueued a selected manual upload, a paid regeneration. Proven: 2 tests fail on the old code. |
| `29c778f0` | ADAPTED | `02ec75b2` | The current-scope export shipped the full history of products, grids and end frames, and left character-derivative records dangling. Proven: the test fails on the old code. |

## Deferred

These commits are `DEFERRED` to the post-V1 upstream merge packet unless
V1-07 observes the defect.

| Upstream | Reason |
|---|---|
| `70e1db92`, `d42226d5`, `7f3dfa14`, `91b50681` | They depend on the upstream video-request-facts refactor (`lib/generation/video_request_facts.py`), which this lineage lacks. V1 already gates the `ALWAYS_ON` audio conflict in `server/services/video_caps.py`. Whether V1 still has the remaining preflight/execution divergence is **open**, and is assessed in V1-07 on real runs. |
| `6676f109`, `1cf17bfa` | They change interruption and `cancelling` semantics that M7-C accepted. Taking them would re-open M7-C. |
| `11f77f8f` | It only affects projects made with ArcReel 0.26 or earlier. It adds project schema v13; V1 is at v12. Deferred until a legacy project import is actually needed. |
| Everything else in the range | ComfyUI, market, the data-root relocation, UX, i18n and development skills are not V1 needs. The data-root and Alembic changes are rejected for V1 (ADR-0091, U2). |

## Verification (after P1 and P2)

- **Targeted suites:** each packet's targeted tests pass. See the per-commit
  runs recorded in each commit.
- **Scoped suites:**
  - `tests/unit/server`, `tests/integration/server`, `tests/unit/lib` and
    `tests/integration/lib`: 12477 passed after P1;
  - video, server and media_tools scopes: 5209 passed after the resume
    fixes;
  - media_tools: 253 passed;
  - archive, export and import: 150 passed.
- **Static gates** at the P1 close: ruff, format, basedpyright 0/0,
  lint-imports 20/0, deptry and audit_tests are all clean.
- **Not yet run:** the full suites. They run at the V1-06 closing gate.
- **E1 upstream verifier record:** produced in packet P4, after the verifier
  is fixed.

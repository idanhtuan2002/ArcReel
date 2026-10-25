# V2 shared model-facts read model — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Execute sequentially; preserve the repository background-agent limit.

**Goal:** Provide a single read-only query over existing V2 model facts without changing selection, prices, qualification or execution.
**Architecture:** Keep `PROVIDER_REGISTRY`, custom model rows and protocol declarations as current owners. A small query module composes their facts using the caller's read session; existing resolvers/builders remain authoritative. Pinned ArcReel catalog vocabulary is the source reference, not a new mutable catalog.
**Tech Stack:** Existing Python/SQLAlchemy/pytest; no new runtime dependency or database migration in this slice.
**Spec:** ../specs/2026-10-24-v2-model-platform-compatibility.md
**ADR:** ../../adr/0110-shared-model-catalog-keeps-v2-execution-authority.md (proposed).
**Baseline:** b019d87d64d8fe145a3dd1d932ae16861aa2006c; implementation must start from the later design-packet commit and recheck source hashes.

## Status and constraints

Implementation and one independent review/repair are committed through `a56f07a9471c0916c768c120eaaacf95598c8e6e`. The affected suite passed 1806 tests and all seven static gates passed. Verification and handoff are complete with an explicitly failed whole-backend gate: the broad run was interrupted after 17407 passed, 187 skipped and three failures; all seven remaining tests then passed. Exact collection/JUnit reconciliation accounts for all 17604 node IDs with no unexecuted remainder. Clean baseline/candidate clones reproduce the same two pre-existing authority-test failures and both pass the M7 clean-tree check. Full backend is not green; this is not cloud or production acceptance. See [current evidence](../../r2/evidence/R2_V2_MODEL_CATALOG_READ_MODEL.json). The old Gemini-only drafts remain preserved.

- No provider HTTP/SDK construction, DB migration, new secret store, price edit/sync, implicit model switching or new production activation.
- Keep local ADR0039/0049/0051/0054/0055/0091/0093 and existing ComfyUI bindings effective.
- Preserve user/project/custom-model IDs, exact prices/currencies and all old approval/checkpoint digests.
- No full upstream package/layout merge or second writable catalog. No exported result contains credential material or a credential-derived binding digest.
- No endpoint replacement in this slice. A query must not imply budget admission or workload qualification.

## File ownership

Create only after confirming no existing equivalent:

- `lib/catalog/__init__.py`: public read-only query exports.
- `lib/catalog/query.py`: builtin/custom source projection and immutable view types; no provider dispatch or persistence.
- `tests/unit/lib/catalog/test_catalog_query.py`: builtin/identity/price projection behavior and input invariants.
- `tests/integration/lib/catalog/test_custom_model_query.py`: real disposable DB/endpoint facts and no-write assertions.
- `docs/r2/evidence/R2_V2_MODEL_CATALOG_READ_MODEL.json`: exact candidate source and verification evidence.

Reuse current registry functions and repository/endpoint resolvers. Do not pre-create unused normalized-metering or cloud execution interfaces. Source inspiration: upstream `lib/catalog/query.py:CatalogModel`; donor identity/pricing migration and synchronized composition are excluded. A type cannot flatten independent custom input/output prices into a multiplier.

Proposed public interface (confirm names against real code before RED):

- `CatalogModel`: immutable identity/display facts; `provider_id`, `model_id`, `api_model_name`, `media_type`, `display_name`, `enabled`, `hidden`, `default`, `endpoint` when applicable, provenance/source version, price facts with independent currency/rates. Do not include secret, base URL or credential binding.
- `builtin_model(provider_id, model_id) -> CatalogModel | None`: pure lookup; no automatic model fallback.
- `custom_models(session, *, provider_id=None) -> tuple[CatalogModel, ...]`: read existing rows/endpoint declarations; include disabled models with flags so callers choose display filtering. No provider credential reads or secret-bearing ORM objects returned.

These are internal query types, not a replacement for `ProviderModel` or a new public HTTP protocol. Use deterministic ordering and preserve API model names/IDs as stored. Derive protocol facts using pure declarations; do not initialize a backend to discover them. If the existing repository list method reads credentials, add a narrowly scoped column projection rather than loading a whole secret-bearing provider entity into the view.

## Task 0: Source/compatibility gate

- [x] Re-read spec+ADR and exact live status; preserve all unrelated dirty files. Verify prior source-manifest hashes and donor pin, recheck graph generation/coverage before structural discovery.
- [x] Trace model registry helpers, custom row/endpoint reads and consumers. Check actual repository query surfaces and SQL selection; distinguish model catalogue lookup from load_custom_backend fallback.
- [x] Confirm query output schema retains10 current price kinds, including ViduDelegate as its existing representation; stage1 price facts are descriptive, not donor `PriceTable` conversion.
- [x] Write a source crosswalk and baseline fixtures with representative builtin/custom IDs (including slash/alias/API-name separation), hidden/disabled/default states and independent price ratios. Snapshot old StoryBrief golden digest from design evidence.
- [x] Gate: no extra provider SDK construction, unknown source ownership or hidden secret exposure. If conflicts appear, update this plan with source evidence before coding.

## Task 1: Pure builtin projection

- [x] RED: test named builtin returns exact media/display/API/default/hidden/price facts; unknown provider/model returnsNone; no silent fallback; no mutation of source lists/dicts through returned value.
- [x] RED: enumerate all builtin models and show a one-to-one identity mapping; capability source remains model/protocol-specific and UNKNOWN is not inferred supported.
- [x] Implement minimal query/types using existing registry helper functions and immutable copies. Match existing domain terminology, no protocol client construction.
- [x] GREEN: run new unit file, existing config-registry and pricing lookup tests; tests must select more than0 cases.
- [x] Commit only owned paths and record command/result/source range. Do not change old registry defaults/entries or pricing behavior to make the view simpler.

## Task 2: Custom projection with read transaction

- [x] RED: use real disposable DB rows for two providers sharing model names; preserve independent routes, endpoint, enabled/default, custom input/output rates and USD/CNY. Include unmatched model name and disabled endpoint/model.
- [x] RED: prove returned objects contain no credential fields; no INSERT/UPDATE/DELETE or sync/migration side effects; deterministic list order and exact-ID lookup.
- [x] RED: endpoint declaration failure is represented explicitly/propagated according to spec, never hidden by dropping a provider. Query cannot alter enabled/default flags or trigger loader fallback.
- [x] Implement only existing column/endpoint reads; reuse caller-owned session and pure endpoint facts. Avoid reading keys/base URLs just to display names.
- [x] GREEN: run new integration file plus backend-loader and existing release-binding tests; fixture database must be disposable and local, never use production selector.
- [x] Commit owned paths and record gate. Price view is not an admission estimate and endpoint support is not live qualification.

## Task 3: Whole-slice verification and handoff

- [x] Run full affected backend gates per CONTRIBUTING. If shared initialization/dependency or test facilities change, broaden to mandated backend full suite. Always run Ruff, formatting check, basedpyright, import contracts, deptry and test audit as applicable.
- [x] Verify no production source files beyond explicitly owned query paths changed and no frontend/API/schema/settings behavior changed.
- [x] Independent whole-slice review once for identity leakage, source mutation, unknown capability, custom-price loss and secret reads. Main owns architecture/security conclusions; honor one background-agent maximum.
- [x] Repair significant findings once with RED→GREEN and targeted/full affected tests. Record deferred minor findings; no per-task review loops.
- [x] Write evidence with exact source HEAD/hashes/test counts/limitations and next-slice prerequisites. This gate is read-model acceptance only, not Gemini integration or cloud qualification.

## Review focus

- Alias or slash-containing model IDs accidentally collapse two provider routes or change defaults.
- Nested mutable values expose registry state or credential-bearing ORM entities through the read model.
- Disabled/hidden/unmatched models disappear in a way that makes existing settings or historical lookups unreadable.
- Independent custom prices/LOCAL/Vidu meanings are flattened into a misleading generic price.
- A UI caller treats candidate/capability facts as qualification or cached budget permission; construction/dispatch must remain outside this module.

## Later plans, intentionally outside this slice

Donor core packaging and normalized metering; request-level execution profiles and reservation/concurrency changes; versioned cloud story brief and Gemini/Ollama qualification; UI eligibility; other cloud/media/Agent integrations. Write their plans from this spec after their compatibility gates, rather than expanding this first slice into a system rewrite.

## Recorded scope adjustment

The final review reproduced two ComfyUI duration mismatches. A small pure `resolve_endpoint_durations` helper in `lib/custom_provider/endpoint_resolution.py` now supplies both the existing `ConfigResolver` and the catalog; resolver behavior remains unchanged. These two existing source files extend the original four source/test ownership paths. Differential real-DB tests went RED to GREEN, followed by 290 related and 1806 affected passes. One independent review and one repair pass were used. Deferred minor: three unqueried custom constraint fields still need unknown-versus-empty semantics before consumer wiring.

The [metering readiness note](../../research/2026-10-24-model-metering-readiness.md) is preparatory research for a later plan; it adds no runtime behavior.

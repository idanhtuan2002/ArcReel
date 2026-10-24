# V2 local-price compiler implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans sequentially in the main session. One independent whole-slice review after implementation.

**Goal:** Compile existing builtin/custom price facts for the normalized kernel without altering any executing consumer.
**Architecture:** Small pure compiler over current Pricing dataclasses plus scalar custom columns; reuse the stage2A validator through an additive public function. No catalog matching, lookup fallback, second price store or money writer.
**Tech stack:** Existing Python/pytest/standard library; no dependencies or migrations.
**Spec:** ../specs/2026-10-24-v2-price-compiler.md
**Status:** Prepared; start from this packet's committed HEAD, source baseline ee00e0a9302d17e61754e6f13219c07a4bee051a.

## Global constraints

- No runtime wiring, provider SDK/network, DB/schema, price/default/model edits, catalog sync, reservation/admission, UI/API, push/merge/deploy.
- Preserve independent custom input/output prices and currency; no missing-to-free conversion. Keep LOCAL and Vidu in their current owners.
- Old legacy calculators retain fallback. New compilation is exact-ID/strict; the two paths are tested side by side rather than globally tightened.
- Reuse the existing isolated worktree, preserve the two untracked Gemini drafts. Branch from the packet for this slice; no cleanup/reset of user work.

## Review focus

1. An absent exact rate silently becomes default/official pricing, or model IDs containing slashes merge.
2. Cached image/text rate cells disappear, or unknown cache usage is charged as zero.
3. Matrix buckets/tier labels are flattened or case-fold/default aliases make two rows ambiguous.
4. Mutable/invalid price facts bypass kernel validation; a zero rate is confused with a missing one.
5. Compiled/reference tables become execution permission or alter legacy fallback/historical costs without caller activation.

## Task 0: Source and baseline gate

- [ ] Verify live Git/graph state, coverage and source fallback. Seal current pricing/types/strategies/lookup/calculator, seven legacy owners and stage2A source. Record current108identity inventory:88convertible,14no-price,6Vidu, no exact-rate misses.
- [ ] Verify donor pin258c7ff1 and actual catalog_pricing/migration incompatibility; reuse schema/kernel/crosswalk, exclude donor price ownership/migration. Confirm no existing exact compiler in actual pricing source.
- [ ] Establish plan workspace and focused baseline: `python -m pytest tests/unit/lib/pricing tests/unit/lib/config/test_config_registry_models.py tests/unit/lib/catalog -q`. Expected192passed; preserve known unrelated whole-backend failures separately.

## Task 1: Exact builtin declaration compilation

**Modify:** `lib/pricing/request_metering.py` (add validate_price_table wrapper/export only).
**Create:** `lib/pricing/price_compiler.py`; `tests/unit/lib/pricing/test_price_compiler.py`.
**Consumes:** Pricing dataclasses and verified kernel. **Produces:** compile_pricing and validator interfaces defined by spec; immutable PriceTable or Unpriced.

- [ ] RED: compile_pricing missing. Test exact no-fallback/slash identity, None/no price, all nine shapes and explicit OpenAI tokens/reference modes. Compare to legacy strategies on the same fully specified input and assert exact known quantities/currencies.
- [ ] RED: four primary image token axes plus optional image/text cache axes preserve all six declared rates. Missing primary fields→MISSING_RATE; unknown field→UNRECOGNIZED_TERMS. Missing token usage stays unpriced and never triggers reference mode.
- [ ] RED: all108registry entries produce88tables/14NO_PRICE_TABLE/6delegates. For each convertible identity assert model selected by exact rate key; test dimensioned representatives against existing strategy results. Synthetic tables additionally cover flat/matrix variants, known free rates, reference sizes, quality tiers and discrete bucket totals.
- [ ] RED: unknown model with default_model present→NO_ENTRY; unknown dimensions at pricing time stay unpriced while old nearest/default lookup remains unchanged. Case-folded resolution/quality and default→standard collisions→UNRECOGNIZED_TERMS. Bad numeric selected rate→ValueError; modifying source maps after compilation cannot change the prior snapshot.
- [ ] Add validate_price_table using existing _table snapshot validation, then implement compile_pricing by shape mapping only. No request construction, normalization or provider resolution. Return explicit Vidu/LOCAL unpriced status and leave existing owners unchanged.
- [ ] GREEN: `python -m pytest tests/unit/lib/pricing/test_price_compiler.py tests/unit/lib/pricing/test_request_metering.py tests/unit/lib/pricing/test_request_metering_core.py -q`; >0selected,0failures. Run affected baseline command. Commit owned files before task-done so ledger ranges bind real commits.

## Task 2: Custom price-unit compilation

**Modify:** compiler module. **Create:** `tests/unit/lib/pricing/test_custom_price_compiler.py`.
**Consumes:** Task1 builders/validator. **Produces:** compile_custom_pricing scalar interface; no DB access.

- [ ] RED: missing custom function. For token rates .45/1.25 with input1000/output500 assert .001075 in both USD/CNY; no common multiplier. Known0rates return0 with explicit usage; missing input/output stays MISSING_RATE.
- [ ] RED: image .1×3→.3, second .5×8→4, character .8×100/10000→.008; inactive historical price_output does not add a charge. All-None/missing currency/unknown unit follow spec. Do not default USD or consult a known official model.
- [ ] RED: negative/bool/nonfinite active rates, unknown currency, source-key absence, zero-versus-missing and immutable snapshots. Show existing custom calculator's reference/fallback behavior remains unchanged, including missing-price0 and zero-duration8second policy; new strict quantities do not inherit it.
- [ ] Implement only scalar-to-meter mapping, using the same immutable table validator. No price/model persistence, rerouting or source data deletion.
- [ ] GREEN: both compiler files plus affected baseline command, >0selected/0failures. Commit scoped compiler/test files, then task-done with actual range.

## Task 3: Whole-slice review and evidence

- [ ] Run affected pricing/config/catalog tests, all seven backend static categories, and full committed base..candidate diff-check. Broaden per CONTRIBUTING only if runtime/shared-facility/DB/dependency or uncertain consumer scope changes.
- [ ] Verify all legacy owners/private kernel bytes unchanged; stage2A guard differs only by additive wrapper/export. Verify no production compiler consumers/imports and no UI/API/schema/admission activation.
- [ ] Independent whole-slice review once; main verifies findings, makes at most one significant RED→GREEN repair pass and records deferred minors/rulings. Reviewer must include declined-to-judge behaviors.
- [ ] Write docs/r2/evidence/R2_V2_PRICE_COMPILER.json with exact candidate/port/source hashes, current commands/results, old-fallback comparisons, provenance/limitations and next profile prerequisites. Preserve hashed archive/RESUME. Commit evidence only; keep the local branch.

## Self-review

The two compiler functions and validator are defined once in the spec; tasks match those interfaces. Each review-focus class has Task1/2 tests or Task3 unchanged-owner checks. Provider parsing/actual request facts, identity custody, conservative Decimal reservation bounds, consumer wiring and production activation are explicitly outside this plan. Numeric rates remain source-owned and compilation never calls the legacy fallback machinery.

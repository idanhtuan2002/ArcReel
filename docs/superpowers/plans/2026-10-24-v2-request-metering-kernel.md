# V2 guarded request-metering kernel implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans, sequentially in the main session. One independent whole-slice review after implementation, no per-task fan-out.

**Goal:** Add pure, validated per-request unit arithmetic without changing any model execution or money writer.
**Architecture:** Privately port three pinned donor files and place host numeric/completeness guards behind two functions in `lib.pricing.request_metering`. Preserve existing price and execution owners. Local-price conversion follows in a separate stage 2B plan.
**Tech stack:** Existing Python >=3.12, standard library, pytest; no new dependency, migration or configuration.
**Spec:** ../specs/2026-10-24-v2-request-metering-kernel.md
**Source evidence:** ../../research/2026-10-24-model-metering-crosswalk.md; ../../r2/evidence/R2_V2_MODEL_METERING_CROSSWALK.json
**Status:** Implemented and independently reviewed at `169490a211a76b58425a91e711a5f392d66f3448`;63new tests/192affected pass and7static checks pass. Not wired to execution or accepted for production. Start baseline was the packet commit `c3b7ed2fd63acafab694e7d7b7527220dcd7cbbe`; source baseline b646708d62b8dcbb183a65ea5341f29db99e2a14. The tested donor pin is258c7ff1ca1f103117cb4f757f7f09fd46cb8647.

## Global constraints

- No runtime consumer wiring, SDK construction, network, DB/migration, model/default/price changes, new dependency, approval/reservation or deployment.
- Preserve independent custom rates/currencies, LOCAL/Vidu ownership, historical costs, old brief/checkpoint bytes and current route qualification.
- Do not transplant the donor Kling resolver:1080p+std differs from local execution. Do not globally alias quality std/pro/4k into service standard/flex/fast.
- The two existing baseline authority assertions remain failed evidence; this plan never opens a release gate or broadens their allowlists.
- Keep every unowned dirty/untracked path. Use a clean isolated worktree under the writable repository; do not clean/reset the old managed worktree's two Gemini drafts.

## Review focus

1. Partial response usage or omitted cache fields silently becomes priced zero.
2. Bool, NaN/infinity, negative or overflowing values bypass checks through unknown/free/zero branches.
3. Caller mutation changes price facts or quotes; row/default ordering changes which rate applies.
4. Equal physical requests are deduplicated, or logical retry count is treated as one physical call.
5. New kernel imports change existing prices, adapter resolution, money precision or permission despite having no consumer wiring.

## Task 0: Source and scope gate

**Files:** plan-owned ledger/source manifest only; no product files yet.
**Consumes:** research packet and spec. **Produces:** pinned port manifest and verified source boundary for Tasks1–3.

- [x] Verify live HEAD/status, nearest graph project/generation and coverage. Read flagged source ranges; confirm whether proposed module/private package already exists before creating it. Recheck seven host source hashes from the crosswalk evidence.
- [x] Use using-git-worktrees to create/reuse isolated `feat/v2-request-metering-kernel` from the committed packet. Preserve old Gemini drafts in the original checkout. Unset DATABASE_URL for disposable tests.
- [x] Recover the archived isolated-port experiment. Verify model.py/vocabulary.py bytes and metering.py's sole import adaptation against the donor Git pin. Record host, source and adapted hashes; no full package/catalog snapshot import.
- [x] Gate: no conflicting existing implementation or unknown ownership. If a conflict appears, ledger the evidence and amend the plan before creating a duplicate module.

## Task 1: Private arithmetic port

**Create:** `lib/pricing/_metering_core/__init__.py` (empty), `model.py`, `vocabulary.py`, `metering.py`, `SOURCE.json`; `tests/unit/lib/pricing/test_request_metering_core.py`.
**Consumes:** Task0 manifest, exact donor types/algorithm/test file. **Produces:** private donor Usage/PriceTable/Meter/PriceRow/Priced/Unpriced/UnpricedReason/price_requests functions for Task2.

- [x] RED: copy the donor's nine cases from `tests/unit/lib/billing/test_metering.py` into the owned test file; adapt imports to the private model/vocabulary/metering paths only. Run `python -m pytest tests/unit/lib/pricing/test_request_metering_core.py -q`; expect import failure because the private package is absent.
- [x] Copy model.py/vocabulary.py byte for byte. Copy metering.py changing only `from arcreel_catalog_core import CJK_DOUBLE_METER, METERS, Meter, PriceTable` into imports from `.model` and `.vocabulary`. Record these transformations and both hash sets in SOURCE.json; no algorithm edits or blanket tool ignores.
- [x] GREEN: same command selects exactly9passed. Confirm the public guard module does not exist yet and no legacy imports changed.
- [x] Commit owned paths only: `feat: port pinned request metering arithmetic`.

## Task 2: Host guards and complete-usage semantics

**Create:** `lib/pricing/request_metering.py`; `tests/unit/lib/pricing/test_request_metering.py`.
**Consumes:** Task1 private types/arithmetic. **Produces:** the two functions and type exports exactly as specified; no later converter/caller interface is created.

- [x] RED: through public price_requests, assert known seconds8 at.5=>Priced(4,USD); known output_seconds0=>Priced(0,USD); table with input/output token axes but only input reported=>Unpriced(MISSING_RATE), and estimate=True=>NO_USAGE_ESTIMATE. Missing table=>NO_PRICE_TABLE; entry_found=False=>NO_ENTRY; empty sequence=>MISSING_RATE or NO_USAGE_ESTIMATE. Missing usage on zero-rate meter stays unpriced; explicit zero stays priced.
- [x] RED: parameterize bool,negative,NaN,infinity,oversized-int and wrong numeric shapes on quantities/rates/free_allowance, including zero/free/unknown branches:ValueError. Finite inputs whose arithmetic overflows also ValueError. Duplicate meter identities/dimension declarations ValueError. Unknown meter/currency/dimension and service_tier=std=>UNRECOGNIZED_TERMS. LOCAL never becomes USD.
- [x] RED: token_usage(input_tokens=100,output_tokens=50) returns only output_tokens50. With explicit three cache zeros, preserve all three zeros and uncached100. With total100,cache20/10/5 return uncached65,cache20/10/5,output50. Total1/cache2 raisesValueError even if other cache fields unknown. Negative/bool/fractional count invalid; unknown output meter invalid; cache known with total absent remains reported without invented uncached input.
- [x] RED: two equal seconds8 usages=>8USD, preserving two requests; source mappings remain unchanged and prior result stays unchanged after caller mutation. Preserve declared wildcard/default row ordering with overlapping-specific/default rows. Raw characters text plus explicit characters quantity=>ValueError. A known nonbilled count meter remains ignored; a positive unpriced token meter remains MISSING_RATE.
- [x] Implement the spec interface. Snapshot immutable views, validate known numeric facts and schema, enforce completeness, call private arithmetic with multiplier1, validate result. Implement token normalization with missing-cache semantics; keep raw provider parsing/attempt identity outside.
- [x] GREEN: run both owned files; every parametrized guard class selects cases and passes. Then `python -m pytest tests/unit/lib/pricing tests/unit/lib/config/test_config_registry_models.py tests/unit/lib/catalog -q`. Expect>0selected and0failures; investigate every discrepancy, never relax legacy behavior to fit the new guard.
- [x] Commit owned paths only: `feat: guard normalized request metering facts`.

## Task 3: Whole-slice verification and handoff

**Create:** `docs/r2/evidence/R2_V2_REQUEST_METERING_KERNEL.json`; plan-owned archive/ledger.
**Consumes:** sealed source, Task1–2 green runs. **Produces:** bounded kernel evidence and stage2B prerequisites, not release acceptance.

- [x] Run relevant tests above, Ruff check and format check, basedpyright --warnings, lint-imports, deptry lib server alembic scripts tests r2, scripts/audit_tests.py --check, git diff --check. Use the existing valid environment; log actual commands. Broaden per CONTRIBUTING if shared facilities/dependencies/DB/initialization or uncertain consumers change; do not rerun unrelated media render suites without such a trigger.
- [x] Confirm all seven legacy source hashes unchanged and no new consumer imports the guard. No API/UI/schema/SDK/paid admission changes. Keep whole-backend historical failures distinct from this slice's actual results.
- [x] One independent review of the complete diff for numeric bypasses, missing/zero/cache semantics, mutable input and identity/price/permission leakage. Main owns disposition. One significant fix pass with RED→GREEN; defer minor findings explicitly.
- [x] Write exact HEAD/port/source hashes, tests/static outputs, deferred findings and limits. Stage2B must compile exact local price facts and re-use49fixtures; later execution must establish Decimal/conservative bounds, actual provider usage facts, attempt dedupe and reservation semantics. Neither is implemented here.
- [x] Commit evidence only and keep the local feature branch available. No push/merge/deploy/provider generation.

## Plan self-review

This plan covers stage2A only; parent-spec price conversion, credit/LOCAL handling, money precision, provider response parsing, reservations and UI are explicitly later gates. Task1 private exports match Task2 imports; Task2 defines the only new host interface. Each Review Focus has public-interface assertions in Task2 or unchanged-source checks in Task3. No implementation test is claimed from the isolated nine-case experiment.

## Execution ruling and limits

Reused the existing harness-managed linked worktree on `feat/v2-request-metering-kernel`, preserving two untracked Gemini drafts; no second worktree was created. The independent review found no significant product defect; two evidence-only bookkeeping notes were corrected by appending actual commit ranges and running a committed-range diff check. Stage2B compilation and all later execution/money/production gates remain unimplemented. See [kernel evidence](../../r2/evidence/R2_V2_REQUEST_METERING_KERNEL.json).

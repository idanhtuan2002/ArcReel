# Pinned metering donor: bridge prerequisites

Status: preparatory source research, not a bridge implementation or acceptance. Host source `a56f07a9471c0916c768c120eaaacf95598c8e6e`; read-model verification is complete with two unchanged whole-backend baseline failures, recorded in commit `78c05c918`. M9/M10 and deployed V2 are unchanged.

The existing [compatibility specification](../superpowers/specs/2026-10-24-v2-model-platform-compatibility.md#4-price-and-usage-semantics) remains the authority. This note narrows packaging and validation gaps before its second slice; it does not replace the prior reuse review or select a package-install strategy.

## Verified source

ArcReel commit `258c7ff1ca1f103117cb4f757f7f09fd46cb8647`: all 11 nonempty Python files in the prior isolated extraction matched `git show <pin>:<path>` byte for byte. No fetch, install, provider call or DB operation occurred. The original extraction has no package metadata; metadata below was read directly from the pinned Git object.

The [core package metadata](https://github.com/ArcReel/ArcReel/blob/258c7ff1ca1f103117cb4f757f7f09fd46cb8647/packages/arcreel-catalog-core/pyproject.toml) declares version 0.1.0, Python >=3.12, no runtime dependencies and a Hatchling build. [Core exports](https://github.com/ArcReel/ArcReel/blob/258c7ff1ca1f103117cb4f757f7f09fd46cb8647/packages/arcreel-catalog-core/src/arcreel_catalog_core/__init__.py) transitively import its model, vocabulary, dataset, readers and writer. The [metering module](https://github.com/ArcReel/ArcReel/blob/258c7ff1ca1f103117cb4f757f7f09fd46cb8647/lib/billing/metering.py) imports that core plus the standard library. Merely copying its single file does not satisfy its imports. This is source evidence, not an installed-wheel/build verification.

## New offline characterization

Command: `python3 /tmp/model-metering-safety-probe.py`, exit 0. Nine cases exercised the unchanged pinned donor. Probe and exact results are preserved in `.superpowers/sdd/2026-10-24-model-metering-readiness/`, with hashes in its manifest. These are characterization observations, not passing product acceptance tests.

| Input | Observed donor result | Requirement before host use |
|---|---|---|
| output_seconds=-1 | priced 0 USD | Reject negative quantities |
| output_seconds=NaN | priced NaN USD | Reject nonfinite quantities and results |
| output_seconds=infinity | priced infinity USD | Reject nonfinite quantities and results |
| multiplier=-1 | priced -0.5 USD | Validate multiplier independently |
| rate=-0.5 | priced -0.5 USD when directly constructing types | Validate rate/table at the bridge boundary; reader guarantees alone are insufficient |
| output_seconds=True | priced 0.5 USD | Reject bool where numeric usage is required |
| total input=1, cache read=2 | cache=2, uncached=0 | Validate disjoint usage and cache sum before token_usage clamps |
| mutate Usage.quantities after construction | price changes from 0.5 to 5 USD | Snapshot mutable inputs before relying on them |
| same Usage twice in request list | 5 USD becomes 10 USD | Distinguish repeated records from distinct physical requests using existing attempt evidence |

These observations do not establish a donor defect: the module documents disjoint usage and may rely on trusted callers. The inference for V2 is that this arithmetic is not its admission, validation, request-identity or immutable-evidence boundary. Deduplicating equal quantities is also wrong: two real requests with identical usage must both be charged. No particular deduplication algorithm is selected here.

## Unfinished gates

Before implementation: choose a reproducibly pinned import/package surface and check its dependency/import contracts; run the same fixtures across all ten legacy price shapes and legacy fallback behavior; retain explicit LOCAL/Vidu delegates; validate finite nonnegative usage/rates, missing versus zero, cache overlap and thought/output accounting; preserve independent custom rates/currencies and historical settled costs. Request identity must come from existing execution attempts, and money writes remain in the current ledger/reservation authority. A new pure arithmetic helper must not imply safe pre-submit bounds or open a cloud route.

The current probe covers no packaging build/install, money precision, concurrent reservations, provider response parsing, full fallback matrix, retry recovery or live qualification. The earlier 22-case compatibility evidence remains historical; it was not rerun or enlarged by these nine cases. No later implementation plan or runtime activation is approved merely by this note.

## Dimension crosswalk still needed

Further pinned-source inspection found a second boundary to settle before writing the production bridge plan. This is not an accepted mapping:

- Local `lib/pricing/types.py:PerSecondTiered` and `lib/pricing/strategies.py:_per_second_tiered` use quality/mode tiers `std`, `pro` and `4k`. The donor vocabulary calls `service_tier` the separate closed set `standard`, `flex`, `fast`. Equal field names do not establish equal meanings. Do not translate local `pro` into donor `fast`.
- The donor vocabulary has no `size` dimension. Existing `PerImageOpenAIToken` reference fallback uses `(quality, size)`. Converting size to another dimension needs an explicit, fixture-tested mapping; the prior exact-rate arithmetic examples did not prove this matrix.
- Direct construction of donor `PriceTable` with a `service_tier=std/pro/4k/default` row reports `is_priceable=True`: that property checks recognized currency/meter/dimension keys, not all row values. The donor reader separately flags invalid dimension values (`reading.py:check_dimension_values`, via `is_valid_dimension_value`). Therefore a bridge that constructs types directly must preserve validation rather than treat `is_priceable` as complete validation. A table using a `size` dimension reports `is_priceable=False` with `unrecognized_keys=(size,)`. These six additional direct-construction observations were run offline; they are separate from the nine numeric/mutation probes above.
- The actual pinned `lib/catalog/snapshot/catalog.json` video entry `kuaishou/kling-v3` declares rates by resolution/audio, and `kling-v3-omni` additionally includes input_video. This does not make that snapshot a replacement for local tiered declarations. Use the donor algorithm/schema selectively and preserve local price ownership.

Primary sources: [donor vocabulary](https://github.com/ArcReel/ArcReel/blob/258c7ff1ca1f103117cb4f757f7f09fd46cb8647/packages/arcreel-catalog-core/src/arcreel_catalog_core/vocabulary.py), [price model/property](https://github.com/ArcReel/ArcReel/blob/258c7ff1ca1f103117cb4f757f7f09fd46cb8647/packages/arcreel-catalog-core/src/arcreel_catalog_core/model.py), [reader validation](https://github.com/ArcReel/ArcReel/blob/258c7ff1ca1f103117cb4f757f7f09fd46cb8647/packages/arcreel-catalog-core/src/arcreel_catalog_core/reading.py), and [pinned snapshot](https://github.com/ArcReel/ArcReel/blob/258c7ff1ca1f103117cb4f757f7f09fd46cb8647/lib/catalog/snapshot/catalog.json). Read from local Git objects/extracted bytes; no live provider or price synchronization occurred.

Next concrete research gate: a lossless unit/dimension crosswalk and paired fixtures for local tier derivation, OpenAI size fallback, nearest video buckets and missing usage. Then select the smallest pinned import/package surface and write the bounded bridge plan. No production bridge interface has been declared ready by this note.

## Follow-up gate

The [49-case crosswalk and isolated three-file import experiment](2026-10-24-model-metering-crosswalk.md) now supplies fresh execution for selected dimension/fallback mappings and confirms an actual donor Kling execution difference. The [stage2A kernel specification](../superpowers/specs/2026-10-24-v2-request-metering-kernel.md) and [bounded plan](../superpowers/plans/2026-10-24-v2-request-metering-kernel.md) prepare guarded arithmetic first. The local-price converter and paid execution remain separate; no complete bridge or live acceptance is implied.

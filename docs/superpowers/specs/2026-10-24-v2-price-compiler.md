# V2 local-price compilation, stage 2B

Status: implemented and independently reviewed at b11709defb532de038d810715c424f7f9423f2ae;182new/374affected tests and7statics pass. Not wired to runtime. Baseline `ee00e0a9302d17e61754e6f13219c07a4bee051a`; uses the verified [stage2A kernel](2026-10-24-v2-request-metering-kernel.md), [49-case crosswalk](../../research/2026-10-24-model-metering-crosswalk.md) and parent [compatibility specification](2026-10-24-v2-model-platform-compatibility.md). No runtime activation.

## Decision and reuse evidence

Compile existing local declarations into the kernel's immutable PriceTable. Keep existing lookup/calculator/legacy fallback as owners of their current behavior; the compiler never resolves a provider or chooses a model. A registry inventory at baseline has108models:88with convertible declarations,14without price,6Vidu delegates; every convertible model has its exact rate key. The verified donor algorithm/schema are already in stage2A. Donor `lib/billing/catalog_pricing.py` depends on catalog matching and channel multipliers; its migration `c7e2a9d4b6f1` drops independent custom rates/currency/unit columns. It cannot supply the preservation contract here. Existing legacy strategies embed default/nearest fallback and missing-usage-to-zero policy; calling them cannot provide strict compilation. A small pure adapter is the remaining gap.

Alternatives: replacing local prices with donor snapshots violates price ownership; reusing legacy fallback as new strict pricing hides unavailable exact rates; compiling existing declarations preserves source facts without either migration. The builder selects the third path under the sponsor's reuse-first continuation.

## Interface and behavior

`lib.pricing.price_compiler` exposes:

- `compile_pricing(pricing: Pricing | None, *, model_id: str, image_mode: Literal["tokens", "reference"] = "tokens") -> PriceTable | Unpriced`
- `compile_custom_pricing(*, price_unit: str | None, price_input: float | None, price_output: float | None, currency: str | None) -> PriceTable | Unpriced`

Model IDs must be nonempty strings and are used exactly, including slashes/aliases. Never use default_model or a lookup/matcher. Missing exact model rate returns NO_ENTRY; no declaration returns NO_PRICE_TABLE; missing required rate cells/empty selected table return MISSING_RATE. Unsupported vocabulary returns UNRECOGNIZED_TERMS. Invalid numeric or structural source facts raise ValueError. Explicit0rates remain0. Tables contain no inferred defaults, nearest buckets, automatic aliases or mutable source mappings.

Add `validate_price_table(table: PriceTable) -> PriceTable | Unpriced` to stage2A's module/export list: reuse its existing snapshot/schema/numeric validator, returning UNRECOGNIZED_TERMS for unrecognized terms. No other kernel behavior changes. The compiler must use this interface instead of a copied validator or dummy request pricing.

| Declaration | Emitted meters / dimensions |
|---|---|
| PerToken | uncached_input_tokens/input and output_tokens/output, per million; both cells required |
| PerImageFlat | output_images |
| PerImageByResolution | output_images; resolution labels as declared |
| PerImageOpenAIToken tokens | image_in→uncached_image_input_tokens; image_out→image_output_tokens; text_in→uncached_input_tokens; text_out→output_tokens; optional image_cached_in→image_cache_read_tokens and text_cached_in→cache_read_tokens when declared. Four primary cells required; unknown extra rate names unpriced. No inferred cache rate. |
| Same, explicit reference mode | output_images; quality and exact size string represented as resolution label. Reference mode only valid for this pricing kind; never automatically selected because token usage is missing. |
| PerSecondMatrix | output_seconds; resolution/audio, resolution only, or no dimensions according to declaration. Matrix keys must match the declared shape. |
| PerSecondTiered | output_seconds; quality/std-pro-4k and audio. This compiles rate labels, not adapter mode or request facts. |
| PerVideoBucket | requests; exact resolution/duration. Never linearize flat buckets. |
| PerTokenVideo | video_tokens; service_tier/audio. Only the declared rate-key `default` maps to standard, matching the pinned Ark crosswalk; request normalization stays outside. |
| PerCharacter | characters, per10000; cjk_double=False |
| ViduDelegate | UNRECOGNIZED_TERMS; existing credit owner unchanged |
| LOCAL/unknown currency | UNRECOGNIZED_TERMS; existing run/local authority unchanged |

Case-folded collisions in rows, including default→standard tier collisions, must return UNRECOGNIZED_TERMS instead of letting row insertion order choose a price. Reject duplicate equivalent rows even if rates match. Preserve row order otherwise. String label matching follows kernel vocabulary; do not invent unknown tier aliases. No table defaults means missing dimensions remain unknown during pricing.

Custom units: token→two independent input/output rates (both required); image→output_images at price_input; second→output_seconds at price_input; character→characters at price_input with no CJK doubling. price_output is an inactive historical field for the three single-axis units, as in the existing calculator; it remains in its DB/query owner and is not a second charge. All-None facts yield NO_PRICE_TABLE; missing currency yields NO_PRICE_TABLE, unknown/missing unit with other facts yields UNRECOGNIZED_TERMS; missing required active rates yield MISSING_RATE. Never infer USD, a unit, or an official price. No multiplier, provider SDK, repository or catalog import.

## Limits and acceptance

A compiled table is descriptive rate data, not an approved price binding, complete invoice, dispatch permission or conservative budget bound. Its reference image branch cannot resolve missing actual usage or release reservations. Actual mode/audio/tier/size facts, model aliases, cache/thought partition, attempt identity, Decimal bounds and money writes remain later profile gates. No existing consumer imports the compiler in this slice.

Prove synthetic same-fixture arithmetic across nine shapes, all88convertible registry identities, explicit free rates, independent USD/CNY custom rates, optional cached-image/text rates, strict rejection of missing/unknown identity/dimensions and numeric/mutable/collision cases. Legacy fallback fixtures continue passing unchanged and are shown alongside strict unpriced results. Run all affected gates, one independent review and at most one significant fix pass. Preserve the known two whole-backend authority-test failures as separate historical evidence; no full-suite or production acceptance is claimed.

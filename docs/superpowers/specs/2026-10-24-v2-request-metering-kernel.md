# V2 guarded request-metering kernel, stage 2A

Status: implementation specification prepared from the sponsor's reuse-first continuation; product code not implemented. Parent: [model-platform compatibility](2026-10-24-v2-model-platform-compatibility.md), [ADR0110 proposed](../../adr/0110-shared-model-catalog-keeps-v2-execution-authority.md). [Crosswalk](../../research/2026-10-24-model-metering-crosswalk.md) and its 49 cases/three-file experiment supply the source evidence.

## Purpose and choices

Provide tested pure arithmetic for normalized physical-request facts without altering any executing consumer. The builder selects a private port of the pinned donor model/vocabulary/metering files, with one import adaptation, behind a validated host interface. This is smaller than importing the full catalog package or adding an external/workspace dependency, and preserves the tested donor algorithm instead of writing another calculator. There is no new price store, money ledger, provider router or metadata synchronization.

Stage 2A deliberately precedes the local Pricing/custom-price converter (2B). That converter will consume this kernel after separate exact-ID/unit/fallback tests. This kernel alone must not be called a safe budget bound, complete settlement, provider qualification or cloud integration.

## Interface

Module `lib.pricing.request_metering` exposes donor vocabulary types `Usage`, `PriceTable`, `Meter`, `PriceRow`, `Priced`, `Unpriced`, `UnpricedReason` and two host-guarded functions. These are internal Python types, not an HTTP/DB serialization contract.

`price_requests(table: PriceTable | None, requests: Sequence[Usage], *, entry_found: bool = True, estimate: bool = False) -> Priced | Unpriced`

- One price snapshot/currency applies to the explicit request sequence. Each element is one physical request, priced separately before summing/context-tier selection. Two equal usages are still two requests. This function does not recognize or deduplicate persisted attempt records.
- No public multiplier: the host calls donor arithmetic with multiplier 1. Explicit zero rates and a declared empty meter table can represent free pricing; missing table/usage does not become free through a multiplier override.
- Reject bool, negative and nonfinite quantities, rates/free allowances and nonfinite/negative resulting costs with ValueError before returning a priced result. Numeric input types are int/float; Decimal/string/object are not silently coerced. Reject duplicate meter identities or duplicate dimension declarations with ValueError to prevent double billing/ambiguous tables.
- Unknown currency/meter/dimension or an invalid recognized dimension value returns Unpriced(UNRECOGNIZED_TERMS). LOCAL stays outside paid arithmetic. No guessing unit conversion, tier alias, resolution default or model fallback.
- Snapshot request/table mappings and sequences before arithmetic; preserve original row order and valid declared wildcards/defaults. Do not modify source objects or retain their mappings in a result.
- Known count meters not priced by a table may be ignored as in the donor. A positive token meter without a rate remains unpriced. Every declared table meter must have reported usage (or raw text for characters): a missing axis, even when another is known, returns MISSING_RATE for actual usage and NO_USAGE_ESTIMATE for estimates. Explicit zero is reported usage.
- Empty requests return MISSING_RATE, or NO_USAGE_ESTIMATE when estimate=True. Unknown entry returns NO_ENTRY; missing table returns NO_PRICE_TABLE. Options must be actual bool values. Validate provided numeric facts even on unknown/free branches; no free-path bypass of invalid values.

`token_usage(*, input_tokens: int | None, output_tokens: int | None, cache_read_tokens: int | None = None, cache_write_5m_tokens: int | None = None, cache_write_1h_tokens: int | None = None, output_meter: str = "output_tokens") -> dict[str, float]`

- Input is the reported total including cache. Each non-None count must be a nonnegative exact int, excluding bool. Reject a known cache subtotal greater than a known total. Allowed output meters: output_tokens, image_output_tokens, audio_output_tokens.
- Preserve explicitly reported cache/output zeros. Missing values remain absent. Derive uncached_input_tokens only when the total and all three cache quantities are known; otherwise leave it absent. Thus input=100/output=50 with all caches unknown yields only output_tokens=50; explicit three cache zeros yields uncached_input_tokens=100 plus all reported zeros/output. This prevents donor clamping/default-zero behavior from inventing evidence.
- This normalization does not parse provider responses. A later qualified adapter must explicitly supply documented zero values when a cache class is known unused; it must not infer them from missing response fields.

Usage.text is str or None. Simultaneous raw text and explicit characters quantity are ambiguous and raise ValueError. Mapping keys must be strings. Invalid shape/type raises ValueError; recognizable but unsupported semantics stays unpriced as above.

## Ownership and exclusions

Keep `lib/pricing/{types,lookup,strategies}.py`, `lib/cost_calculator.py`, provider adapters, query/catalog, DB/schema, reservations, Ledger, qualifiers, frontend and production untouched. The port's model types are private arithmetic schema, not another owner of model identities or mutable prices. No consumer imports this module in this slice.

Float results retain reference-arithmetic semantics. No rounding into reservations, inferred hard-budget permission, LOCAL conversion, Vidu credit relabeling, retry policy, thought/output repartition, historical cost rewrite, price-table compilation or request-ID store is included. Source rate completeness and actual request facts remain prerequisites for later execution. The full repository currently has two unchanged baseline authority assertions failing; this spec does not authorize weakening them.

## Acceptance

Watch the missing port/guard tests fail, then pass; preserve all nine donor cases, adding explicit host guard/completeness/cache tests through the public interface. Run the affected pricing/config/catalog tests and all applicable static gates from CONTRIBUTING. One independent whole-slice review, one significant repair pass, defer minors with consequences. Verify original production source hashes unchanged. Record exact HEAD, port/source hashes, real commands/results and limits; no production or paid-route acceptance.

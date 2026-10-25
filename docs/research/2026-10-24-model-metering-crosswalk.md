# Model metering: dimension crosswalk and isolated core experiment

Status: offline research gate complete, not a production converter or cloud qualification. Host `b646708d62b8dcbb183a65ea5341f29db99e2a14`; ArcReel pin `258c7ff1ca1f103117cb4f757f7f09fd46cb8647`. This extends the [readiness note](2026-10-24-model-metering-readiness.md). [Exact cases and source hashes](../r2/evidence/R2_V2_MODEL_METERING_CROSSWALK.json) preserve the evidence.

## Fresh execution

49 asserted cases ran against the actual host strategies and unchanged pinned donor arithmetic: 26 exact arithmetic matches across nine pricing kinds; 13 legacy fallback versus strict unpriced observations; three required delegates; two independent custom-price observations; one character-count policy difference; three isolated adapter-method matches and one confirmed adapter difference. These counts are new evidence, not a rerun of the earlier 22 cases. No network connection/name-resolution attempts were made; the probe blocks both operations. The initial fixture was rejected by the donor validator because video durations were absent; the corrected declared fixture completed all 49 cases. No product source changed.

| Host representation | Tested donor representation | Limit |
|---|---|---|
| PerToken | uncached_input_tokens/output_tokens, independent rates per million | Missing usage is unpriced; cache/reasoning rates cannot be invented |
| PerImageFlat | output_images | Count each actual image |
| PerImageByResolution | output_images + resolution | Explicit 1K/2K/4K, including zero price; unknown/missing resolution differs from legacy fallback |
| PerImageOpenAIToken | separate image/text token meters | Actual token quantities remain distinct |
| Its `(quality,size)` reference table | output_images + quality + resolution label retaining exact WxH | Representation feasibility only; use actual size facts, preserve old reference fallback separately |
| PerSecondMatrix | output_seconds + resolution/audio | Explicit free rate survives; unknown resolution differs from legacy fallback |
| PerSecondTiered | output_seconds + quality/audio, quality from local resolved mode | Do not reinterpret quality mode as service throughput tier |
| PerVideoBucket | requests + exact resolution/duration | Nearest bucket is legacy policy, not linear seconds or an implicit strict fallback |
| PerTokenVideo | video_tokens + service_tier/audio | The pinned Ark caller maps default to standard only when that wire field exists; this is not a global tier alias |
| PerCharacter | characters, raw text count | CJK-double remains explicit opt-in; raw `中文ab` counts 4, opt-in counts 6 |
| ViduDelegate | existing credits-to-CNY owner | Credits 0 and 32 retain 0 and 1 CNY; no relabeling as tokens |
| LOCAL | existing run/local authority | No paid USD/CNY coercion |
| Custom input/output prices | independent .45/1.25 rates in USD/CNY | No single channel multiplier or price migration |

## Actual donor call-surface comparison

The pinned Ark `metered_usage` maps `default` to `standard` via `_CATALOG_SERVICE_TIERS` and omits its service-tier dimension when `_accepts_service_tier(model)` is false. Current host `_submit` likewise omits the actual wire field for unsupported model families. A future profile must use actual request facts; copying the selector string into billing is insufficient.

The pinned Kling method body, isolated from its exact AST without constructing a backend, resolves `1080p + std` to `pro`. The actual local `KlingVideoBackend._resolve_mode_from` resolves that input to `std`. Three other fixtures match. Therefore the donor mode resolver is not a behavior-preserving replacement. Its current metered_usage also derives resolution from effective mode and audio from effective output facts; those are useful references, not permission to replace local execution or price tables. This comparison does not exercise the complete donor backend or live API.

Sources: [pinned Ark caller](https://github.com/ArcReel/ArcReel/blob/258c7ff1ca1f103117cb4f757f7f09fd46cb8647/lib/backends/video_backends/ark.py#L207), [pinned Kling caller](https://github.com/ArcReel/ArcReel/blob/258c7ff1ca1f103117cb4f757f7f09fd46cb8647/lib/backends/video_backends/kling.py#L340), [core vocabulary](https://github.com/ArcReel/ArcReel/blob/258c7ff1ca1f103117cb4f757f7f09fd46cb8647/packages/arcreel-catalog-core/src/arcreel_catalog_core/vocabulary.py), and local `lib/pricing/strategies.py`, `lib/video_backends/kling.py`, `lib/video_backends/ark.py`, `lib/vidu_shared.py`. Source bytes/hashes are in the evidence packet; no live web/provider facts are inferred.

## Smallest tested import surface

An isolated standard-library-only package copied core `model.py` and `vocabulary.py` byte for byte, plus `metering.py` with its one package import replaced by two relative imports. The unchanged original nine donor tests passed, exit 0. Test-only import shims refer to those same ported types. The experiment installed no package and imported no complete catalog dataset/composition/runtime.

This establishes a feasible three-file private source port, not a production backport acceptance. A future port must retain its source manifest and pass host import/type/static gates. Its public guard must validate numeric facts, snapshot mappings and preserve unknown usage; the donor nine tests do not supply those guarantees. Full core-package vendoring would carry readers/dataset/writer functionality that this arithmetic slice does not need. A new external/workspace dependency would expand packaging and lockfile scope without a demonstrated runtime benefit here. The proposed smallest port is the builder's recommendation, not sponsor approval of deployment.

## Decision and next gate

Prepare stage 2A as a guarded pure metering kernel using this private port. Keep stage 2B local-price conversion separate: the 49 cases demonstrate selected representations and policy differences, not an exhaustive converter. Existing CostCalculator, Ledger, reservations, adapters, catalog and historical costs remain untouched.

The next implementation must test missing-versus-zero and partial usage, reject invalid numeric facts, and avoid silently treating unknown cache amounts as zero. Float reference arithmetic does not establish a conservative money bound; actual budget precision/reservation integration, request identity/dedupe and provider usage parsing remain later gates. Existing two whole-backend authority-test failures remain recorded; this research does not resolve or rerun them.

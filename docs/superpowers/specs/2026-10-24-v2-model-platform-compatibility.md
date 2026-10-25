# V2 model platform: compatibility specification

Status: design prepared from the sponsor-selected reuse-first direction; implementation pending. ADR: [0110, proposed](../../adr/0110-shared-model-catalog-keeps-v2-execution-authority.md). Research: [source comparison](../../research/2026-10-23-v2-system-wide-model-reuse.md). Source baseline `b019d87d64d8fe145a3dd1d932ae16861aa2006c`; deployed tag remains `r2-v2.0.6`. Donor pin `258c7ff1ca1f103117cb4f757f7f09fd46cb8647`.

## 1. Intent and boundaries

A creator can select suitable models from multiple providers across text/vision, image, video, audio and Agent. Shared management means consistent facts, identity, explanations and cost evidence; it does not mean one generic network request or a universal Agent runtime. Start from current V2 contracts and a pinned ArcReel donor, not an additional provider framework.

The current step produces an ADR, compatibility crosswalk, executable offline spike and a bounded first-slice plan. No production code, credential, DB schema, deployed tag or live provider call changes. M9/M10 stay paused. Earlier Gemini-only spec/plan remain preserved drafts and are not the implementation entrypoint.

## 2. Fact ownership and reusable modules

| Concern | Existing owner/interface | Proposed use | Explicit limit |
|---|---|---|---|
| Provider definitions | `lib/config/registry.py:ProviderMeta` | Retain credential fields, protocol/config and concurrency | Catalog must not create a new credential store |
| Builtin model facts | `ModelInfo`, `model_info_for`, `default_model_for_provider` | Project through shared query first | Preserve hidden/default/API name; no upstream sync |
| Custom model facts | `CustomProviderRepository`, `CustomProviderModel`, endpoint resolution | Project existing rows using a caller-owned read session | Preserve IDs, enabled/default, endpoints, overrides and independent prices |
| Resolve selected model | `ConfigResolver`, `ProviderModel`, text tiers/media buckets | Keep current precedence | Query never chooses a replacement model |
| Build backend | `assemble_backend`, `ProviderSpec`, `ENDPOINT_REGISTRY` | Keep construction and qualification | A facts query must never construct a provider SDK client |
| Actual protocol capabilities | `VideoCapabilities`, endpoint specs and ComfyUI bindings | Query pure declarations/confirmed bindings | Do not invent supported values when lookup fails |
| Model entry facts and units | ArcReel `lib/catalog/query.py`, `packages/arcreel-catalog-core` | Selectively port relevant types/query vocabulary after packaging review | Model-entry matching is descriptive, not an identity migration |
| Request metering | ArcReel `lib/billing/metering.py` | Candidate pure arithmetic behind existing calculator/ledger | Vidu credits, LOCAL and legacy fallback keep compatibility delegates |
| Cost/budget | `CostCalculator`, `Ledger`, `BudgetReservationRepository`, `budget_guard` | Keep authoritative writes and currency scopes | A priced result is not proof of a safe pre-submit upper bound |
| Provider attempts | Existing M7 execution layer, StoryAttemptSink, Agent connection budget | Crosswalk before extracting common facts | No parallel attempt/money ledger |
| Qualification | `paid_routes`, `route_qualifications`, assembly/cache rechecks | Keep existing authority; extend scope explicitly later | Generic text qualification does not qualify every text workload |
| UI | `/system/config/model-candidates`, `useModelCandidates`, provider catalogs | Consume a shared facts projection in a later slice | Candidate display is advisory, not an admission token |

`CapabilityMatcher` remains the production-method inventory/matcher from M4; it does not become a global provider router just because it has a similar vocabulary. OpenMontage ranking and DramaClaw egress lifecycle are source references, not additional runtime dependencies.

## 3. Identity and selection

- Use existing `ProviderModel(provider_id, model_id)` as the execution/configuration identity. A provider-model route additionally depends on endpoint, normalized base URL, credential configuration binding and adapter version. Do not add raw credential material to a route/view object.
- Builtin registry key and API model name remain distinct, including amphibious model entries. No string splitting that assumes the first slash in an arbitrary external model name identifies its manufacturer; preserve existing pair serialization and parsing.
- A catalog entry may group display facts only with a proven mapping. Unmatched entries stay unmatched. Shared names across accounts/providers do not merge routes or prices.
- Existing hidden models remain available for historical lookup but absent from selectable defaults. Disabled custom models remain distinguishable from deleted/unknown models.
- Local legacy loader falls back to its enabled default when an explicit custom model is invalid (`lib/custom_provider/loader.py:47–105`). Existing release gate checks the backend actually constructed; tests confirm that qualification of the requested model does not open the fallback model. Keep this observed behavior in the compatibility layer. New exact-selection execution must opt into strict behavior and cannot inherit fallback accidentally.
- Text selection retains project tier > project default > global tier > global default > auto-resolution; media retains the equivalent bucket precedence. Story writer/judge is a per-run choice. Agent model selection stays separate from text tiers.

## 4. Price and usage semantics

### Existing values

Keep custom `price_unit`, `price_input`, `price_output`, `currency` exactly; independent input/output ratios cannot always be represented by one channel multiplier. A missing price remains missing, not zero or the official channel price. Already settled `ApiCall.cost_amount`/currency are immutable history for this conversion.

The first query slice returns price facts with provenance but does not replace `lookup_pricing` or `CostCalculator`. Future stricter admission uses a normalized result with distinct priced, explicitly free and unpriced states. Legacy fee estimation is retained behind its old interface until a tested conversion is activated.

### Unit crosswalk

| Legacy quantity/shape | Donor unit representation | Conversion scope |
|---|---|---|
| PerToken | uncached input + cache read/write + output tokens, rates per million | Only split cache when reported with documented provider semantics |
| PerImageFlat / PerImageByResolution | output_images and selected resolution | Exact dimensions; no fallback invented from catalog aliases |
| PerImageOpenAIToken | separate image/text input/output quantities | Preserve actual payload/result dimensions and all billed requests |
| PerSecondMatrix / PerSecondTiered | output_seconds plus resolution/audio/tier dimensions | Preserve tier normalization and intentional legacy fallbacks separately |
| PerVideoBucket | requests with exact resolution/duration price bucket | Not linear seconds pricing; nearest-bucket legacy behavior needs its own fixture |
| PerTokenVideo | video_tokens per million | Not text tokens or seconds |
| PerCharacter | characters per ten thousand | Keep current counting; do not enable CJK-double unless configured/verified |
| ViduDelegate | provider credits with current conversion | Donor vocabulary has no credits unit; retain delegate rather than relabel as tokens/requests |
| Run currency LOCAL | local execution/no monetary billing marker | Donor currency vocabulary is USD/CNY; keep LOCAL in run authority, not a paid USD conversion |

### Request evidence and admission (later slices)

A logical task/run can contain multiple requests. Capture per-request provider/model identity, attempt reference, request digest, termination/dispatch outcome, usage and which fields are unknown. Record cache, thought and output usage without double counting. Count/schema re-ask/child requests are separate budgeted side effects according to each profile. Validate all quantities as finite/nonnegative and validate units before invoking donor arithmetic.

Use existing reserve/claim/reconcile; do not authorize future requests from post-response cost logging. A profile must declare its input count method, margin if estimated, output/thought cap, price/unit source and maximum request count. A missing/unreliable bound prevents new paid hard-budget execution. At settlement, preserve unknown usage and the reservation; do not release to zero merely because a call failed or returned no usage. The host bounds authorizations under its qualified price/profile assumptions; fee estimates are not provider invoices.

Money reservation uses the existing currency precision and a conservative upward conversion; historical floats are not rewritten. If a reported amount exceeds the reserved authorization, record it and block further automatic spending; never cap the recorded amount to hide overspend. Crash/restart reconciliation must retain uncertainty and be tested with actual repository transactions before activation.

## 5. Timing, qualification and compatibility

| Consumer | Freeze/revalidation boundary | Must survive |
|---|---|---|
| General text/vision | Existing resolver/assembly; revalidate stronger profile at paid dispatch | Per-task tier, schema behavior and ledger identity |
| Image/audio | Existing lane resolution and assembly/admission | Reference image and voice semantics, actual executing model |
| Video | Latest facts before submit; persisted execution checkpoint/job identity after submit | Poll/resume never resubmits or silently resolves a different model |
| Story | Approved immutable brief and per-node fingerprints | Version1 serialization/digest and old resumes; writer/judge identities |
| Agent | Session-start credential/options and per-connection reservation | Existing session resume, hooks/tools/permissions and ADR0093 cap |
| Discovery/connectivity | Existing metadata/setup path | A successful list/discovery is not generation/profile qualification |
| Trial | Existing separate setup policy | Shared catalog does not silently open release trial routes |

Current qualification key includes route/model/config binding/adapter version and expiry. Stronger workload evidence must be versioned and recorded using this existing authority. Extend its record schema/readers with backwards-compatible scoping if needed: old records qualify only their old workload. Keep changes to actual request-shaping facts separate from throughput tuning. A catalog update cannot itself issue a qualified record.

Do not insert defaults/new metadata fields into old StoryBrief then recompute a different approval digest. Retain the exact version1 reader and digest; a later cloud brief requires an explicit versioned approval envelope covering the route, price/budget/profile facts. New envelope readers and old-task recovery need golden and tamper tests, not just successful JSON parsing.

## 6. Eligibility presentation

A candidate has independent axes: configuration/enabled state; hard capability support (supported/unsupported/unknown); qualification (scope/version/expiry); freshness/availability observations; price/estimate status. Budget admission is `not evaluated` in the catalog view, not `allowed` based on cached observations. Do not collapse these axes into a new boolean `ready` that would overrule existing gates.

A user can see why a chosen route is unavailable. Missing support for a hard requirement is not interpreted as supported. Existing broad default selectors retain their purpose and existing fields; task-specific choices may additionally filter/disable candidates. UI never performs a secret-bearing config query or reimplements capability rules. Admission remains server-side and revalidates after queueing/config changes.

## 7. Compatibility evidence produced 2026-10-24

Source baseline b019d87d; donor pin above. Probe imports exact pinned donor module/core from the prior extraction and the current legacy strategy/calculator. No provider requests, installation or DB writes by the probe.

- 22 explicit cases; 12 arithmetic matches across9 pricing shapes, including separate custom input/output rates in USD/CNY.
- Observed donor behavior: explicit free is priced0; missing usage/entry/estimate produce distinct unpriced reasons; cache quantities are disjoint; two explicit requests sum their own costs.
- Confirmed gaps: LOCAL is outside donor currency vocabulary; Vidu credits outside meter vocabulary; legacy `CostCalculator` rewrites zero duration to8 seconds while its pure per-second strategy prices zero as0. The conversion must not accidentally change this wrapper behavior for old consumers.
- A synthetic old StoryBrief roundtrip retains its current digest; the serialized fixture is saved. This is a golden baseline, **not** proof a future schema migration is compatible.
- Existing targeted suite: pricing unit tests + backend-loader tests + integration release-binding tests. Actual result is recorded in the evidence JSON; these use disposable fixtures, not production.

Limits: chosen exact price dimensions, not every fallback or every live provider; no concurrent budget, alias migration, catalog composition, new-UI or cloud literary acceptance. The previous 128+9 results belong to the previous research gate and are not reported as rerun here.

## 8. Implementation slices and acceptance

1. **Read-only query:** project existing owners with no persistence/network/backend construction. Prove identity/default/custom-price parity and empty/unknown states; preserve existing endpoint responses. This is the only implementation slice covered by the attached plan.
2. **Pinned donor metering bridge:** dependency/package/import crosswalk, every legacy shape/fallback, unknown values, credit/LOCAL delegates, historical price stability, duplicate requests and budget-precision evidence. No auto sync or price migration.
3. **Single-request execution profile:** existing text/vision backends report sufficient facts per physical request; explicit retry/unknown policy, per-request reservation, stronger workload qualification and backwards-compatible readers. Real SQLite/PostgreSQL concurrency evidence as required by the touched authority paths.
4. **Ollama/Gemini story consumer:** keep generic provider behavior below story, reuse writer/judge routing and common output validation; prove count/context/output/thought/schema/CJK/truncation/unknown/recovery cases. Claude/Grok follow the same verified seam, not vendor-specific selectors scattered through features.
5. **UI and remaining families:** switch read consumers incrementally; qualify each media/Agent lifecycle before activation. Agent-compatible models require Agent runtime compatibility/cap evidence, not only text-generation support.

At every stage compare requested and actual route, ensure catalog display grants no permission, and record exact source/commands/results. Production remains the released version until normal release evidence and approval. No migration or production deployment is authorized merely by the existence of this spec.

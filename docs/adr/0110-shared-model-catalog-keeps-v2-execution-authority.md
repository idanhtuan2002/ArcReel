---
status: proposed
---

# Share model facts and request metering while retaining V2 execution authority

The sponsor expanded Gemini integration to every part of V2 that uses models, including other cloud providers. The [reuse review](../research/2026-10-23-v2-system-wide-model-reuse.md) identifies existing backend assembly, resolver, pricing, budget, qualification and recovery modules; building a second provider platform would duplicate them. We propose one model-facts query and common request-usage vocabulary, selectively reusing ArcReel `258c7ff1ca1f103117cb4f757f7f09fd46cb8647`, behind those existing interfaces. Execution remains specific to text/vision, image, video, audio and Agent.

This is a proposed architectural direction and a compatibility specification, not production activation. The user authorized continuing the design after the source review; runtime policy changes below still need their implementation and acceptance evidence. Local ADR numbers and upstream ADR numbers are independent.

## Proposed rules

1. **One owner per fact.** Existing `PROVIDER_REGISTRY` and custom-model DB rows remain authoritative in the first implementation slice. A shared query projects them; it is not a second writable catalog. Later source replacement requires parity and an explicit cutover. Model facts may come from a pinned ArcReel catalog snapshot, protocol facts remain in backends, and ComfyUI capabilities remain derived from confirmed bindings. Model metadata is not execution permission.
2. **Keep provider/model identities.** Preserve `ProviderModel(provider_id, model_id)`, API model names, custom-provider IDs, task tiers, media buckets, defaults and project precedence. A shared catalog entry is descriptive; two providers/accounts serving the same model remain two routes. Alias matching never silently renames settings, rewrites an approved brief or substitutes a model.
3. **Reuse construction and execution.** `assemble_backend` remains the backend construction seam. Its paid-route gate, including on cache hits, stays in place. Video retains job/checkpoint recovery; audio retains voices/character usage; Agent retains session, tools, permission hooks and its credential storage. Direct Claude text generation and the Claude Agent SDK are separate execution contracts.
4. **Preserve prices and history.** Keep independent custom input/output prices and currency, code-declared builtin prices and settled historical costs. No donor migration that discards custom prices, no automatic catalog/price sync and no multiplier-only conversion. `ViduDelegate` and run currency `LOCAL` retain their semantics until independently represented and tested.
5. **Normalize facts per actual request.** Prefer donor `Usage`/`price_requests` to normalize amounts and cache units. Validate finite, nonnegative, nonoverlapping quantities first. Every actual retry, schema re-ask, child request and count request must fit its execution profile and be accounted for. Settlement still uses V2 repositories and reservations; no second money ledger. An unknown outcome retains its authorized reservation; missing usage is not zero.
6. **Separate legacy compatibility from stricter new execution.** The first slice only projects facts. Legacy custom-model fallback and reference-fee behavior are characterized, not silently changed globally. New explicit cloud/story selection must fail if its exact route is unavailable, refuse unknown price/bounds before paid dispatch, and expose usage uncertainty. Default resolution when no model was selected is distinct from replacing an explicitly selected model.
7. **Qualification is workload-sensitive.** The existing adapter/version + live route binding remains necessary. It is insufficient to infer story count/schema guarantees from a generic text canary. A stronger workload profile must have separately recorded, versioned evidence through the existing qualification authority; absent profile evidence never opens the new workload. Old records retain their original scope. Agent restrictions in ADR0093 remain in force until a separately verified budget design replaces them.
8. **A common selector is a read model.** Reuse and extend existing candidate/UI projections. Show compatible choices and concrete reasons for unavailable choices; actual admission revalidates current facts/config/qualification/budget before dispatch. Ranking is advisory and never authorizes fallback or changes the selected provider.

## Existing ADRs and transition

Preserved: ADR0008/0016/0017/0027/0037 credential rules; ADR0013/0038 model/channel facts and identity; ADR0039/0049 assembly/resolution; ADR0051/0054/0055 defaults, buckets and video execution timing; ADR0091/0093 release admission; ADR0099/0100/0101 ComfyUI. ADR0109 remains proposed, with writer/judge routing already implemented.

ADR0009 remains effective for the first slice: prices stay code-declared or in existing custom-price columns. A future runtime-editable or synchronized catalog needs an explicit amendment, not an implication of this ADR. ADR0014/0044/0047 retain legacy behavior; a new per-request execution profile must explicitly constrain retries and output bounds without globally changing unrelated consumers. No old ADR is marked superseded by this proposed document.

## Considered options

- Add Gemini-specific selectors and gateways per feature: duplicates policy and repeats the same integration problem for Claude/Grok.
- Replace the host with an external gateway or merge upstream wholesale: adds another runtime/authority and brings incompatible migration, credential, pricing and release semantics.
- Keep V2 authority, selectively reuse catalog/metering and preserve media-specific backends: chosen as the proposal because it reuses working seams and permits incremental compatibility checks.

## Consequences

The first code milestone is a read-only model-facts query; it does not enable new cloud routes. Metering conversion, stronger per-request budgets, cloud story execution and shared UI eligibility follow as separately testable slices. The [compatibility specification](../superpowers/specs/2026-10-24-v2-model-platform-compatibility.md) fixes their boundaries, cases and acceptance gates. The [first-slice plan](../superpowers/plans/2026-10-24-v2-model-catalog-read-model.md) does not authorize the later runtime/database changes.

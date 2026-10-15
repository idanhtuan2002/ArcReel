RESEARCH COMPLETE — READY FOR M9 ADR/DESIGN EVALUATION

# R2 M9 Opportunity and Research Intelligence — comprehensive research

**Date:** 2026-09-14
**Scope:** local authoritative documents, current R2 source, two pinned donor
checkouts, and current first-party YouTube, Google Trends, and TikTok API/policy
documents. This artifact recommends an architecture for later ADR evaluation;
it does not itself accept that architecture.
**ArcReel source lineage inspected:**
`25f19b12ca77b59dfea730ef8d91eacca9fdeda1` (`design/r2-m5b-narrative-context`).
**Donor pins:** OpenMontage
`08e2151fa02de28a5d6a312b3d575692bf147ad7`; Kalinga Shorts Factory
`e4b5a2173ca03d365aad565a89fcc43159b44f9b`; Huohuo Drama
`f104b853b3563e124d9cde25f9331d323fb483b9` (reused from the accepted M8
research lineage as a bounded `zh-shuang` fixture).
**Authorization boundary:** research and design input only. This pass made no
platform call, used no credential, ran no migration, and authorizes no
implementation or production operation.

## 1. Executive result

M9 should be a host-integrated, evidence-first opportunity module, not a trend
scraper or a second factual system. Its minimum durable flow is:

```text
SourceQuery
  -> one or more immutable SourceSnapshot revisions
  -> lossless source-native observations
  -> explicitly policy-based derived signals
  -> immutable OpportunityCandidate revision
  -> Human Greenlight decision
  -> Canvas exploration through the M8 API

source/evidence selected for factual use
  -> existing Factual Authority
  -> SourceRecord / EvidenceRecord / ResearchPack / ClaimLedger
```

The two arrows at the end are different authority transitions. A Human
Greenlight selects a creative opportunity; it does not verify any claim, create
an approved `ResearchPack`, mutate Canon, or select production truth. This is
normative in accepted ADR-0080
([lines 28–41](../adr/0080-post-m8-north-star-closed-loop.md#L28-L41),
[92–99](../adr/0080-post-m8-north-star-closed-loop.md#L92-L99)).

The strongest reusable local primitives are the existing factual contracts and
the M8 revision/digest/CAS/idempotency patterns. The donors contribute research
vocabulary and adversarial fixtures. Neither donor contributes an authority-safe
Greenlight or sufficiently strong provenance contract.

## 2. Evidence status and hierarchy

### 2.1 Accepted authority

ADR-0080 is accepted at ArcReel commit
`25f19b12ca77b59dfea730ef8d91eacca9fdeda1`. The machine-readable acceptance
record binds reviewed candidate
`016e094689b5e59666ee879c33bdc194caa415a0`, accepted ADR SHA-256
`53f9d9986723df587cf52fd5b34b78c0d440809d6ba057df1625d179de070aa8`,
contract SHA-256
`047551f6a198bb1a310292aec389d0c3828d997e220effcf7ac2c1c2f6369ea4`,
two independent PASS reviews, and no required skips or material unknowns
([acceptance record lines 1–43](../r2/evidence/R2_POST_M8_ARCHITECTURE_ACCEPTANCE.json#L1-L43)).

The acceptance contract fixes M9 before M10–M12, one active implementation and
review packet, ArcReel as host and PostgreSQL as durable authority store
([lines 17–34](../r2/evidence/R2_POST_M8_ARCHITECTURE_ACCEPTANCE_CONTRACT_2026-09-14.json#L17-L34)).
It assigns Human Greenlight to a custodian defined by M9, keeps factual claims in
existing Factual Authority, keeps learning lifecycle in M8, and requires M9 to
freeze `SourceQuery`, `SourceSnapshot`, lossless normalization,
`OpportunityCandidate`, Greenlight, the Factual Authority bridge, and composite
signal policy basis
([lines 36–80](../r2/evidence/R2_POST_M8_ARCHITECTURE_ACCEPTANCE_CONTRACT_2026-09-14.json#L36-L80)).

Architecture acceptance permits design/planning, not code, migrations,
credentials, provider calls, publication, runtime activation, or production
approval
([lines 196–215](../r2/evidence/R2_POST_M8_ARCHITECTURE_ACCEPTANCE_CONTRACT_2026-09-14.json#L196-L215),
[233–242](../r2/evidence/R2_POST_M8_ARCHITECTURE_ACCEPTANCE_CONTRACT_2026-09-14.json#L233-L242)).

### 2.2 Intent sources, not authority

The original vision asks for an opportunity-to-market-to-learning loop while
humans retain final creative and release decisions
([Product Vision lines 8–16](r2-origin/00_PRODUCT_VISION.md#L8-L16),
[46–83](r2-origin/00_PRODUCT_VISION.md#L46-L83)). It explicitly describes the
vision document itself as non-authoritative
([lines 1–4](r2-origin/00_PRODUCT_VISION.md#L1-L4)). Likewise, the system
requirements are rationale, not authority
([System Requirements lines 1–6](r2-origin/02_SYSTEM_REQUIREMENTS.md#L1-L6)).
They are useful to recover the desired M9 behavior but cannot override ADR-0080.

The rationale calls for separate commercial and creative opportunity dimensions,
originality and feasibility rather than trend copying, per-fact provenance, and
separation of factual and fiction truth
([System Requirements lines 12–24](r2-origin/02_SYSTEM_REQUIREMENTS.md#L12-L24)).
Its proposed weighted formula is therefore a design question, not permission to
collapse all signals into one score. Accepted ADR-0080 is stricter: every
composite signal must name inputs, transformation and policy basis, and a
provider-derived composite is blocked unless the particular use is permitted
([ADR-0080 lines 145–162](../adr/0080-post-m8-north-star-closed-loop.md#L145-L162)).

### 2.3 Graph and direct-source coverage

The codebase graph was checked at Tier 2, project
`home-anhtuan-content-production-os`, generation `2026-09-14T10:43:55Z`, full
mode. It found `ResearchPack`, `SourceRecord`, `EvidenceRecord`, `Claim`, and
`ClaimLedger` in `r2/contracts/factual.py`. Coverage checks reported
`no_recorded_issue` and `metadata_match` for the cited local files. This is a
best-effort signal, not proof of completeness; the exact sources cited here were
also read directly. Donor checkouts are outside that graph and were read from
their pinned Git objects.

## 3. Existing authority seams M9 must preserve

### 3.1 Factual Authority is already typed

At current ArcReel HEAD, `SourceRecord` binds a source identity, type, origin,
capture time, fingerprint and provenance; `EvidenceRecord` binds source ref,
locator, captured content/fact, type, time and provenance
([`factual.py` lines 29–48](../../r2/contracts/factual.py#L29-L48)).
`ResearchPack` already carries a versioned topic/scope, sorted source and evidence
refs, synthesis, uncertainties, open questions and provenance
([lines 51–63](../../r2/contracts/factual.py#L51-L63)). `Claim` has explicit
confidence/status and rejects `VERIFIED` with no evidence; `ClaimLedger` rejects
duplicate claim IDs
([lines 66–94](../../r2/contracts/factual.py#L66-L94)).

Direct implication: M9 should submit selected snapshot evidence through an
adapter into these existing contracts and their authority service. It must not
invent `OpportunityFact`, treat a Greenlight as `ClaimStatus.VERIFIED`, or write
a parallel ResearchPack store.

The current contract file alone does **not** prove repository/service rules for
referential integrity, source/evidence immutability, exact version selection, or
transactional publication of an approved ResearchPack. These are explicit M9
design unknowns, not inferred guarantees.

### 3.2 M8 mechanics are reusable; M8 authority is not transferable

The accepted M8 design defines immutable `ExplorationRevision` payloads with
parent revision, full lineage and payload digest, plus a separate `CandidateHead`
CAS version
([M8 design lines 187–239](../superpowers/specs/2026-09-13-r2-m8-canvas-learning-multiformat-design.md#L187-L239)).
Its preview binds exact candidate revision/digest, target, expected target/master,
impact digest, scope and a bounded expiry
([lines 240–308](../superpowers/specs/2026-09-13-r2-m8-canvas-learning-multiformat-design.md#L240-L308)).
Genesis/append/replay and promotion lock ordering are fail-closed and no
transaction spans network or media I/O
([lines 511–547](../superpowers/specs/2026-09-13-r2-m8-canvas-learning-multiformat-design.md#L511-L547),
[593–619](../superpowers/specs/2026-09-13-r2-m8-canvas-learning-multiformat-design.md#L593-L619)).

M9 should reuse these mechanics as a shared-kernel pattern or accepted deep
module, especially canonical digest domains, immutable revisions, independent
head CAS, scoped idempotent commands, replay/conflict distinction, short
transactions, and append-only receipts. It must not insert
`OpportunityCandidate` into M8's currently closed `CandidatePayload` union: that
union contains only Canvas, Spatial and Format candidates
([lines 443–460](../superpowers/specs/2026-09-13-r2-m8-canvas-learning-multiformat-design.md#L443-L460)).
An extension would require an accepted schema evolution; the safer default is an
M9-owned opportunity revision repository plus an explicit adapter that creates
an M8 `CanvasCandidate` after Greenlight.

M8's Learning contracts can be evidence inputs to M9. `LearningObservation`
preserves source/metric definition/window/raw digest/transformation/correction
and lineage; `LearningRecommendation` preserves evidence IDs, applicability,
exclusions, confidence, guardrails, lineage and expiry; Human disposition is a
separate `RecommendationDecision`
([lines 334–382](../superpowers/specs/2026-09-13-r2-m8-canvas-learning-multiformat-design.md#L334-L382)).
M9 may consume accepted recommendations or observations through an M8 read port,
but cannot rewrite them or create a second learning lifecycle. Recommendation
code itself has no production, Canon, Narrative, policy, routing or governance
write port
([lines 549–591](../superpowers/specs/2026-09-13-r2-m8-canvas-learning-multiformat-design.md#L549-L591)).

## 4. Donor evidence

### 4.1 OpenMontage research surface

**Pin:** `calesthio/OpenMontage@08e2151fa02de28a5d6a312b3d575692bf147ad7`.

The Research Director is explicitly placed before creative choices, scripts and
spend, and states that research does not make creative decisions
([source lines 1–17](https://github.com/calesthio/OpenMontage/blob/08e2151fa02de28a5d6a312b3d575692bf147ad7/skills/pipelines/explainer/research-director.md#L1-L17)).
It separates scoping, landscape, trending pulse, data/evidence, audience mining,
expert voices, visual references, angle synthesis and bibliography
([lines 53–120](https://github.com/calesthio/OpenMontage/blob/08e2151fa02de28a5d6a312b3d575692bf147ad7/skills/pipelines/explainer/research-director.md#L53-L120),
[122–251](https://github.com/calesthio/OpenMontage/blob/08e2151fa02de28a5d6a312b3d575692bf147ad7/skills/pipelines/explainer/research-director.md#L122-L251)).

The `research_brief` schema contributes useful vocabulary: existing content,
saturated angles, underserved gaps, timeliness, source-rated data points,
audience questions/misconceptions, angle candidates grounded in findings, and a
bibliography
([schema lines 1–55](https://github.com/calesthio/OpenMontage/blob/08e2151fa02de28a5d6a312b3d575692bf147ad7/schemas/artifacts/research_brief.schema.json#L1-L55),
[100–163](https://github.com/calesthio/OpenMontage/blob/08e2151fa02de28a5d6a312b3d575692bf147ad7/schemas/artifacts/research_brief.schema.json#L100-L163),
[181–244](https://github.com/calesthio/OpenMontage/blob/08e2151fa02de28a5d6a312b3d575692bf147ad7/schemas/artifacts/research_brief.schema.json#L181-L244)).

However, URL strings and a single `research_date` do not preserve an immutable
query, response snapshot, pagination/coverage, capture digest, provider-native
identity, retrieval semantics, correction/deletion lineage, or policy basis.
Its `engagement_signal` is an untyped string
([schema lines 24–41](https://github.com/calesthio/OpenMontage/blob/08e2151fa02de28a5d6a312b3d575692bf147ad7/schemas/artifacts/research_brief.schema.json#L24-L41)).
Minimum item counts are workflow defaults, not evidence that three entries or
five sources are universally sufficient.

The donor `decision_log` preserves alternatives, scores, reasons, rejected
reasons, visibility, approval and confidence
([schema lines 11–99](https://github.com/calesthio/OpenMontage/blob/08e2151fa02de28a5d6a312b3d575692bf147ad7/schemas/artifacts/decision_log.schema.json#L11-L99)).
This is valuable review-fixture vocabulary, but a mutable-looking list plus
`user_approved: boolean` does not provide a Human Greenlight issuer, exact
candidate/snapshot closure binding, expiry, supersession, CAS or replay receipt.

### 4.2 Kalinga research and topic suggestions

**Pin:** `desaultkhan/Kalinga-Shorts-Factory@e4b5a2173ca03d365aad565a89fcc43159b44f9b`.

Kalinga demonstrates a small adapter registry, run-specific creator brief, a
manual facts path, optional Wikipedia grounding, and cached `facts.json`
([`research.py` lines 1–35](https://github.com/desaultkhan/Kalinga-Shorts-Factory/blob/e4b5a2173ca03d365aad565a89fcc43159b44f9b/pipeline/src/research.py#L1-L35),
[56–120](https://github.com/desaultkhan/Kalinga-Shorts-Factory/blob/e4b5a2173ca03d365aad565a89fcc43159b44f9b/pipeline/src/research.py#L56-L120)).
Its current-context helper explicitly asks for sourced bullets and returns no
result on failure
([lines 123–151](https://github.com/desaultkhan/Kalinga-Shorts-Factory/blob/e4b5a2173ca03d365aad565a89fcc43159b44f9b/pipeline/src/research.py#L123-L151)).
The LLM adapter requests per-fact confidence and hook angles
([lines 250–274](https://github.com/desaultkhan/Kalinga-Shorts-Factory/blob/e4b5a2173ca03d365aad565a89fcc43159b44f9b/pipeline/src/research.py#L250-L274)).

These are useful fixture shapes and orchestration failure cases, not direct M9
authority. `ensure()` trusts an existing path, writes mutable JSON directly, and
does not bind exact query, response, content digest, identity, author, policy or
revision. Several failures are intentionally swallowed; a failed Wikipedia
summary may truncate the injected text, while the full extract is stored on the
filesystem
([lines 92–120](https://github.com/desaultkhan/Kalinga-Shorts-Factory/blob/e4b5a2173ca03d365aad565a89fcc43159b44f9b/pipeline/src/research.py#L92-L120),
[192–247](https://github.com/desaultkhan/Kalinga-Shorts-Factory/blob/e4b5a2173ca03d365aad565a89fcc43159b44f9b/pipeline/src/research.py#L192-L247)).

`suggest_topics()` is a valuable product-behavior fixture: it uses channel/show
premise, an optional creator seed and prior queued/produced topic strings, asks
for researchable subjects, then performs simple output sanitization and exact
case-insensitive duplicate rejection
([`creative.py` lines 1274–1322](https://github.com/desaultkhan/Kalinga-Shorts-Factory/blob/e4b5a2173ca03d365aad565a89fcc43159b44f9b/pipeline/src/creative.py#L1274-L1322)).
But `[{topic, why}]` contains no evidence, score dimensions, uncertainty,
provenance, candidate revision or authority. Near-duplicate prevention exists
only in the prompt, not deterministic validation. The CLI persists an
`ideas.json` timestamp and then independently appends a chosen string to a CSV
queue
([`kalinga.py` lines 649–687](https://github.com/desaultkhan/Kalinga-Shorts-Factory/blob/e4b5a2173ca03d365aad565a89fcc43159b44f9b/pipeline/src/kalinga.py#L649-L687),
[`daily.py` lines 19–60](https://github.com/desaultkhan/Kalinga-Shorts-Factory/blob/e4b5a2173ca03d365aad565a89fcc43159b44f9b/pipeline/src/daily.py#L19-L60)).
That path must not become M9 Greenlight or Canvas authority.

Kalinga's history channel is a profile fixture, not a universal M9 rubric. It
requires factual specificity and honest uncertainty for a roughly 60-second
history format
([`channel.yaml` lines 18–38](https://github.com/desaultkhan/Kalinga-Shorts-Factory/blob/e4b5a2173ca03d365aad565a89fcc43159b44f9b/channels/history-shorts/channel.yaml#L18-L38),
[75–107](https://github.com/desaultkhan/Kalinga-Shorts-Factory/blob/e4b5a2173ca03d365aad565a89fcc43159b44f9b/channels/history-shorts/channel.yaml#L75-L107)).
It does not prove requirements for fiction, Chinese short drama, long-form, or a
different audience.

Huohuo Drama contributes one bounded Chinese short-drama fixture already
inspected for M8: chapter fields model time/place/cast, catalyst, desire,
obstacle, stakes shift, choice, conflict, emotional craft, ending question,
information delta and theme echo; its opening chapters additionally encode the
donor-specific `恨/爽/急/盼` and `爽型` vocabulary. M9 may reuse these fields to
describe a candidate's creative/profile fit and to build native-language
review fixtures. They are not market-demand observations, factual evidence, or
a universal law of Chinese drama, and no engagement or Greenlight score may be
inferred from their presence alone
([M8 research §6.2](2026-09-12-r2-m8-canvas-learning-multiformat-research.md#62-chinese-short-drama--爽文-fixture)).

### 4.3 Official provider/API evidence assessed on 2026-09-14

Provider access is a capability, not an assumed M9 dependency. Each source needs
an assessed policy basis, exact operation, credential class, permitted purpose,
freshness/retention/deletion rules, and a fail-closed availability state.

| Source capability | Verified first-party behavior | M9 classification |
|---|---|---|
| YouTube public inventory | `search.list` returns video/channel/playlist references; `videos.list` returns selected parts such as `snippet`, `statistics`, and `status`, costs one unit, and supports up to 50 results for applicable list modes. The default project allocation currently separates 100 `search.list` calls/day and 10,000 units/day for other endpoints. | **OPTIONAL ADAPTER.** Persist exact query/parts/fields, resource IDs, quota accounting, page state, retrieval time, response digest and missing/private/deleted results. Search rank is not completeness or popularity truth. |
| YouTube derived analytics | Derived metrics are generally prohibited, but YouTube now permits named classes such as custom scores/ratios, categorization and sentiment when the developer accepts the Analytics & Reporting amendment and complies with its conditions. Approved statistical/derived data may be retained up to 36 months; titles, creator names, descriptions and comment text still require the 30-day refresh/deletion treatment. | **DISABLED BY DEFAULT.** Every composite signal must bind proof of the applicable amendment/use case and distinguish R2-derived values from YouTube-native metrics. Absence, expiry or mismatch of that proof blocks derivation, not raw lossless normalization. |
| Google Trends API | The official API is still alpha with access limited to accepted testers. It advertises a rolling five-year window, daily/weekly/monthly/yearly aggregation, regional/subregional comparison and consistently scaled data. | **OPTIONAL/UNAVAILABLE BASELINE.** Never make M9 acceptance depend on access. Manual/import fixtures must exercise the same port; capability evidence records alpha approval and exact aggregation/scale semantics. |
| TikTok Research API | Commercial users, creators and advertisers are ineligible. Approved research projects currently receive 1,000 requests/day and up to 100,000 records/day; video-query search uses archived data, new videos may lag 48 hours, and statistics may lag 10 days. | **UNAVAILABLE FOR THE COMMERCIAL PRODUCT BASELINE.** Do not disguise product discovery as academic research or treat archived counts as current. Retain only as a separately approved research capability. |
| TikTok Commercial Content API | An approved application/research client and client token can query ads and public advertiser data. Pagination uses `search_id`/`has_more`; this is a commercial-content/ad corpus, not the organic TikTok universe. | **OPTIONAL ADS-CORPUS ADAPTER.** Label every observation `commercial_content`; never substitute it for organic trend or audience demand. |

The YouTube exception is intentionally modeled per signal rather than as a
global provider switch. A permitted channel ratio does not automatically permit
an unrelated opportunity composite, a different account, or retention of title
and comment text. Equally, the general prohibition must not erase a later
documented amendment. The evaluated capability and policy-document digests are
part of the candidate evidence closure.

The initial M9 design therefore needs a provider-neutral, no-network baseline:
Human-curated/imported sources and deterministic fixtures use the same query,
snapshot, normalization and policy contracts. Network adapters remain dormant
until the host supplies an opaque credential reference and current capability
evidence. This lets M9 ship useful opportunity research without pretending that
restricted APIs are available.

## 5. Reuse classification

| Surface | Classification | M9 use | Boundary / parity requirement |
|---|---|---|---|
| ArcReel `SourceRecord`, `EvidenceRecord`, `ResearchPack`, `Claim`, `ClaimLedger` | **DIRECT** existing host contract | Factual bridge target | Reuse exact accepted service/repository authority once identified; do not duplicate |
| M8 canonical digest, immutable revision, head CAS, idempotent command and receipt patterns | **PORT / shared-kernel pattern** | Opportunity revision and Greenlight mechanics | M9-owned types or separately accepted schema evolution; no insertion into closed M8 payload union by assumption |
| M8 `LearningObservation` / recommendation read seam | **DIRECT via port** after M8 acceptance | Evidence input with source lineage and expiry | Read only; no M9 persistence or disposition bypass |
| OpenMontage `research_brief` sections | **PORT vocabulary + FIXTURE** | Landscape/audience/angle test corpus | Replace URL-only provenance with SourceQuery/Snapshot closure; item-count constants are not universal |
| OpenMontage Research Director search batches | **FIXTURE** | Query-plan and partial/failure scenarios | No embedded search recipe becomes normative; official-source and provider-policy gates remain external |
| OpenMontage `decision_log` | **PORT vocabulary + FIXTURE** | Alternatives/rejected reasons/human-visible review | Boolean approval is not Greenlight; must add issuer/binding/expiry/CAS/supersession |
| Kalinga adapter registry and manual facts flow | **PORT interface idea + FIXTURE** | Adapter success/no-result/cache/manual-input cases | No direct filesystem authority; no silent catch/truncation in authoritative path |
| Kalinga `suggest_topics()` | **FIXTURE** | Seeded ideation, prior-topic collision and malformed-output tests | LLM output remains an untrusted proposal; prompt-only near-duplicate rule is insufficient |
| Kalinga `facts.json`, `ideas.json`, CSV queue | **REJECT as authority; FIXTURE only** | Import/adversarial corpus | Mutable filesystem presence cannot establish provenance, currentness or Human Greenlight |
| Huohuo chapter/`爽型` fields | **PORT vocabulary + NATIVE-LANGUAGE FIXTURE** | `zh-shuang` creative-fit descriptors and reviewer corpus | Donor-specific grammar, never an engagement proxy, factual truth, universal threshold or automatic Greenlight |
| Donor web/LLM runtime and pipeline shell | **REJECT** | None | Would introduce provider calls, credentials, orchestration and state outside the authorized M9 boundary |
| YouTube Data API list operations | **PORT behind capability gate** | Public inventory snapshots and provider-native fields | Exact operation/quota/page/field/policy evidence; no derived score without applicable amendment |
| Google Trends API alpha | **OPTIONAL PORT + FIXTURE** | Consistently scaled search-interest observations if access exists | M9 baseline cannot require alpha admission; preserve interval, geography, scaling and coverage |
| TikTok Research API | **REJECT for commercial baseline** | Separately approved research projects only | Commercial/creator ineligibility and archived-data lag are explicit capability facts |
| TikTok Commercial Content API | **OPTIONAL PORT, ADS ONLY** | Paid/commercial creative landscape | Never represent ads as organic demand; preserve `search_id` pagination and corpus label |

Any selected donor code or behavior still requires the accepted R2 donor parity
protocol: exact URL/SHA/paths, reachable surface, behavior and donor-test
inventory, same-fixture differential evidence, exact integrated HEAD, no required
skips/material unknowns, and independent review
([M8 design lines 467–509](../superpowers/specs/2026-09-13-r2-m8-canvas-learning-multiformat-design.md#L467-L509),
[699–712](../superpowers/specs/2026-09-13-r2-m8-canvas-learning-multiformat-design.md#L699-L712)).

## 6. Required M9 contracts — design input, not final schema

### 6.1 `SourceQuery`

Minimum identity/binding candidates:

- `query_id`, immutable revision and `query_digest` over canonical semantics;
- `(user_id, project_name)` scope and request/command identity;
- `source_family`, source-native operation and parameters, locale/region/time
  window, audience/profile context, and page/coverage limit;
- opaque host credential reference when applicable, never token material;
- provider-policy/evidence reference and digest, assessed/effective time, allowed
  purposes, retention/deletion class and freshness deadline;
- requester/creator identity, creation time and supersession link.

Changing any semantic parameter, scope, purpose, policy or credential/account
binding must produce a new query revision/digest. Retry of the same command and
same digest returns the prior identity; same command with a different digest
conflicts.

### 6.2 `SourceSnapshot`

Minimum candidates:

- immutable `snapshot_id` and revision, exact `query_id`/revision/digest;
- source-native record/account/channel identities and provider response/version;
- capture start/end and provider-observed time separately;
- raw payload artifact reference plus SHA-256, media type and schema version;
- page/cursor lineage, requested versus returned coverage, truncation,
  missingness, authorization/private/deleted state, and adapter version;
- policy/consent/retention/deletion bindings copied from the evaluated capability;
- correction/supersession/tombstone relationship and non-sensitive deletion
  proof.

A snapshot is evidence of what was observed under a query, not proof that the
provider universe was complete or that a claim is true. Partial pagination,
expired capability or unresolved retrieval outcome must remain explicit.

### 6.3 `NormalizedSourceObservation`

Normalization must be lossless and source-native: preserve the source metric or
field name/definition/version, value/unit, window, source identity, snapshot/raw
digest, transformation version, missingness and correction lineage. It may not
combine fields, assign a new meaning, infer popularity or produce a weighted
opportunity score. This matches ADR-0080's accepted definition
([lines 154–162](../adr/0080-post-m8-north-star-closed-loop.md#L154-L162)).

### 6.4 `DerivedOpportunitySignal`

A derived signal should be a separate artifact with:

- signal kind/dimension; exact input observation/snapshot closure and digest;
- transform code/version and parameters;
- named policy basis per input/source and permitted purpose;
- cohort/profile/audience/time-window applicability and exclusions;
- uncertainty/missingness treatment and sensitivity evidence;
- evaluator identity/time and expiry.

Commercial opportunity, creative opportunity, originality, channel fit,
knowledge advantage and production feasibility should remain separately visible.
If an overall rank is proposed, it must preserve every component and cannot hide
a forbidden provider-derived composite behind a label or local-data mixture.

### 6.5 `OpportunityCandidateRevision` and head

Minimum candidates:

- candidate ID, immutable revision, parent revision, independent head CAS;
- topic/premise/angle/audience/profile scope and creator intent;
- exact snapshot and derived-signal closure digest;
- separate commercial and creative assessments, production feasibility,
  uncertainty, contraindications and open questions;
- references to M8 observations/recommendations where used, including currentness
  and expiry;
- factual-claim candidates explicitly marked unverified unless existing Factual
  Authority says otherwise;
- canonical payload/lineage digest, author and creation time.

The repository must preserve rejected and superseded revisions. It must not
overwrite a candidate based on a later trend refresh or silently move a
Greenlight to a new revision.

### 6.6 `GreenlightDecision`

Minimum candidates:

- append-only decision ID and scoped idempotent command ID;
- `APPROVE`, `REJECT`, `EXPIRE` or `SUPERSEDE` disposition;
- exact candidate revision/payload digest and complete snapshot/input closure
  digest;
- freshness policy and evaluated-at deadline;
- Human issuer/custodian, reason, issued time, expiry and superseded decision;
- current candidate-head and decision-head expected versions;
- approved Canvas-bridge scope, not a production/factual target;
- receipt/event identity for exact replay and audit.

The Greenlight transaction must re-read candidate head, complete evidence
closure, policy/currentness, expiry and scope under a fixed lock order before
append. Refresh, correction, deletion, changed candidate/scope/policy, expiry or
explicit supersession invalidates it; no component may silently carry approval
forward.

### 6.7 Explicit authority bridges

1. **Greenlight → M8 Canvas:** a narrow adapter consumes an exact current
   Greenlight and produces an M8 Canvas exploration proposal/revision through
   `ExplorationRepository`. It does not call `ExplorationPromotionService`, M7
   Production Authority, Canon or Narrative authority.
2. **Snapshot evidence → Factual Authority:** a separate adapter maps selected
   source/snapshot material to existing `SourceRecord`/`EvidenceRecord` inputs.
   Only Factual Authority may verify a `Claim` or approve/publish a ResearchPack.
3. **M8 Learning → M9:** an M8 read port returns exact observations,
   recommendations and dispositions. M9 records their immutable identities and
   expiry in candidate evidence; it cannot update M8 tables.

## 7. Invariants

1. Greenlight selects an opportunity; it never verifies factual truth.
2. No model score, donor checkpoint, provider response or engagement count grants
   Greenlight.
3. M9 has no direct Canon, NarrativePlan, CreativePolicy, routing, production,
   ApprovedMaster, ResearchPack or Claim authority write port.
4. `SourceQuery`, snapshots, observations, signals, candidate revisions and
   Greenlight decisions are immutable; corrections/supersessions are append-only.
5. Every mutable head uses expected-version CAS; every public operation is scoped
   by user/project and foreign versus unknown identity is indistinguishable.
6. Exact replay is idempotent; same command identity with changed semantics is a
   conflict.
7. Raw acquisition happens outside short database transactions. Authority
   transactions never span provider, model, filesystem or media-store I/O.
8. Snapshot completeness, missingness, truncation and unknown outcome are data,
   never silently converted to zero or success.
9. Normalization is lossless; derivation is a separate policy-governed artifact.
10. Corrected/deleted inputs expire or supersede dependent signals, candidates
    and Greenlights; incomplete propagation makes dependent reads fail closed.
11. Human Greenlight binds exact revision, complete input closure, freshness,
    issuer, reason, issued time, expiry and scope.
12. Canvas remains exploration-only. Greenlight may seed Canvas, but only M8's
    separately previewed and explicitly authorized promotion path can reach an R2
    artifact, and Production Authority remains the only route to ApprovedMaster.
13. M9 uses the ArcReel host and PostgreSQL authority store; no donor database,
    queue, orchestrator, browser authority or parallel runtime becomes truth.
14. One implementation/review packet remains active; fixture-only parallel work
    has no provider calls, credentials or acceptance authority.

## 8. Required failure and adversarial cases

| Case | Required result |
|---|---|
| Same query command/same digest replay | Return same query identity; no duplicate revision/event |
| Same command/different semantic digest | Conflict, no write |
| Query policy or credential/account binding changed | New revision or stop; never reuse prior snapshot authority |
| Partial pages, cursor loop, duplicate page or page-order change | Record incomplete/duplicate state; do not claim complete landscape |
| Provider timeout after possible response persistence | Durable unknown outcome and reconciliation identity; no blind retry-as-new |
| URL content changes after capture | New snapshot/fingerprint; old snapshot remains immutable |
| Raw digest mismatch or unavailable payload | Reject normalization and dependent candidate |
| Lossy transform or unknown metric definition | Reject normalized observation |
| Composite lacks input closure, transform version or permitted-use basis | Stop before candidate scoring |
| Missing signal is coerced to zero | Test must fail |
| Commercial and creative dimensions collapse into one opaque score | Test must fail |
| Cross-profile/cohort evidence is pooled without compatibility declaration | Stop with cohort/profile leakage evidence |
| Candidate append from stale parent/head | CAS conflict; preserve current revision |
| Model emits malformed, duplicate or unsupported topic | Untrusted proposal rejected or isolated; no Greenlight |
| Prompt says “avoid near duplicate” but semantic duplicate passes string check | Detection fixture; requires explicit human/reviewer outcome |
| Greenlight by model/provider/donor boolean | Reject issuer/authority |
| Greenlight candidate or snapshot closure changed/expired | Stale decision; no Canvas bridge |
| Snapshot corrected/deleted after Greenlight | Append expiry/supersession; dependent reads fail closed until propagation completes |
| Greenlight adapter attempts direct ResearchPack/Claim verification | Authority-boundary failure |
| Greenlight adapter attempts M8 promotion, production or Canon mutation | Authority-boundary failure |
| Factual bridge references missing Source/Evidence identity | Reject atomically; no partial ResearchPack |
| Foreign project ID versus unknown ID | Indistinguishable response and no leakage |
| Process crash between decision append and event/receipt | Atomic commit or deterministic recovery; never acknowledged-but-missing |

## 9. Bounded probes and parity gates for the future design

These probes require no live provider access and can be preregistered before M9
implementation:

1. Canonical query digest table: parameter order, Unicode, locale, timestamps,
   omitted/default fields and policy-ref changes.
2. Snapshot fixture corpus: complete pagination, partial last page, cursor loop,
   duplicate records, changed record, private/deleted record, rate-limit and
   unknown outcome.
3. Normalization differential corpus: exact source values/windows/units/digests
   survive; derived fields are rejected from the normalization contract.
4. Composite policy matrix: each input permitted/forbidden/expired/missing;
   forbidden single input blocks the composite.
5. Candidate concurrency probe: concurrent genesis, stale append, exact replay,
   changed replay and cross-project access.
6. Greenlight concurrency probe: changed candidate head, corrected snapshot,
   expired freshness, changed scope, decision supersession and crash/restart.
7. Factual bridge probe: identical selected evidence maps deterministically;
   unverified claims remain unverified; missing refs fail atomically.
8. Canvas bridge probe: only exact current Greenlight creates a Canvas revision;
   no path can invoke M8 promotion or Production Authority.
9. OpenMontage fixture parity: landscape/gaps/audience/angle/bibliography fields,
   malformed URLs, missing sources, old sources and contradictory findings.
10. Kalinga fixture parity: seeded versus unseeded ideation, exact and semantic
    duplicates, malformed JSON, missing backend, cached mutable facts and
    swallowed upstream error.

For any donor port, parity is scoped to the selected reachable behavior, never
repository popularity or an attractive output. Every applicable functionality,
correctness, determinism, failure-safety, integrity, observability, performance
and resource row must be `PARITY` or `IMPROVED`; donor defects need fixtures.

## 10. Architecture options and research recommendation

The option comparison uses the accepted post-M8 criteria: authority containment,
source/policy correctness, reuse, failure recovery, cohort extensibility, and
implementation clarity. Scores are comparative research inputs from 1 (weak) to
5 (strong), not an acceptance vote.

| Option | Authority | Policy correctness | Reuse | Recovery | Cohorts | Clarity | Result |
|---|---:|---:|---:|---:|---:|---:|---|
| A. Extend M8 Learning to own discovery and Greenlight | 2 | 3 | 4 | 4 | 3 | 2 | **Reject.** It conflates learning with market discovery and changes M8's accepted payload/authority boundary. |
| B. Host-integrated M9 deep module with provider ports, M7 receipt mechanics, M8 read/Canvas adapters, and a Factual Authority bridge | 5 | 5 | 5 | 5 | 5 | 5 | **Recommend for ADR evaluation.** It reuses accepted mechanics without transferring authority. |
| C. External scraper/microservice/data lake | 1 | 2 | 2 | 2 | 4 | 2 | **Reject.** It creates a second runtime/store and weakens project scoping, deletion lineage and transaction evidence. |
| D. Manual-only research subsystem | 5 | 5 | 3 | 4 | 3 | 4 | **Retain as baseline adapter, not governing architecture.** Safe and useful offline, but cannot by itself close the intended discovery loop. |

Option B should be tested against a manual/import adapter first and add network
adapters only behind capability evidence. It should reuse M7's execution-attempt,
receipt, idempotency and unknown-outcome vocabulary rather than inventing a
second acquisition executor; reuse M8's revision/digest/CAS mechanics and exact
Greenlight-to-Canvas seam without placing opportunity payloads in M8's closed
union; and reuse the actual Factual Authority service once that service is
identified. If the latter service does not exist beyond contracts, M9 design
must expose a required `FactualAuthorityPort` and implementation must stop with
`M9_FACTUAL_AUTHORITY_UNAVAILABLE` rather than treating Pydantic models as an
authority system.

Western generic/factual profiles and Chinese short-drama `zh-shuang` profiles
must be sibling cohorts. They share evidence mechanics but not source priors,
originality corpus, commercial/creative weights, thresholds, language
normalization, audience assumptions or reviewer rubric. A profile can declare
required/optional source classes; unavailable sources produce explicit
missingness, never borrowed cross-cohort evidence or a synthetic zero.

## 11. Explicit design-time unknowns and required resolutions

1. **M8 implementation prerequisite:** this pass did not establish a current
   `M8_IMPLEMENTATION_ACCEPTED` record or exact accepted implementation seam.
   M9 implementation must stop until that prerequisite exists and matches.
2. **Factual Authority service boundary:** contracts are verified, but the exact
   accepted repository/service/transaction that publishes Source/Evidence/
   ResearchPack/Claim state still needs tracing and binding.
3. **Greenlight custodian:** ADR-0080 intentionally leaves Human custodian role,
   eligibility, delegation, revocation and conflict policy to M9 design.
4. **Opportunity scoring policy:** no accepted formula, calibration set,
   threshold, aggregation or tie-break policy exists. The rationale's product is
   not a normative formula.
5. **Provider account-specific proof:** current public rules are recorded in
   §4.3, but M9 design still needs the exact account/project amendment, API
   approval, scopes, quota and effective/expiry evidence before enabling an
   adapter. Public documentation is not proof that this installation is approved.
6. **Snapshot storage:** raw payload store, encryption, size limits, retention,
   legal deletion domain and permitted tombstone fields are unresolved.
7. **Coverage semantics:** each source needs a definition of complete, truncated,
   sampled, ranked and unavailable results; donors do not supply one.
8. **Semantic originality/near-duplicate evaluation:** Kalinga has only prompt
   guidance plus exact normalized-string exclusion. Corpus, reviewer rubric,
   false-positive tolerance and cultural/profile scope remain open.
9. **Profile/cohort calibration:** generic Western and `zh-shuang` remain sibling
   cohorts. No inspected donor evidence justifies shared weights or universal
   opportunity thresholds, so each rubric/corpus requires preregistration and
   qualified blind review.
10. **Fiction research:** local rationale mentions genre/theme/audience signals,
    but OpenMontage/Kalinga evidence is explainer/factual-short-heavy. Required
    fiction-specific source classes and factual-versus-creative bridge behavior
    remain open.
11. **Deletion dependency traversal:** exact indexes, deadline, recomputation and
    fail-closed read strategy from snapshot through signal/candidate/Greenlight
    need a design contract.
12. **Operational envelope:** expected query/snapshot volumes, payload sizes,
    concurrency, latency, cost and retention are not benchmarked.
13. **Donor manifest:** OpenMontage and Kalinga pins are cited and locally
    verified, but this pass did not add them to the repository source manifest;
    evidence ownership was limited to this research file.

## 12. Evidence index

### ArcReel local primary sources

- `docs/adr/0080-post-m8-north-star-closed-loop.md` — accepted ADR SHA-256
  `53f9d9986723df587cf52fd5b34b78c0d440809d6ba057df1625d179de070aa8`.
- `docs/r2/evidence/R2_POST_M8_ARCHITECTURE_ACCEPTANCE_CONTRACT_2026-09-14.json`
  — SHA-256
  `047551f6a198bb1a310292aec389d0c3828d997e220effcf7ac2c1c2f6369ea4`.
- `docs/r2/evidence/R2_POST_M8_ARCHITECTURE_ACCEPTANCE.json` — accepted
  lineage and independent reviews.
- `r2/contracts/factual.py` — current HEAD SHA-256
  `f3478d17683f5b859b7fa342b223c5babfd527d14f9365f7e598e892316bbb15`.
- `docs/superpowers/specs/2026-09-13-r2-m8-canvas-learning-multiformat-design.md`
  — current HEAD SHA-256
  `34c1f1d2fcc1c0b5967dcf0f6180f04405435cf0d4c65702b6aa6346bc455dba`.
- `docs/research/r2-origin/00_PRODUCT_VISION.md` and
  `02_SYSTEM_REQUIREMENTS.md` — intent/rationale only, explicitly
  non-authoritative.
- `docs/research/2026-09-12-r2-m8-canvas-learning-multiformat-research.md`
  — existing bounded Huohuo/Western/`zh-shuang` donor evidence; research input,
  not M9 authority.

### Pinned donor source

- OpenMontage `08e2151fa02de28a5d6a312b3d575692bf147ad7`:
  [`research_brief.schema.json`](https://github.com/calesthio/OpenMontage/blob/08e2151fa02de28a5d6a312b3d575692bf147ad7/schemas/artifacts/research_brief.schema.json),
  [`research-director.md`](https://github.com/calesthio/OpenMontage/blob/08e2151fa02de28a5d6a312b3d575692bf147ad7/skills/pipelines/explainer/research-director.md),
  [`decision_log.schema.json`](https://github.com/calesthio/OpenMontage/blob/08e2151fa02de28a5d6a312b3d575692bf147ad7/schemas/artifacts/decision_log.schema.json).
- Kalinga Shorts Factory `e4b5a2173ca03d365aad565a89fcc43159b44f9b`:
  [`research.py`](https://github.com/desaultkhan/Kalinga-Shorts-Factory/blob/e4b5a2173ca03d365aad565a89fcc43159b44f9b/pipeline/src/research.py),
  [`creative.py`](https://github.com/desaultkhan/Kalinga-Shorts-Factory/blob/e4b5a2173ca03d365aad565a89fcc43159b44f9b/pipeline/src/creative.py),
  [`daily.py`](https://github.com/desaultkhan/Kalinga-Shorts-Factory/blob/e4b5a2173ca03d365aad565a89fcc43159b44f9b/pipeline/src/daily.py),
  [`kalinga.py`](https://github.com/desaultkhan/Kalinga-Shorts-Factory/blob/e4b5a2173ca03d365aad565a89fcc43159b44f9b/pipeline/src/kalinga.py),
  [`history-shorts/channel.yaml`](https://github.com/desaultkhan/Kalinga-Shorts-Factory/blob/e4b5a2173ca03d365aad565a89fcc43159b44f9b/channels/history-shorts/channel.yaml).
- Huohuo Drama `f104b853b3563e124d9cde25f9331d323fb483b9`:
  [`novel-outline-drama-fields.ts`](https://github.com/appolloqin/huohuo-drama/blob/f104b853b3563e124d9cde25f9331d323fb483b9/workbench-server/src/services/novel/novel-outline-drama-fields.ts).

### Official provider/API primary sources

- YouTube [`search.list`](https://developers.google.com/youtube/v3/docs/search/list),
  [`videos.list`](https://developers.google.com/youtube/v3/docs/videos/list),
  [Data API quota overview](https://developers.google.com/youtube/v3/getting-started),
  and [additional derived-metric/storage policy](https://developers.google.com/youtube/terms/derived-metrics-policy).
- Google [Trends API alpha](https://developers.google.com/search/apis/trends).
- TikTok [Research API FAQ](https://developers.tiktok.com/docs/en/research-api-faq)
  and [Commercial Content API getting started](https://developers.tiktok.com/docs/en/commercial-content-api-getting-started).

These claims were assessed on 2026-09-14. They are time-sensitive and must be
revalidated and hashed again at M9 design acceptance and before any adapter is
enabled.

## 13. Handoff boundary

The research pass is complete enough to begin ADR/design evaluation of Option B.
The design must resolve every item in §11, freeze provider capability states and
the exact Factual/M7/M8 seams, preregister donor parity and cohort rubrics, and
split the smallest independently reviewable M9 packet sequence. Nothing in this
document is an implementation approval.

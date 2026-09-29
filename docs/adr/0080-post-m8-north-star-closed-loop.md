---
status: accepted
---

# Post-M8 closes the North Star through four sequenced host-integrated milestones

R2 shall preserve M0-M8 as the governed creative-production spine and close the
original `DISCOVER -> CREATE -> DIRECT -> PRODUCE -> EVALUATE -> DISTRIBUTE ->
LEARN` loop through four additional milestones: M9 Opportunity and Research
Intelligence, M10 Quality Evidence and Product Packaging, M11 Governed
Distribution, and M12 Closed-loop Portfolio Learning. These capabilities remain
deep modules inside the ArcReel host over PostgreSQL and the existing R2
authority/execution contracts. They shall not become a second application,
orchestrator, workflow authority, database, queue or truth store.

The decision is based on the source and donor probes in
`docs/research/2026-09-14-r2-north-star-completion-research.md`. Expanding M8 was
rejected because it would collapse independently reviewable authority, quality,
network-side-effect and learning risks into one milestone. A distribution-first
product vertical remains a valid pilot inside this sequence, but was rejected as
the governing architecture because it leaves DISCOVER, independent quality
evidence and feedback lineage incomplete.

## Decision

The milestone order is normative:

1. **M9 — Opportunity and Research Intelligence** owns immutable source-query
   and snapshot evidence, source-native normalized observations,
   `OpportunityCandidate` revisions and Human Greenlight of a creative
   opportunity into Canvas exploration. Greenlight selects an opportunity; it
   does not verify a factual claim or create an approved `ResearchPack`.
   Each append-only Greenlight binds the exact candidate revision and complete
   source-snapshot digest closure, freshness policy, Human issuer, reason,
   issued time and expiry; evidence refresh, expiry or supersession requires a
   new decision and cannot silently carry the prior Greenlight forward.
   Source evidence and claims enter the existing factual-authority workflow
   separately, and only that workflow may produce ResearchPack evidence.
   Popularity, novelty, channel fit, knowledge advantage and production
   feasibility remain separate; untrusted market input cannot write Canon,
   factual truth or production truth.
2. **M10 — Quality Evidence and Product Packaging** owns versioned
   `QualityProfile`, typed multi-assessor `QualityRun`, authority-issued quality
   disposition, immutable `PackagingCandidate` revisions and deterministic
   export bundles. It may reuse M8 candidate/revision/promotion mechanics, M7
   executions/receipts and the host's secure FFmpeg subprocess pattern. It does
   not own an external publish side effect.
3. **M11 — Governed Distribution** owns `PublishApproval`, idempotent
   `DistributionCommand`, durable provider-session identity,
   `DeliveryAttempt`, reconciliation and `DistributionReceipt`. Network
   adapters remain thin. Upload, processing, moderation, scheduling and public
   visibility are distinct states. Public release requires a separate Publish
   Gate and explicit production authorization.
4. **M12 — Closed-loop Portfolio Learning** owns authorized platform
   ingestion, distribution-receipt-to-content mapping and portfolio/cohort
   evaluation. M8 remains owner of the generic `LearningObservation`, correction
   lineage, `LearningRecommendation`, disposition and persistence lifecycle;
   M12 supplies platform-specific payloads through that interface rather than
   creating a second observation/recommendation store or authority. Resulting
   recommendations may enter M9 opportunity evidence or M8 exploration
   candidates; they cannot mutate Canon, NarrativePlan, policy, profile,
   routing, artifact or approval authority.

M8-D2's YouTube/TikTok work is the first implementation of the M8-owned **pure
normalization seam**: fixture payload to source-preserving
`LearningObservation`, without network acquisition. M12 shall reuse those
transforms and add/replace only provider I/O adapters for acquisition, refresh,
consent and deletion behind the M8 interface. Shared transform or contract
changes remain an explicit M8 schema evolution; M12 owns their platform I/O
maintenance but has no parallel normalization lifecycle or direct table access.

No milestone may begin implementation from planned predecessor behavior. M9
starts only from the accepted M8 implementation lineage; each later milestone
starts only after the preceding milestone's required evidence and independent
review are accepted. A design commit, historical green test or donor output is
not predecessor acceptance evidence.

## Stable seams and authority

The external interfaces remain small and provider-neutral:

- a **Market Source seam** accepts a declared query and returns an immutable
  provider-native snapshot plus coverage/freshness semantics;
- a **Quality Probe seam** accepts an approved artifact reference and versioned
  profile and returns typed evidence without deciding Final Cut;
- a **Distribution Provider seam** accepts an approval-bound command, persists
  or returns the provider reconciliation identity, and reports provider-native
  delivery observations;
- an **Analytics Source seam** returns authorized observations with metric,
  time-window, freshness, consent and deletion semantics.

Authority remains elsewhere: Human Greenlight selects an opportunity; factual
authority verifies claims and ResearchPack evidence; existing Production
Authority selects an ApprovedMaster; a quality disposition governs package
readiness; Publish Approval authorizes an exact platform/account/content/
metadata/visibility tuple; platform adapters only execute and observe.
No provider adapter, model judgment, donor checkpoint, engagement score or
successful HTTP response may grant Greenlight, quality disposition, Production
Approval or Publish Approval.

`QualityDispositionAuthority` is a Human Final Cut custodian, separate from all
probe/model adapters. Each append-only `PASS`, `REWORK` or `WAIVE` decision binds
user/project, exact ApprovedMaster/artifact digest, `QualityProfile` digest,
complete `QualityRun` digest and assessed-subject closure, including the exact
`PackagingCandidate` payload digest when packaging is under review, issuer,
reason, issued time and expiry. `WAIVE` is always reasoned and time-bounded. A
new artifact/profile/run/assessed subject, expiry or explicit supersession
invalidates package readiness; the disposition never selects or changes the
ApprovedMaster. The implementation specification must define the atomic
current-disposition read/CAS used by packaging and Publish Approval.

M10 extends the shared M8 candidate kernel through an accepted schema evolution
with `PackagingCandidate` and a closed `PACKAGING_SLOT` target. Preview-bound
selection binds the exact candidate revision/payload digest, ApprovedMaster,
current `QualityDisposition`, scope and expected packaging-head CAS. Its M10
Packaging Authority may select an immutable package but cannot target an M8
`ARTIFACT_SLOT`, replace the ApprovedMaster or invoke Production Authority.

`PublishApprovalAuthority` is a Human release custodian. Each append-only
approval binds user/project, exact ApprovedMaster and packaging selection,
content/metadata/thumbnail/caption digests, platform/account, disclosure,
visibility/schedule, QualityDisposition, issuer, reason, issued time and expiry.
Any changed binding, expiry or supersession invalidates it. Publish Gate is the
transactional revalidation and consumption of that same approval immediately
before the provider command; it is not a second signature or a provider-owned
decision.

The existing provider credential repository may remain a host configuration
entry point. The **host**, not M9/M11/M12, owns the credential-reference/custody
interface. It binds OAuth account/channel, scope, expiry, refresh, revocation
and deletion proof. M9, M11 and M12 consume opaque credential references
through their own ports and cannot read or persist token material. Access or
refresh tokens shall not enter prompts, artifacts, logs, commands, receipts or
browser persistence.

## Platform-data constraints

Platform access is capability-gated rather than assumed. TikTok Research is
unavailable by default because its current eligibility excludes creators and
commercial users; an eligible approved research project is required to enable
that adapter. Google Trends remains optional while official API access is
limited. R2 shall not replace an unavailable official capability with
undocumented scraping.

YouTube API metrics remain provider-native observations. By default, R2 shall
not create a weighted opportunity, virality or performance metric from YouTube
API Data; the current policy text prohibits creating derived data or metrics in
the ordinary API-client case. Any exceptional path requires a named, reviewable
policy basis and separate activation evidence rather than assuming universal
permission. Refresh, authorization-reverification, revocation and user-requested
deletion operations are part of the data interface, not an operational
afterthought.

“Normalization” is a lossless representation change that preserves the source
metric name/definition/version, value/unit, window, provider identities, raw
digest and transformation version; it cannot combine fields or assign new
meaning. Every composite signal used by an `OpportunityCandidate` — including
novelty, channel fit, knowledge advantage and feasibility — must name its input
sources, transformation, policy basis and whether provider terms permit that
use. A signal that consumes YouTube API Data is blocked unless its particular
reviewable policy basis permits it; labeling it “creative” or mixing it with
local data does not evade that rule.

Deletion does not rewrite append-only history into false evidence. When source
data must be deleted, M12 removes the provider payload and uses M8's
`ObservationRepository.ingest()` to append a source-preserving
`LearningObservation` correction with `correction_of` and `missing_reason`, plus
a non-sensitive deletion tombstone/proof. Dependent recommendations are
withdrawn or superseded through an append-only `RecommendationDecision` schema
evolution; dependent M9 opportunity candidates and Greenlights expire or are
superseded through their own append-only interfaces; and downstream portfolio
conclusions are recomputed or withdrawn.
M12 has no direct write port to M8 tables and cannot mutate an observation or
recommendation in place. The tombstone may retain only
minimal command/time/outcome/digest-domain evidence permitted by the governing
policy; it must not retain a reversible copy or derived surrogate of deleted
provider data. The M12 specification must define dependency traversal,
idempotent deletion, deadline evidence and fail-closed reads during incomplete
propagation.

## Donor reuse decision

Donors deepen named modules but never supply authority:

- OpenMontage provides research/package vocabulary, offline export behavior,
  profile definitions and differential fixtures;
- Kalinga Shorts Factory provides the vertical-Short profile corpus,
  cheap-first QA ordering, pure SEO/lint candidates, granular repair-routing
  fixtures and real output media for regression evidence;
- the legacy YouTube uploader provides request-shape and happy-path fixtures,
  not credential custody, recovery or receipts;
- VieNeu may enter only behind the existing provider/execution contracts after
  same-fixture parity and timing-quality evidence;
- FFmpeg/ffprobe are direct deterministic probe adapters; VMAF is limited to
  named-reference render/transcode comparisons and may appear only as technical
  observation evidence, never as an automatic quality disposition.

Every selected donor surface remains subject to `R2-DEC-031`: exact revision,
reachable behavior inventory, same-fixture differential tests, donor-defect
fixtures, resource evidence and independent review. `PARITY` or `IMPROVED`
applies only to the selected surface; it is never inferred from repository
popularity, smoke tests or one attractive output.

## Consequences

- M10's content/quality ladder is Western explainer export-only, vertical
  factual Short export-only, then Chinese `zh-shuang` export-only. After M10 is
  accepted, M11's independent network ladder is private/unlisted YouTube
  explainer, private/unlisted YouTube vertical Short, then TikTok private pilot
  after its platform gates pass. This separates semantic/profile risk from
  irreversible network-side-effect risk.
- Isolated fixture-only vertical prototypes may run while M9 specifications are
  written, but they carry no production authority, cannot call provider APIs,
  cannot count as M10/M11 acceptance evidence and do not relax milestone order.
- M9-M12 share identity, scoping, lineage, idempotency, receipts and recovery
  with M0-M8 rather than creating parallel abstractions.
- Export-only packaging can deliver user value before network authority is
  enabled. A packaged artifact is not uploaded, published or public.
- Cross-platform metrics are not collapsed into a universal score. Each source
  retains its own semantics, freshness, missingness, consent and retention.
- Podcast, audiobook and novel profiles remain extensions until evidence shows
  a distinct kernel contract is required.
- This proposed ADR authorizes specification and implementation planning only
  after independent acceptance. It does not authorize implementation,
  migrations, credentials, API calls, uploads, publication, runtime activation
  or production approval.

## Acceptance conditions

This ADR remains `proposed` until an independent review verifies that the
following obligations are explicit and mutually consistent here or in a bound
normative acceptance manifest:

- a frozen **schema-freeze protocol** naming, for each milestone, where and when
  its accepted design records contract/evidence schema identities and hashes,
  who independently verifies them, and which stop code applies on drift; ADR
  acceptance does not require future milestone hashes to exist early;
- normative stop codes, linear migration boundaries and rollback/restore proof;
- OAuth scope/refresh/revocation plus provider-data refresh/deletion operations;
- sandbox/provider fixtures for success, rejection, retry and unknown outcome;
- reviewer qualification, independence and rubric version;
- exact predecessor and integrated HEAD lineage; and
- one implementation-and-review packet active at a time, with no later packet
  treating planned or unaccepted behavior as available.

Acceptance of this architecture permits M9-M12 specification and implementation
planning. Each milestone still requires its own accepted design, plan and
execution manifest before code or external side effects are authorized.

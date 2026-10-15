---
status: proposed
---

# M9 uses an evidence-first opportunity module with capability-gated source adapters

M9 shall be a deep module inside the ArcReel host over PostgreSQL. It owns
immutable market-source queries and snapshots, lossless source observations,
policy-bound derived opportunity signals, append-only opportunity candidate
revisions, and Human Greenlight into M8 Canvas exploration. It shall not become
a scraper product, external intelligence microservice, second factual system,
or extension of M8 Learning authority.

This decision selects Option B from
`docs/research/2026-09-14-r2-m9-opportunity-research-intelligence.md`. The option
contains authority and policy risk while reusing the most valuable existing
work: M7 execution/receipt mechanics, M8 canonical digest/revision/CAS and
Canvas/Learning seams, R2 factual contracts, OpenMontage research vocabulary,
Kalinga ideation/failure fixtures, and Huohuo native-language `zh-shuang`
fixtures.

The design baseline is ArcReel commit
`7d271f7833ed84a4b8a4aeee62c837a831a668c8`; later acceptance evidence must bind
the exact ADR/spec/research candidate hashes rather than treating this baseline
as design acceptance.

## Decision

M9 presents one provider-neutral Opportunity Intelligence interface. Its
implementation hides source capability evaluation, acquisition recovery,
pagination/coverage, immutable snapshots, lossless normalization, policy-based
derivation, candidate revisioning, evidence invalidation and Greenlight
revalidation. Provider-specific adapters satisfy an internal Market Source
seam and never grant authority.

M9 also owns append-only, project-scoped `OpportunityCohortProfile` revisions
and CAS heads. A profile freezes the cohort/source/dimension rules,
transform/calibration identities, originality corpus, reviewer qualification
and freshness policy used to validate a candidate. Only an authenticated Human
holding a short-lived host-owned authorization lease for the exact command and
profile-publication subject may publish a profile revision. The custodian
replays that lease by command identity and guarantees it remains authorizing
until its admission deadline; changed-subject replay fails closed. Every use
binds the exact profile identity, revision and digest;
changing profile content appends a revision rather than silently changing an
existing candidate's meaning.

The initial supported adapter is deterministic Human/manual import. YouTube
public inventory, Google Trends alpha and TikTok Commercial Content are optional
dormant adapters until the host supplies an opaque credential reference and a
current capability grant for the exact provider, account, purpose, scopes,
policy basis, retention and deletion obligations. TikTok Research is unavailable
for the commercial baseline. Undocumented scraping is not a fallback.

Public documentation is policy evidence, not account authorization. YouTube
derived opportunity signals are disabled by default. A signal consuming YouTube
API Data may be produced only when a host-issued capability grant binds the
applicable Analytics & Reporting amendment and exact permitted use. Lossless
provider-native normalization remains distinct from derivation. Revoked,
expired, missing or mismatched grants fail closed.

`OpportunityCandidate` is M9-owned and does not extend M8's closed candidate
payload union. A narrow bridge consumes one current Human Greenlight and creates
an M8 Canvas seed through the accepted M8 interface. Greenlight only authorizes
entry into exploration; it does not call M8 promotion, write Canon or Narrative,
verify facts, create an approved ResearchPack, or select an ApprovedMaster.

Selected source material enters factual processing through a required
`FactualAuthorityPort`. At the current design lineage, R2 exposes typed factual
contracts but no verified durable Factual Authority repository/service. M9 shall
not mistake those Pydantic models for authority. Implementation of the factual
bridge stops with `M9_FACTUAL_AUTHORITY_UNAVAILABLE` until the accepted authority
seam is present and bound by exact commit/hash evidence.

M9 implementation starts only from an independently accepted M8 implementation
lineage. Planned seam names are not executable dependencies.

**V2 revalidation (2026-10-15).** The V2 lineage accepted the M8 implementation at
`23cf146a`. The design was revalidated against it
(`docs/research/2026-10-15-r2-m9-prerequisite-path.md`):

- The durable Factual Authority is a separate prerequisite (FA-1), gated at the
  M9-D release. It is not required before M9-A.
- Cohort profiles carry the exact M6 creative profile identities (ADR-0105).
- The Canvas seed uses M8 lineage resolution v3 (ADR-0109) on the server and
  never the client append route (ADR-0107).
- The host custodian is an adapter over the ADR-0103 showrunner grants.
- Retention deadlines are enforced at read time, and a sweep creates the
  invalidation jobs.

Western generic/factual and Chinese short-drama `zh-shuang` are sibling cohorts.
They share contracts and evidence mechanics but never silently share source
priors, originality corpora, language normalization, weights, thresholds,
audience assumptions or reviewer rubrics. Missing cohort evidence remains
missing; it is not borrowed from the sibling cohort or converted to zero.

Human Greenlight is held by an authenticated Human project editor authorized by
a host-owned custodian interface. Custodian calls occur outside M9 database
transactions and return duplicate-safe authorization leases bound to the exact
command, subject, custodian-policy revision and a maximum 30-second admission
window. M9 serializes the full command key before its final receipt/head check;
an existing exact receipt returns without reauthorizing. Every append-only
decision binds user/project,
exact candidate revision and payload digest, complete source/signal closure,
freshness policy, issuer, reason, issued time, expiry, scope and supersession.
Models, source adapters, donor checkpoints, scores and successful HTTP responses
cannot issue it.

Provider payload deletion never rewrites history into false evidence. M9 deletes
the governed raw, identity, normalized-value, derived-result and assessment
payloads from an erasable evidence store; append-only PostgreSQL rows retain
only opaque refs and those non-reversible proofs the exact policy permits. M9
appends a non-sensitive tombstone, records dependency invalidation, and marks
dependent signals, candidates and Greenlight decisions `INVALIDATED` through their
validity projections. Greenlight decisions themselves stay custodian authority. Reads fail closed
while propagation is incomplete. Existing Canvas history remains immutable
historical exploration, but a stale Greenlight cannot seed a new Canvas
revision.

## Considered options

- **Extend M8 Learning:** rejected because market discovery, Human Greenlight and
  factual-source custody are distinct from M8 observation/recommendation
  authority and would reopen M8's accepted payload contract.
- **External scraper/microservice/data lake:** rejected because it introduces a
  second runtime/store and weakens project scoping, policy evidence, deletion
  lineage and transaction recovery.
- **Manual-only subsystem:** retained as the safe baseline adapter, but rejected
  as the governing architecture because it cannot close the intended discovery
  loop when authorized sources later become available.

## Consequences

- M9 can deliver evidence-backed opportunity comparison without any live
  provider credential or call.
- Adding a provider does not change public opportunity contracts, but enabling
  it requires current capability evidence, adapter fixtures and independent
  review.
- M9 exposes separate opportunity dimensions rather than one opaque virality
  score. V1 does not define a universal overall score.
- M7/M8/Factual seams remain prerequisites, not copied implementations.
- PostgreSQL transaction-scoped command-key guards serialize absent-receipt
  races; immutable receipts, not guard hashes, remain idempotency authority.
- M9 design acceptance is valid only through the milestone-specific contract
  and strict schemas derived from ADR-0080's accepted review policy. The
  acceptance record schema, sealed-review schema and cross-record verifier are
  separate controls: schemas close each document shape, while the verifier
  enforces distinct reviewer identity, exact candidate/contract/rubric
  equality, output hashes, complete PASS checks and seal-before-share order.
  The repository entry point resolves all evidence from Git objects, proves the
  candidate and acceptance parent lineage, recomputes every candidate artifact
  and status-only ADR hash, enforces the exact four-path acceptance commit,
  and rejects a dirty acceptance tree.
  Acceptance records do not carry self-attested command output; the successful
  Git-backed verifier process is the gate evidence.
- This proposed ADR and its design authorize documentation and review only. They
  do not authorize code, migrations, provider access, credential use, runtime
  activation, publication or production approval.

# M10-A A0/A1: pure contract and digest packet

Status: PROPOSED FOR TWO INDEPENDENT REVIEWS. No acceptance or implementation eligibility is recorded by this document.

## Sequencing amendment and authority

The user explicitly paused M9 and requested M10 on released V2, then repeatedly
requested continuation. This packet implements that sequencing at a narrow
boundary: original M10-A Tasks A0 and A1 only. It does not accept M9, waive
reviews, qualify a Human custodian, or accept durable Factual Authority. The
original ADR-0080 acceptance and full M10 design gate remain immutable.

A0/A1 may proceed only after two independent reviews accept this exact bounded
candidate and its separate `R2_M10_CONTRACT_DESIGN_ACCEPTANCE.json` envelope.
The original `R2_M10_DESIGN_ACCEPTANCE.json` remains absent/unaccepted. The
bootstrap default still requires the complete original predecessor chain.
Selecting `--packet contracts` reads a different acceptance record and cannot
convert it to full-M10 eligibility. Positive output is exclusively
`CONTRACT_IMPLEMENTATION_ELIGIBLE` with the exact A0/A1 file allowlist.

Why this boundary: pure types, validation and canonical digest vectors consume
neither an M9 research service nor a live quality/factual authority. Requiring
operational adapters or PostgreSQL state transitions before defining their
contracts creates a circular prerequisite. Those operational proofs remain
mandatory in their owning original A3/A5/A6 tasks before operation/acceptance;
they are not silently removed from full M10. A0/A1 completion is not M10-A
completion, full design acceptance, production activation or release readiness.

Prerequisites retained for this packet are the exact accepted M7/M8 source
lineage and released V2.0.8 base. Both acceptance artifacts have single-parent
acceptance commits and are ancestors of the released base. The packet manifest
binds their exact refs/bytes; a release label alone is insufficient. The old
M9 sponsor exception is not reused: it applied only to its named M9 candidate.

## Scope and execution

`R2_M10_CONTRACT_PACKET_2026-10-25.json` is the exact machine-readable definition.
It permits only the A0 scope verifier/tests and A1 contract/digest files/tests
plus a bounded packet evidence file. No ORM/model registry, migration, database,
probe process, queue, API, frontend, credential, provider or filesystem-export
path is allowed. Existing production files and M9 dirty work are preserved.

A0 rechecks the accepted contract envelope/source identity, exact allowlist,
clean owned paths and immutable migration graph, and AST-checks allowed imports
and forbidden runtime surfaces. No repository file is created on refusal.
A1 uses RED/GREEN contract and digest tests, existing canonical helpers, source
pins and corresponding affected regression tests. No host activation occurs.
Any needed file or behavior outside the manifest returns to a reviewed scope
amendment. A0/A1 ends at its clean candidate evidence, not at original A3.

## A1 normative field sources and corrections

Use the original 2026-09-16 spec §4.1 for all named A contract families and §5.1
for its A digest tags. Retain all seven observation variants, slot/requirement
semantics, independent-assessor evidence, Human-only dispositions, 30-second
leases, seven-day disposition maximum and 24-hour WAIVE maximum. No §4.2 B
contract or reserved B digest tag may enter A1. Corrections below take precedence
for this bounded candidate only; the original recovered files remain unchanged.

### Model base and identities

Define `M10ContractModel` explicitly as the repository R2 base with frozen=True,
extra=forbid and validated assignment. All collections are tuples or the reused
recursively immutable M8 `CanonicalJsonObject`; freezing a parent alone does not
freeze a dict or mutable nested host model. Aware timestamps are required; the
existing canonical helper serializes them in UTC. Reject nonfinite numeric data.
M10-created entity IDs use UUIDv7 strings; foreign host IDs, user/project/actor,
rule/slot/policy IDs and command IDs are exact nonempty identities, with no
leading/trailing whitespace or control characters. Do not relabel a host ID as
a newly created M10 UUID. All physical commands/receipts are scoped by
user_id, project_name, actor_id, operation and command_id.

### Exact master binding

Replace the prior mutable metadata-body proposal with:

```text
ArtifactMetadataSnapshot
  artifact_key: ExactIdentity
  body: CanonicalJsonObject
  metadata_digest: Sha256Digest
MasterDependencyEdge
  parent_artifact_key: ExactIdentity
  child_artifact_key: ExactIdentity
  dependency_ref: ExactIdentity
MasterBindingV1
  schema_id: Literal[m10.master-binding.v1]
  user_id, project_name: ExactIdentity
  root: existing frozen MasterHeadSnapshot
  dependency_heads: tuple[MasterHeadSnapshot, ...]
  metadata_snapshots: tuple[ArtifactMetadataSnapshot, ...]
  dependency_edges: tuple[MasterDependencyEdge, ...]
```

Reuse the host metadata type for temporary validation of a thawed copy, never
store that mutable model inside the frozen contract. Require a complete normalized
metadata body, one snapshot per consumed head and no extra/missing keys. Root
cannot also be a dependency. Sort heads/snapshots by artifact key and edges by
(parent, dependency_ref, child). Reject duplicate keys/edges and cycles; every
dependency head must be reachable from root. Each metadata `master:` dependency
must have exactly one edge and each edge must name such a dependency. Its
fingerprint equals the child's content digest (host prefix normalization only);
its version is the existing resolver representation candidate_id@host_version_ref
from the child's approved metadata. Never derive host_version_ref from the DB
master_version. Each head's selected candidate and approval reference agree with
its metadata; malformed/unapproved/mismatched bodies are rejected. Non-master
snapshot references remain bound metadata, not new M10 authority heads.

AssessedSubject replaces its ambiguous approved_master_id display field with
master_binding and master_binding_digest. artifact_ref equals root.object_ref;
artifact_digest equals root.content_digest; content_basis_digest binds the full
root metadata content basis; existing caption/audio digests remain optional and
bound. Pure validation establishes internal coherence, not that this is the
current real master or that bytes exist. A5 still resolves/revalidates all bodies,
bytes and external authority references under the canonical host row locks.

QualityProfileRevision gains explicit user_id/project_name scope. The original
QualityPolicyV1 gains a nonempty unique rule_ids catalog: probe rules and slot
rule references must refer to it. This avoids treating technical probe-rule IDs
as the only valid narrative/accessibility rule IDs. Requirement IDs and slot IDs
are unique within the profile; rule IDs are separately unique. ALL requires all
slots, N_OF_M bounds are valid, references exist and escalation is acyclic.
INAPPLICABLE must be an explicitly allowed slot state plus a bound observation;
missing evidence is never an applicability reason.

### Authorization request cycle and retained lease separation

The two retained action-bound lease types remain distinct. Validate a strict
positive issued_at..admit_not_after window no longer than30 seconds. The
contracts describe evidence; constructing one never grants Human authority.
Existing Showrunner/admin identity does not satisfy either action automatically.

Define a `QualityProfileDraft` with scope, profile/revision/parent, cohort/surface,
full policy/policy_digest, supersession effect, created_by and created_at. It has
no authorization receipt, admission timestamp or final profile digest. A
`ProfilePublicationSubject` binds its draft digest, exact scope/actor and expected
profile revision. `ProfilePublicationAuthorizationRequest` contains that subject
and the command envelope. Final QualityProfileRevision records the original
publication-subject/request digests and the actual publication lease/admission
fields. Compute its profile digest only after those fields exist. This prevents
authorization from depending on a digest that contains its own future receipt.

Define `DispositionSubject` with exact scope/actor, subject/run/profile identities
and digests, decision, sorted waivers, reason, requested expiry and expected
current-disposition version. `DispositionAuthorizationRequest` contains it and
the command envelope. Request digests cover domain/version, scope/actor/operation
and semantic subject, excluding command_id and request_digest itself. The lease
binds command_id separately. Final QualityDisposition retains its lease/policy/
evidence/admitted-time fields; its digest excludes only its own cache field.
No final digest, commit time or issued receipt can feed its own preflight subject.

Command operation is a closed A set: PUBLISH_PROFILE, COMPLETE_RUN,
ISSUE_DISPOSITION. No packaging/export operation is admitted. Exact replay is a
future repository property, not a constructor side effect. Validate local parent,
revision, count, aware-time, expiry and waiver constraints in A1. Cross-record
authorization, external qualification, runtime currentness, evidence existence,
DB-time admission, CAS/replay and PostgreSQL interleavings remain A3/A5/A6 proof
obligations and are not claimed by this packet.

### Digest closure

Reuse exact V2 M8 canonical bytes. Each A digest hashes
{domain: <registered tag>, contract_version: "1", body: <normative body>}.
Add explicit A tags m10.master-binding.v1, m10.artifact-metadata.v1,
m10.content-basis.v1 and m10.quality-profile-draft.v1 to original §5.1.
Every body's own digest cache is excluded, while referenced-body digests and
full semantic bodies remain bound. QualityProfileDraft excludes future admission
fields; final profile body includes them. Observation closure is variant-tagged
and deterministically ordered by requirement_id, slot_id, observation_id.

M10 contracts validate shape and internal coherence; digest helpers recompute
and verify cached digests without a contracts-to-domain import cycle. A3/A5/A6
must invoke those verifiers before authority writes. No typed value is declared
trusted merely because a checksum field has the right shape. Reject unknown
and every reserved B tag, never use a prefix-based permissive registry.

Existing draft encoding vectors are historical design experiments, not golden
A1 admission vectors. Regenerate valid deeply immutable metadata/edge vectors
under this packet, include every normative field in mutation coverage, and retain
the rejected vector history through Git instead of claiming old invalid metadata
is a validated host subject.

## Review/freeze boundary

Two blind qualified independent reviewers evaluate this packet, not the whole
M10 runtime. Their records must bind the same candidate, conflict declarations,
qualification evidence and rubric R2_M10_CONTRACT_REVIEW_V1. Reviewers must trace
M7/M8 acceptance and authority boundaries, assess exact scope/no activation,
immutability/hash cycles, subject closure and the absence of a grant bypass.
Required skips/material unknowns must be empty for A0/A1; explicitly deferred
operational proofs are outside this packet and remain blockers of full M10.

A separate acceptance commit may add only the bounded acceptance JSON and new
review artifacts under docs/r2/evidence/m10-contract-reviews/. It does not change
ADR-0080/0082 status, the original acceptance contract, production or M9. The
bootstrap must verify that bounded scope, accepted M7/M8 predecessors, source/
schema/tests/packet bytes, same candidate and review custody. Without that exact
accepted envelope it remains REFUSED. No sponsor acceptance or reviewer PASS
is inferred from this proposal or from the user's request to continue.

### Exact additional request fields

The additional request families below are field declarations, not an authority
adapter. ExactIdentity and Sha256Digest are the constrained scalars above;
integer expected versions admit0 for genesis and never negative values.

```text
QualityProfileDraft
  user_id, project_name: ExactIdentity
  profile_id: M10Uuid7; revision: int>=1; parent_revision: int>=1 | None
  cohort_id, product_surface: ExactIdentity
  policy: QualityPolicyV1; policy_digest: Sha256Digest
  supersession_effect: SupersessionEffect
  created_by: ExactIdentity; created_at: AwareDatetime
ProfilePublicationSubject
  user_id, project_name, actor_id: ExactIdentity
  profile_draft: QualityProfileDraft
  profile_draft_digest: Sha256Digest
  expected_profile_revision: int>=0
ProfilePublicationAuthorizationRequest
  command: CommandEnvelope
  subject: ProfilePublicationSubject
DispositionSubject
  user_id, project_name, actor_id: ExactIdentity
  subject_digest: Sha256Digest
  quality_run_id: M10Uuid7; quality_run_digest: Sha256Digest
  profile_id: M10Uuid7; profile_revision: int>=1
  profile_digest: Sha256Digest; decision: DispositionDecision
  waiver_bindings: tuple[WaiverBinding, ...]
  reason: nonempty string; requested_expires_at: AwareDatetime
  expected_disposition_version: int>=0
DispositionAuthorizationRequest
  command: CommandEnvelope
  subject: DispositionSubject
```

Require request command scope/actor to equal subject scope/actor; draft scope and
created_by equal the publication subject; revision equals expected_profile_revision
+1 and parent_revision is None exactly for genesis, otherwise equals the expected
revision. Publication uses PUBLISH_PROFILE and disposition uses ISSUE_DISPOSITION.
The finalized profile gains publication_subject_digest and
publication_request_digest, with the explicit field names in this paragraph.
The finalized disposition retains its exact run/subject/profile, authority and
expiry fields from the original spec. Cross-record validity is verified before
future writes, not asserted by these data constructors.


## Review repair: complete command surface and artifact identity

### Run completion request

The original port's undeclared CompleteRunCommand is concretized as follows.
These are data constructors, not a collecting-run repository or sealing service.

```text
ObservationBinding
  observation_id: M10Uuid7; observation_type: ObservationType
  observation_digest: Sha256Digest
  requirement_id, slot_id: ExactIdentity
RunCompletionSubject
  user_id, project_name, actor_id: ExactIdentity
  run_id: M10Uuid7
  subject: AssessedSubject; subject_digest: Sha256Digest
  profile_id: M10Uuid7; profile_revision: int>=1; profile_digest: Sha256Digest
  observations: tuple[ObservationBinding, ...]
  observation_closure_digest: Sha256Digest
  requirements_digest: Sha256Digest
  execution_refs: tuple[ExactIdentity, ...]
CompleteRunCommand
  command: CommandEnvelope
  subject: RunCompletionSubject
```

Require COMPLETE_RUN; command scope/actor equals completion subject scope/actor,
and embedded master-binding scope agrees. run_id identifies the already allocated
run being completed, so it is semantic input and must be hashed. The sealed
QualityRun must retain this run_id and exact subject/profile/requirements/
observation/execution bindings. Constructor checks do not prove allocation or
ownership in a real repository; A5 must do so.

Observations are nonempty, unique by observation_id and ordered by
(requirement_id, slot_id, observation_id); reject contradictory duplicate IDs.
Execution refs are unique and sorted. Closure verification recomputes the exact
normalized ObservationBinding tuple and checks its declared digest. At A5,
each binding must match the full fetched immutable observation's variant,
identity, requirement/slot and recomputed digest. A binding is not proof that the
observation/evidence exists. Do not substitute a slot count or untagged digest
list for this closure.

The final QualityDisposition also gains profile_id/profile_revision explicitly.
They must agree with DispositionSubject and the resolved QualityRun at A6; a
digest alone is not the identity selector. All added identity/revision fields
participate in request/subject/final-result digests and mutation/roundtrip tests.

QualityRun's local ref invariants: run observation IDs are nonempty/unique,
slot-result (requirement_id,slot_id) pairs are unique, per-row observation refs
and digests are parallel/nonempty, and no primary observation is counted in two
slots. Their union equals the run's observation refs. Escalation refs name bound
observations in that same union; actual escalation policy, qualification,
independence and whether SATISFIED is justified are evaluated at A5 against the
resolved profile, not trusted from a constructor or caller status.

### Closed hash-body projection table

This table resolves cache/exclusion ambiguity; it supplements original §5.1.
All digests use the previously defined domain/version/body envelope. Own-cache
exclusion is top-level only; referenced-body digests are never stripped.

| Domain/body kind | Exact normative body | Own cache excluded |
| --- | --- | --- |
| m10.quality-policy.v1 | Full QualityPolicyV1 including added rule_ids | None |
| m10.quality-profile-draft.v1 | Full QualityProfileDraft, including full policy and policy_digest | None |
| m10.quality-profile.v1 | Full finalized QualityProfileRevision, including draft subject/request and publication/admission fields | profile_digest only |
| m10.artifact-metadata.v1 | Full ArtifactMetadataSnapshot, including artifact_key and normalized immutable host metadata body | metadata_digest only |
| m10.master-binding.v1 | Full MasterBindingV1 with normalized heads/snapshots/edges and referenced metadata digests | None |
| m10.content-basis.v1 | Complete normalized content_basis object from root metadata | None |
| m10.assessed-subject.v1 | Full AssessedSubject, including master binding/full referenced digests | None |
| Original seven variant-specific observation domains | Entire matching closed-union observation body, including all common bindings and variant fields | None |
| m10.observation-closure.v1 | Normalized tuple of full ObservationBinding bodies | None |
| m10.assessment-requirements.v1 | Ordered AssessmentRequirement tuple, including full ordered slots and escalation fields | None |
| m10.quality-run.v1 | Full final QualityRun with all identity/subject/profile/closure/slot/execution/completion fields | None |
| m10.waiver-binding.v1 | Full WaiverBinding | None |
| m10.quality-disposition.v1 | Full QualityDisposition including explicit profile identity/revision and issuer/lease/admission/expiry | None |
| m10.profile-publication-subject.v1 | Full ProfilePublicationSubject, including full draft and its digest | None |
| m10.disposition-subject.v1 | Full DispositionSubject including explicit profile identity/revision | None |
| Three original *-request.v1 domains | Object with command scope/actor/operation plus full corresponding publication/completion/disposition subject | command_id and request_digest; future result receipt/commit fields are absent, not recursively removed from referenced evidence |
| m10.command-key-guard.v1 | Object of user_id,project_name,actor_id,operation,command_id | request_digest is absent from this projection |

Add m10.observation-closure.v1 explicitly to the closed A registry, in addition
to the four added tags above. No implicit digest field is added to a contract
merely because a helper returns its digest. Referenced preallocated entity IDs
and existing execution/receipt references remain semantic data; only result
fields created by the operation itself are excluded from its preflight request.
Requirements/slot tuple order remains policy-declared order. Only explicitly
set-like heads/snapshots/edges, observation bindings, execution refs and waiver
bindings normalize to the documented stable key order.

### Exact master-ref mapping

For each master: edge, decode parent and child artifact keys using the existing
ArtifactKey decoder, require canonical encode/decode roundtrip, require both
EPISODE_VIDEO and the same positive episode, then require:

```text
shot_ref = dependency_ref with exactly one leading "master:" removed
validate_m3_target_ref(shot_ref) succeeds
child_artifact_key == ArtifactKey.episode_video(parent.episode_number, shot_ref).encode()
```

This is the pinned GoldenAHostIntegration.artifact_key_for/ApprovedMasterResolver
mapping, not a new wire encoder. Reject an empty/unsafe ref, alias encoding,
other key kind, cross-episode child and master:A->child B even when candidate,
version and content digest coincide. Unknown master-ref identity families fail
closed pending a separately reviewed extension. Non-master dependency owners
remain bound snapshots and are not rewritten into these edges.

A1 may import only the qualified pure ArtifactKey/ArtifactKind identity surface
and validate_m3_target_ref leaf, not instantiate GoldenAHostIntegration or a
manifest adapter. Importing a containing host module may load existing class
definitions; it does not authorize invoking its filesystem/authority methods.
A0 checks exact direct imports/calls and source pins, while review/side-effect
tests inspect the allowed transitive module initialization.

Before delegated host parsing, reject whitespace/control normalization in raw
identity fields. Existing already validated host snapshots must themselves hold
exact identities. Do not let a permissive nested host parser silently trim a
caller-supplied key into a different authority identity. Metadata must equal its
complete normalized host representation before it is frozen.

Required A1 additions: full request-family roundtrip/mutation coverage; same-
content different-target, alias and cross-episode refusal fixtures; explicit
request/result cache-cycle vectors; nested-mutation and raw-identity tests.
These are required implementation tests, not claims of current A1 execution.

Exact request body layout is
`{command: {user_id, project_name, actor_id, operation}, subject: <full subject>}`;
key names and nesting are fixed. Guard body is the flat five-field object
`{user_id, project_name, actor_id, operation, command_id}`. No alternate flattening,
renaming or generic recursive cache stripping is conforming. Use StrictInt for
new M10 ordinal/count/version/TTL/byte-limit fields so booleans and numeric
strings cannot impersonate integer identity or policy values. Validate raw host
head version integers before delegated host parsing as well.

For metadata normalization, compare canonical bytes of the input frozen JSON
against canonical bytes of the temporary host model's full model_dump(mode=json)
representation. Ordinary Python equality is insufficient because True equals1.
Store only the canonical immutable representation, never the temporary model.

The bounded bootstrap also protects its consumed host/canonical/metadata/identity
source and namespace-initializer files as dirty dependencies, rather than calling
them unrelated work. Owned/consumed index entries marked assume-unchanged or
skip-worktree are refused even when Git's normal diff hides changed bytes. The
verifier never clears those flags, rewrites the index or discards hidden work.

Each master: child's metadata contract_ref.contract_type is ShotSpec, matching
ApprovedMasterResolver's existing check. Every head content digest and dependency
fingerprint must be valid64hex, allowing the host's existing optional sha256:
prefix; comparison follows the pinned normalize_sha256 semantics. Preserve the
foreign head's wire value in the binding. AssessedSubject.artifact_digest is the
canonical prefixed digest and compares to the root through that normalization,
not a string-format alias. Invalid opaque digest strings cannot form a valid
internal subject merely because two strings happen to agree.

# M10-A concrete dependency bindings

Status: PROPOSED; additive to the original design and V2 rebase, not acceptance.
Base: r2-v2.0.8 /14565f9d8a181654be272267a097ddafe2c87c79.

## MasterBinding

Use existing `MasterHeadSnapshot` fields without a new encoding of host identity:
artifact_key, master_version, candidate_id, object_ref, content_digest and
approval_record. The proposed frozen envelope is:

```text
MasterBindingV1
  schema_id = m10.master-binding.v1
  user_id, project_name: nonempty exact scoped identities
  root: MasterHeadSnapshot
  dependency_heads: tuple[MasterHeadSnapshot, ...]
  metadata_snapshots: tuple[ArtifactMetadataSnapshot, ...]
ArtifactMetadataSnapshot
  artifact_key: exact host key
  body: R2ArtifactMetadata (full immutable serialized body)
  metadata_digest: digest of recomputed body
```

No caller-supplied digest is authoritative. Resolve root and every consumed
source head from the scoped host repository. Require one metadata snapshot per
root/dependency key; no duplicate heads, duplicate metadata keys, unconsumed
extra keys or root in dependency_heads. Sort both tuples by exact artifact key.
Validate approval_record and selected candidate against the database head and
candidate object; host_version_ref is host-owned and must be resolved by the
host mapping, never inferred from an integer display version. Verify actual
private bytes against content_digest before assessment. Recompute every body
and exact transitive currentness closure under the caller transaction guard.

Domain bytes use existing `r2.advanced_creative.digests.canonical_json_bytes`:
`{domain: m10.master-binding.v1, contract_version: "1", body: <full binding>}`.
AssessedSubject gains master_binding plus master_binding_digest; existing
artifact/content-basis/caption/audio fields must agree with that closure. The
new A domain is an explicit proposed amendment, not one of B's reserved domains.
Design vectors must show source master, approval, scope, content basis and byte
changes alter the digest; production A1 must additionally validate contracts.

## Custodian requests and default refusal

The retained `ProfilePublicationAuthorizationLease` and
`DispositionAuthorizationLease` are separate action contracts. Publication
request binds full command scope/actor, profile revision/parent, policy and
profile body digests, supersession effect and expected profile head. Disposition
request binds full command scope/actor, subject/run/profile digests, decision,
sorted waivers, reason, expiry and expected disposition head. Request digest
excludes command_id; lease binds it separately and also binds the exact action.

At admission, DB time must satisfy issued_at <= now < admit_not_after, with a
strict positive window <=30 seconds. Final admission rechecks the scoped current
custodian policy and revocation identity on the same transaction; a historical
lease cannot survive a revoked grant. Exact historical replay returns its
receipt without making a fresh currentness claim.

`CurrentShowrunnerGrantReader.require_current_locked` verifies an existing
project/principal Showrunner grant with DB time, but its role is only
HUMAN_SHOWRUNNER. It does not qualify either M10 action. Do not change that role
contract or reinterpret admin, CurrentUser or M8 authority. The M10 host adapter
must deny both actions until separately qualified action/subject/policy custody
exists. No qualified M10 adapter is claimed by this packet; A3/A6 operational
admission remains blocked. This gap is not solved by inventing another grant
ledger. Reuse the host's current-grant read/custody machinery through a reviewed
scope amendment and prove revocation interleavings before activation.

## Factual dependency

`ClaimLedger`/`ResearchPack` contracts and Golden-A loader provide structures
and fixtures; they do not provide an accepted durable currentness/correction/
withdrawal service. Required factual observations need a scoped receipt binding
exact ClaimLedger and ResearchPack bodies/digests, correction/withdrawal head,
coverage, observed_at and validity, with transactional revalidation against the
owning authority. Until qualified, operational factual profile admission is
blocked. No fixture fallback or optional-slot conversion is allowed. M10 has
no factual write port; M9 work is untouched.

## Sequencing and migration

User instructions prioritize M10 on released V2 while keeping M9 paused. This
permits this design packet and its read-only bootstrap. A scoped sequencing
amendment is proposed for M10-A only: remove reliance on M9 opportunity/source
acquisition code and use released M7/M8 plus separately qualified factual and
custodian dependencies. It neither accepts M9 nor removes factual/authority
requirements. Normative reviewers must bind the amendment and original
architecture contract hash in a separate acceptance; do not alter the old
accepted contract or let a caller flag bypass it. The first bootstrap continues
to enforce the original four-owner prerequisite chain until that amendment is
independently accepted and its verifier/schema changes are reviewed.

Migration predecessor is the observed singleton918c4a0e0001. A proposed revision
ID is derived as first12hex(SHA256(UTF8("r2.m10a.migration.v1:" + base_commit))).
Check collision against the full migration tree. Re-derive only if the reviewed
base changes. No migration is created/executed by this design packet. Freeze
its exact filename and owned registries only with the acceptance candidate.

Original A owned production paths remain the original plan's exact list. New
design-owned paths are the bootstrap script, mirrored unit/integration tests,
this binding document, design acceptance schema and proposed design evidence.
No broad `r2/`, `lib/`, `server/` or directory allowlist grants new authority.
Original A0 must re-derive the explicit production allowlist before code starts.

## Design bootstrap protocol

The proposed acceptance schema and verifier provide structural custody checks,
not verification that a named person is qualified or that their declaration is
true. Normative reviewers and the acceptance custodian remain responsible for
that substantive authority. Review records use conflict_declaration NO_CONFLICT,
the exact reviewed candidate, UTC aware timestamps and a separate hashed JSON
artifact per reviewer, materialized in the acceptance commit. The verifier
requires distinct reviewer identities, neither equal to author_id, identical
record/envelope bodies and PASS on the same candidate. This does not prove
blindness by itself; review custody must be examined at normative acceptance.

For the original prerequisite policy each owner has a hash-bound acceptance
artifact at an ancestor acceptance commit whose direct parent is its named
accepted_candidate_head. Required statuses for this proposed envelope are
M7_IMPLEMENTATION_ACCEPTED, M8_IMPLEMENTATION_ACCEPTED,
M9_IMPLEMENTATION_ACCEPTED and FACTUAL_IMPLEMENTATION_ACCEPTED. These are
expected record contracts, not assertions that such records currently exist.
No field or CLI flag enables the proposed M9 sequencing exception.

Bootstrap-only additional refusal codes are M10_SCHEMA_FREEZE_FAILED,
M10_REVIEW_INDEPENDENCE_FAILED, M10_MIGRATION_BOUNDARY_INVALID,
M10_OWNED_PATH_DIRTY and M10_SCOPE_EXPANSION_REQUIRED. They supplement the
original stop-code table for this design-owned tooling and grant no new runtime
state. Missing real design acceptance returns M10_DESIGN_NOT_ACCEPTED.

The bootstrap reads committed Git objects with replacement refs disabled,
parses migration assignments with AST/literal_eval without imports, checks exact
single-parent acceptance custody and complete migration graph equality across
base/candidate/acceptance/current HEAD, and rejects bound or owned dirty files.
Ignored untracked owned files and uncommitted Python migrations also block.
Unrelated dirty work is neither altered nor treated as owned by M10. It writes
only its JSON diagnostic to stdout; no stop receipt is created in the repo.

[Encoding vectors](../../r2/evidence/R2_M10_MASTER_BINDING_VECTORS.json) bind the
proposed domain and exact existing canonical source. They test byte sensitivity,
not production schema validity, identity mismatch refusal or transaction safety.
These latter proofs remain required before the corresponding A implementation
can be accepted.

Bootstrap repair constraints: Git commands ignore inherited Git-selection/config
variables and disable graft/lazy-fetch/protocol resolution. Detect staged and
working-tree changes independently, including ignored owned files. Compare fresh
HEAD with the pinned commit before and after verification; this is a point-in-time
check, not a grant surviving subsequent source changes. Candidate changes are
limited to the exact design-owned set, not all documents under docs/.

## Bounded pure-source implementation base

For the separately reviewed A0/A1 packet only, released V2.0.8 remains the release ancestor; verified local checkpoint dda0f273e035615e1c10a67f8712279d23b7053c is the derived implementation base. Import identity/target-ref leaves from r2.artifact_identity and metadata types from r2.contracts.artifact_metadata. Legacy host paths describe owner behavior only and must not be imported by pure contracts. The bounded packet's exact base/evidence/closure pins take precedence for this import boundary. Original operational predecessor, factual, custodian and full-M10 gates remain unqualified.

For the bounded packet, every root and dependency metadata snapshot's contract_ref.id equals the resource decoded from its canonical artifact key, and that key equals its corresponding head key. Master children also equal the validated shot_ref. The packet defines waiver full-canonical-byte ordering/duplicate logical keys and closes policy catalog membership for probe, freshness, slot and waiverable references; original operational currentness/authority checks remain deferred, not inferred from these constructors.

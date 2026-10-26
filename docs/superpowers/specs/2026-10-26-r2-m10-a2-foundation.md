# M10 A2: pure errors, ports and parity

PROPOSED. This packet continues the user's explicit sequential M10 instruction from reviewed A0/A1 baseline655080af. It authorizes source-only A2 after two independent design PASS decisions on the same candidate and a separate pinned acceptance. It does not accept full M10, M9, runtime adapters, Factual/Human authority, provider calls, probes, migrations, packaging/export or deployment.

## Scope and ownership

The packet JSON is the exact10-product-path and4-design-path allowlist. A0/A1 and its accepted bootstrap, schemas, contract fields,25digest domains and3command operations are immutable inherited inputs. Do not change their guard to admit A2. On an A2 descendant, the old A0/A1 scope guard correctly refuses the expanded paths; the new A2 guard has a separate `M10_A2_SCOPE_OK` result. Neither result is full-M10 eligibility.

The79 baseline pins include all consumed A1 source, pure closure, namespace/config/lock files, characterized host sources, design/acceptance/review evidence and the M8 parity seam/tests. They are read/protection inputs, not blanket import permission. The M8 parity schema/fold stay unchanged. Migrations are immutable, including dirty new/deleted revision files.

## Typed errors

Use exactly the20 codes in original M10 spec section9, one named M10Error subclass per code. Registry maps code to concrete class and is immutable; inverse lookup uses exact class identity, never an arbitrary exception's `.code`. Error constructors discard supplied details and expose only their registered code in args/str/repr. Direct base or unregistered subclasses cannot masquerade as a registered error.

`error_for_code(code)` returns the registered error, or RequiredEvidenceMissingError for unknown input. `error_payload(exc)` returns exactly `{code: <known-code>, message: <same-known-code>}`; unknown exceptions/subclasses map to M10_REQUIRED_EVIDENCE_MISSING. No prompts/media/provider/reviewer messages, args, cause/context or traceback enter the payload. This is the future outward boundary; it does not promise that arbitrary caller logging of a raw exception is safe. ProfilePublicationUnauthorizedError maps specifically to M10_PROFILE_PUBLICATION_UNAUTHORIZED, distinct from disposition authorization. Declaring B-related failure codes does not implement a B operation.

## Port data and interfaces

All four descriptors inherit the unchanged M10ContractModel, use its exact identities, UUID/digest types where named, extra-forbid and deep immutability. They introduce no new entity IDs or digest tags.

- ProbeRequest: user_id,project_name,actor_id,execution_ref: ExactIdentity; subject:AssessedSubject; profile:QualityProfileRevision; rule:ProbeRule. Its scope equals both profile scope and subject.master_binding scope; rule equals a declared profile.policy.probe_rules member. actor_id need not equal the profile creator. execution_ref is an opaque M7 execution reference, not a receipt/admission grant. A4 must verify embedded caches, qualified M7 execution custody, actual config/tool identity and resource bounds before execution. ProbeReceipt is an alias of the existing TechnicalObservation.
- FactualReadRequest: user_id,project_name,actor_id:ExactIdentity; subject_digest:Sha256Digest; claim_ledger_projection_ref,research_pack_ref:ExactIdentity.
- FactualReadProjection: user_id,project_name:ExactIdentity; observation:FactualObservation; validity_receipt_ref:ExactIdentity; validity_receipt_digest:Sha256Digest. It losslessly retains withdrawal/status; no local `current` or `valid` boolean is admitted as authority. A5 must resolve/match scope, subject and requested ledger/pack refs and verify the actual current receipt under its qualified authority. Missing authority remains unavailable.
- EvidenceReference: user_id,project_name,ref:ExactIdentity; digest:Sha256Digest. Metadata handle only, no bytes, path access, resolver credentials or existence claim.

Exactly these eight Protocols, with async abstract methods only:

```text
QualityProfileReadPort.get_revision(*, user_id,project_name:ExactIdentity, profile_id:M10Uuid7, revision:int) -> QualityProfileRevision | None
QualityProfilePublicationService.publish(request:ProfilePublicationAuthorizationRequest) -> QualityProfileRevision
QualityProbePort.observe(request:ProbeRequest) -> ProbeReceipt
QualityRunService.complete(command:CompleteRunCommand) -> QualityRun
ProfilePublicationCustodianPort.authorize_publication(request:ProfilePublicationAuthorizationRequest) -> ProfilePublicationAuthorizationLease
QualityDispositionCustodianPort.authorize_disposition(request:DispositionAuthorizationRequest) -> DispositionAuthorizationLease
FactualReadPort.read_current(request:FactualReadRequest) -> FactualReadProjection | None
EvidenceReferencePort.get_exact(*, user_id,project_name,ref:ExactIdentity, expected_digest:Sha256Digest) -> EvidenceReference | None
```

Protocol annotations are not runtime input validation. Implementations at their owning later tasks must enforce positive revision, scope, ownership, cache/evidence/currentness, receipts and Human leases. No adapter is instantiated here. No Protocol receives Production Authority, network, filesystem, DB/session or export capability. There is no M10 disposition writer/service implementation.

## Parity

Reuse M8 report/row/enums byte-for-byte. `evaluate_quality_parity(report:DonorParityReport,current_head:str)->ParityVerdict` first refuses non-string, noncanonical/nonzero40hex HEADs and invalid report values, then calls the exact accepted M8 evaluate_parity. Revalidate a model dump to reject bypassed/malformed model copies. All normal eight-dimension decisions delegate; there is no parallel fold or trusted caller verdict. A pure fold cannot establish actual Git HEAD, donor fixture provenance or runtime qualification; those remain the invoking gate/reviewer's duty. Unknown/malformed values return BLOCKED, with no leaked exception text.

## A2 scope custody

After design review, a separate acceptance commit contains only R2_M10_A2_DESIGN_ACCEPTANCE.json and the two actual reviewer artifacts under m10-a2-reviews/. Record schema_version1, status M10_A2_DESIGN_ACCEPTED, author_id, baseline_head, design_head, exact scope, bound four design path/hash rows, two reviewer records with distinct identities/NO_CONFLICT/PASS/same head, and empty required_skips/material_unknowns. Bind reviewed_at UTC. No Human/sponsor grant is inferred. The implementation pins exact acceptance ref and artifact SHA, so a caller cannot substitute a synthetic record or repin the baseline.

`verify_m10_a2_scope.py` loads only the digest-verified immutable baseline bootstrap Git blob to reuse its public GitRepository/load_json. It checks real HEAD before/after; source file equals committed guard bytes; fixed baseline/design/acceptance ancestry and single-parent acceptance; design delta only4paths; acceptance delta only receipt/review artifacts; all design hashes and actual reviewer bodies match; all79 baseline hashes/modes at baseline/design/current HEAD match and are dirty/hidden-index protected; current delta after acceptance only10product paths; owned/consumed and migration dirty paths refuse. Unrelated dirty work is preserved. No repo write on refusal.

Fixed acceptance SHA/hash is the trust anchor, not a caller verdict. Baseline source/evidence is read at655080af, whose source/review history is pinned; the old guard is never run against a fictional live HEAD. File equality/no out-of-scope deltas preserve the accepted migration singleton without importing Alembic or inventing a new migration. Static A2 checks allow only pinned pure imports/stdlib and abstract Protocol async bodies; cold-process tests prove import side-effect boundaries. They are not a general Python sandbox.

Stop codes used by this guard: M10_DESIGN_NOT_ACCEPTED, M10_PREREQUISITE_NOT_ACCEPTED, POST_M8_BASE_SEAM_CHANGED, M10_SCHEMA_CHANGE_REQUIRED, M10_NETWORK_SIDE_EFFECT_FORBIDDEN. Read errors are sanitized. Missing/invalid acceptance remains refused, no product file is created by the guard. New/protected paths marked assume-unchanged/skip-worktree are refused without clearing flags.

## Verification and completion

TDD covers all20 error mappings, canary leakage/forged subclasses, frozen DTO scope/rule membership and roundtrips, explicit public port signatures/no executable async bodies, same-fixture M8 parity on every dimension plus empty/unbound/mixed cases, cold import traps, and real disposable-Git scope/refusal/index/provenance cases. No tests-only source generator or new dependency. Run affected A2/A1/M8 regressions and required backend static gates. Report actual HEAD/commands/results/limits, zero required skips and material unknowns. One final independent whole-packet implementation review, then bounded material repair/re-verification if needed.

A2 completion is source/interfaces only. A3 begins only with a separately qualified persistence/Human-custody packet; no protected old file or additional path is implied by 'continue'.

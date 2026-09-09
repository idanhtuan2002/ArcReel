---
status: accepted
---

# Narrative lifecycle separates immutable evidence from narrow acceptance authority

M5C shall introduce a Narrative-domain lifecycle boundary for durable drafting,
revision, selection, extraction, review, and delta-compilation history. The
boundary consists of a `NarrativeLifecycleEvidence` consistency model and a
narrow `NarrativeAcceptanceService`; it is not a Production Authority service
and it does not acquire Canon authority.

`DraftCandidate`, `NarrativeRevision`, extraction attempts/results,
`NarrativeChangeSet`, and compilation attempts/results are immutable evidence.
Authority does not reside in those records or in accepted prose. An append-only
`NarrativeAcceptanceDecision` is authoritative only for selecting a revision or
reviewed change-set lineage within the Narrative workflow. A mutable effective
head is a rebuildable projection of those decisions, not the decision history.

One effective accepted revision exists at a time for this stable scope key:

```text
(user_id, project_name, plan_id, scene_contract_id, canon_branch_id)
```

Exact `canon_version_id`, Plan version, SceneContract version, and
`context_pack_id` are immutable bindings of revisions, decisions, extraction,
and compilation. They are not scope-key fields, and implementations must never
fall back to a latest version. Supersession appends a decision and advances the
effective head with an expected-predecessor/OCC check; it never mutates or
deletes an earlier decision.

M5C shall store normalized prose inline as immutable evidence under the frozen
M5B byte contract. `content_hash` identifies prose bytes only. Opaque workflow
identifiers and semantic fingerprints bind content to its exact scope, bases,
context, provenance, and policy/compiler versions; equal prose under different
bases does not imply equal revision or acceptance identity.

Change-set review is per lineage/partition, not one aggregate acceptance per
revision. Each `NarrativeChangeSet` declares a lineage plus source-span and
semantic-effect coverage. A review decision accepts, rejects, or supersedes a
named lineage. Compilation must name the exact accepted decision references and
change-set IDs it consumes. Overlapping active source spans or semantic-effect
keys fail closed unless an explicit Human merge/ambiguity decision names the
competing inputs and records the chosen resolution. An extractor cannot accept
its own proposal, and a compiler cannot silently choose a latest change set.

`CanonDeltaCompiler` is a pure, deterministic proposal transformation over an
explicit reviewed change-set selection, exact Canon base, exact compiler/policy
versions, and explicit Human ambiguity decisions. Durable compilation
attempt/result records surround that pure transformation for restart, retry,
abstention, conflict, failure, and audit evidence. Exact retries must preserve
semantic output identity. Provider `outcome_unknown` is evidence, never an
acceptance; provider adapters or orchestration own reconciliation or a new
attempt rather than a generic M5C provider state machine.

The boundary ends at a `CanonDelta` proposal:

```text
accepted NarrativeRevision
  -> reviewed NarrativeChangeSet selection
  -> CanonDelta proposal
  -> existing M5A Canon approval and commit path
```

`NarrativeChangeSet` and `CanonDelta` remain different contracts. M5C shall not
introduce a Canon approval service. The existing M5A `CanonCommitApproval` and
`CanonTransactionService` remain respectively the Canon approval receipt and
sole Canon commit authority.

## Considered options

- Reusing the mutable draft quarantine or a boolean on `NarrativeRevision`
  cannot preserve immutable decision history, exact retry, or authoritative
  supersession semantics.
- Reusing Production candidate/approval services crosses the frozen Narrative
  and Production authority boundary even though their fingerprint and OCC
  patterns are useful donors.
- Treating accepted prose, an extracted change set, or compiler output as Canon
  collapses review and transaction boundaries and is rejected.
- A single lifecycle service with unrestricted writes would conflate evidence
  recording with acceptance authority. The accepted design exposes separate
  capabilities even if one database and unit-of-work implementation backs them.

## Consequences

- Acceptance transactions verify already-persisted immutable evidence, append
  a decision, and advance the relevant effective head atomically with OCC.
  Orphaned but unaccepted evidence is harmless and auditable.
- Multiple non-overlapping accepted change-set lineages may contribute to one
  compilation. Replacement supersedes only the named lineage.
- Read ports expose exact identities and bases; convenience projections cannot
  authorize acceptance or compilation.
- Retry keys cannot be reused with different semantic inputs. Ambiguous timeout
  outcomes cannot become accepted by retrying or by reading a latest head.
- M5C design must specify roles, ports, persistence constraints, state/result
  vocabularies, failure windows, and adversarial tests. It must preserve every
  invariant above and receive Human approval before an implementation plan is
  written.
- This ADR authorizes design work only. It does not authorize M5C
  implementation, migrations, workers, provider calls, or production changes.

## Amendment: decision authority and effective-selection semantics

This amendment is an authoritative narrowing of the decision above. It does not
replace the evidence/authority split, the stable `NarrativeWorkScope` key, or the
M5A Canon boundary.

The narrow Narrative acceptance authority owns three decision families:

- revision acceptance decisions select, reject, or supersede a
  `NarrativeRevision` for a `NarrativeWorkScope`;
- change-set review decisions accept, reject, or supersede a
  `NarrativeChangeSet` within one declared lineage/partition; and
- change-set conflict-resolution decisions record an explicit Human resolution
  among named, competing reviewed change sets.

`NarrativeAcceptanceService` is the owning boundary for all three families. The
design may expose more than one narrow command port or application-service class,
but every authority-bearing write must remain behind that boundary and use the
same append-only decision, exact-retry, and expected-predecessor rules. Writers,
extractors, compilers, providers, and orchestration may request or consume a
resolution; they cannot create one or infer one from model output.

A conflict-resolution decision must name the competing change-set and review
decision IDs, the overlapping source spans or semantic-effect keys, the chosen
resolution, and the Human actor and approval receipt. It is applicable only
while all named review decisions remain currently effective. Replacing a
resolution appends a new decision; it never mutates the old decision. The
compiler consumes exact applicable resolution-decision IDs as semantic inputs
and otherwise fails closed.

### Logical effective heads

Revision acceptance and change-set review have distinct logical head semantics:

```text
RevisionAcceptanceHead
  key = (user_id, project_name, plan_id, scene_contract_id, canon_branch_id)
  value = exactly one currently effective revision-acceptance decision

ChangeSetReviewHead
  key = (revision_acceptance_decision_id, change_set_lineage_id)
  value = at most one currently effective review decision for that lineage
```

Many non-overlapping `ChangeSetReviewHead` entries may coexist for one effective
revision acceptance. A replacement advances only the named lineage head. A new
effective revision does not inherit the prior revision's change-set heads.

These are logical constraints, not a requirement for two physical tables or two
classes. A shared projection is permitted only if its subject namespace, keys,
uniqueness constraints, and rebuild checks preserve both cardinalities without
allowing a revision decision to collide with or supersede a change-set lineage.
Every head remains a rebuildable lock/index projection; the append-only decision
chain remains the authority.

### Current authority and historical evidence

A new downstream workflow action must name exact decision IDs and verify from
the authoritative decision chain that each decision is currently effective for
its logical head. The head projection may accelerate and serialize this check,
but the head cannot independently authorize acceptance, extraction, compilation,
or Canon handoff.

Historical revisions and decisions remain immutable, addressable evidence. An
audit or deterministic historical replay may resolve their exact IDs and bases,
but it cannot treat a superseded or rejected decision as current authority for a
new downstream action. In particular:

- extraction for a new change-set attempt requires the named revision-acceptance
  decision to be currently effective;
- compilation requires the named revision acceptance, every named change-set
  review decision, and every required conflict-resolution decision to remain
  currently effective and mutually applicable; and
- a compilation attempt/result remains durable historical evidence if an input
  decision is later superseded, but a new M5A approval handoff must revalidate
  current effectiveness and fail closed rather than resurrect that result.

The durable attempt records the effective decision identities it observed. Any
acceptance or resolution change racing with downstream admission must be detected
by an expected-head/OCC check or by final revalidation before the next authority
boundary is crossed.

### Decision identity and exact retry

Every authority decision uses an opaque decision ID as its idempotency identity;
no prose hash, change-set hash, or compiler output hash is a decision ID. Exact
retry lookup occurs before stale-predecessor rejection. Reuse of a decision ID is
idempotent only when its complete canonical identity tuple is unchanged,
including, as applicable:

- decision family, action, and stable work scope;
- selected revision, change-set, lineage, and competing decision IDs;
- expected predecessor decision ID;
- exact Canon, NarrativePlan, SceneContract, and `NarrativeContextPack` bindings;
- Human actor identity and approval receipt; and
- conflict coverage, chosen resolution, and referenced resolution decisions.

Any mismatch is an identity conflict and writes nothing. `content_hash` continues
to identify normalized prose bytes only. Server-generated record timestamps are
audit metadata, not retry identity, unless they are part of the immutable Human
approval receipt supplied to the decision.

This amendment clears the identified authority ambiguity for M5C design work.
The design spec must preserve these logical decision families, current-effective
checks, retry ordering, and failure windows in its ports, persistence constraints,
state machines, and adversarial tests. It must still receive Human approval before
an implementation plan is written, and this amendment grants no implementation or
production authority.

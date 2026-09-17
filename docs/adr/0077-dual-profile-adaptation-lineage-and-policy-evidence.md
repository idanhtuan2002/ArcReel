---
status: accepted
---

# Dual-profile adaptation uses sibling branches and versioned policy evidence

M6 shall produce generic Western drama and Chinese short-drama `爽文` as two
independent sibling `AdaptationBranch` lineages rooted in the same immutable
parent Canon version. Each branch binds exactly one immutable
`AdaptationProfile` identity and version for its lifetime. A profile change
creates a new sibling branch; it never rewrites an approved map, screenplay, or
evaluation result and never resolves a policy as "latest".

`adaptation_policy` retains its frozen meaning as the four-value fidelity stance
`STRICT | FAITHFUL | FREE | INSPIRED_BY`. It shall not be overloaded with genre,
market, territory, or profile identity. Profile identity is a separate semantic
binding included in branch content identity, downstream provenance, and every
profile-evaluation input fingerprint.

Both profiles share one adaptation authority kernel and the frozen
`AdaptationBranch` → `AdaptationMap` → `ScreenplayArtifact` lifecycle. Profile
rules execute through pure, provider-neutral policy ports and produce immutable
`ProfileEvaluationReport` sidecars. Sidecars may block proposal or require an
explicit Human waiver according to a versioned rule disposition, but they do not
own map-entry approval, screenplay approval, screenplay locking, branch-head
advancement, or Canon mutation.

The generic-Western profile shall hard-fail only source-grounded structural and
integrity rules: exact lineage, reference closure, screenplay surface grammar,
continuity, and frozen Golden B constraints. Dramatic concepts such as problem,
goal/action, opposition, stakes, causality, revelation, reversal, and resolution
remain versioned rubric evidence or Human-scored advice; M6 shall not invent a
universal closed Western beat taxonomy.

The Chinese short-drama profile may port the pinned Huohuo `恨/爽/急/盼` and six
`爽型` surface only behind the project-wide donor gates. Source-parity checks keep
Huohuo's exact chapter-1-through-8 applicability. They shall not assert that
every 60–120-second slice completes all four beats or has exactly one `爽型`
without a separately measured, versioned R2 corpus rule.

Take-derived shot vocabulary enters through `ShotSpecV2`, not by changing the
serialized field set or hash domain of `ShotSpec` v1. Version-dispatched
serialization, hashing, and schema-transition rules preserve all accepted v1
bytes and hashes and prohibit v2-to-v1 downgrade within a logical lineage.

## Approval and transaction boundary

An adaptation proposal transaction may append immutable branch, map, screenplay,
and evaluation evidence. Only the adaptation Human-authority boundary may append
map-entry decisions, screenplay approval, a policy-waiver decision, or the
atomic screenplay approval-and-lock decision that admits TakeDirector.

Because screenplay evidence is immutable, admission never toggles fields on an
existing row. It consumes exact proposal version N and atomically appends version
N+1 of the same screenplay identity with `approval_status=APPROVED` and
`locked_for_direction=true`, together with the decision that selects the N+1
hash. No other semantic change is permitted during this transition. This costs
one explicit version but avoids an approval-without-lock window and preserves
append-only replay.

Every authority command uses an opaque retry ID, complete semantic-tuple equality
before stale-head rejection, an expected predecessor, project/user scoping, and
one deterministic lock order. A profile report or waiver is applicable only to
the exact artifact bytes, branch/map versions, profile version, ruleset digest,
and named findings it binds. Any changed input invalidates the old waiver for a
new approval. A screenplay cannot lock while any referenced map entry is not
approved or any blocking profile finding lacks an applicable Human waiver.

PostgreSQL implementation shall use short `READ COMMITTED` transactions plus
explicit row locks and uniqueness/OCC constraints, following the accepted M5
authority pattern. It shall not rely on an absent-row `FOR UPDATE`, floating
reads, automatic retry, or a cross-Canon/adaptation transaction. First-head races
use unique genesis insertion followed by lock/reread; all failed commands write
nothing.

Any current-selection check that authorizes a consuming action shall verify the
append-only authoritative decision chain in the same transaction that holds the
relevant head lock. It loads the typed decisions through that transaction-bound
repository, validates subject, action, predecessor and generation consistency,
folds latest/effective state, compares every stored-head field, and proves the
effective decision selects the exact artifact being consumed before writing.
A checker that opens its own unit of work is suitable for offline integrity
reporting only; its result is not an authority capability and cannot be composed
with a later write without reopening the proof.

## Considered options

- A single branch containing both profile variants was rejected because one head
  serializes unrelated experiments and permits semantic mixing in later maps,
  approvals, and replay.
- An independently mutable profile overlay was rejected because branch and
  overlay heads can each be current while their pair was never reviewed; a
  stronger local opinion can also mask the approved profile.
- Copying the entire authority model per profile was rejected because lineage,
  approval, locking, retry, and OCC semantics are identical and would drift.
- Making all profile rules hard failures was rejected because the inspected
  first-party Western sources expressly do not define one universal dramatic
  form, while Huohuo's hard surface has a narrower chapter scope than Golden B.
- Adding optional Take enums to v1 `ShotSpec` was rejected because default or
  empty fields can alter accepted serialization and semantic hashes.
- Calling a reusable integrity checker in a separate transaction was rejected
  because a head can change between verification and admission. Database
  constraints alone were also rejected as insufficient: they cannot prove the
  semantic effective-state fold across `ACCEPT`, `REJECT`, and `SUPERSEDE`.

## Consequences

- A shared Canon source can be compared across both profiles without either
  output overwriting the other or claiming alternate-continuity Canon authority.
- Profile upgrades are explicit forks. This costs some duplicated maps and
  screenplays, but makes replay, approval, rollback, corpus comparison, and
  concurrent experimentation unambiguous.
- Profile-specific evidence remains queryable and auditable without contaminating
  shared authority contracts or downstream provider payloads.
- Authority services need a repository-bound pure fold in addition to any
  standalone integrity checker. This duplicates no rule body: both use the same
  pure fold, while only the caller holding the lock may grant a capability.
- Golden B contains one shared-source dual-profile pair: two separately
  reviewable 60–120-second slices rooted in the same pinned Canon version. This
  tests isolation and comparability without pretending to be a culturally native
  benchmark. Native-culture corpus expansion remains a later measured milestone.
- `AdaptationBrief` remains out of the M6 authority path until a separate decision
  defines its missing frozen shape and owner. M6 shall not invent it as a hidden
  approval or policy carrier.
- This ADR authorizes M6 design and implementation planning only. It does not
  authorize implementation, migrations, provider calls, production activity,
  deployment, or changes to the M5C implementation worktree.

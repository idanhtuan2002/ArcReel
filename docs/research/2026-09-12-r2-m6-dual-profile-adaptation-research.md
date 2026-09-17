# R2-M6 dual-profile adaptation research

Date: 2026-09-12
Status: research input only — not an ADR, design spec, implementation plan, or
architecture approval.

## 1. Question and fixed boundary

The Human-selected M6 product scope must support both:

1. generic Western drama; and
2. Chinese short-drama / `爽文`.

This note investigates how both profiles can share provider-neutral R2
authority contracts and production seams while profile-specific craft policy
stays outside authority. It does not decide the final contract shape, migration,
checkpoint split, or Golden B acceptance topology.

The frozen M6 flow is `Canon → AdaptationBranch → AdaptationMap →
ScreenplayArtifact → TakeDirector → ShotSpec → readiness → production →
ApprovedShotMasters → final drama`, with a 60–120 second, 2+ character, 5–10
shot acceptance slice that includes location, prop/state, secret/knowledge,
candidate-selection, and continuity evidence
(`docs/r2/R2_06_FROZEN_IMPLEMENTATION_ROADMAP.md:185-213`).

## 2. Source-derived observations

### 2.1 `take`: useful film vocabulary, not an R2 authority contract

The inspected upstream is
[`XucroYuri/take@47c17216b5ad74ee7dd376e8508266e29aefae2c`](https://github.com/XucroYuri/take/commit/47c17216b5ad74ee7dd376e8508266e29aefae2c).
The local pinned checkout resolves to that full SHA. The relevant source files
were clean in that checkout when inspected.

The film-language vocabulary is explicit and closed:

- seven shot sizes, from `extreme-wide` through `extreme-close`;
- eight camera angles, including eye-level, low/high, Dutch,
  over-shoulder, aerial, bird, and worm; and
- fourteen movements, including static, paired pan/tilt/dolly/crane/zoom,
  tracking, handheld, and orbit.

These values are defined in the upstream
[`models/enums.ts`](https://github.com/XucroYuri/take/blob/47c17216b5ad74ee7dd376e8508266e29aefae2c/packages/core/src/models/enums.ts#L7-L32).
The same file also defines lifecycle status, aspect-ratio, and analysis-source
enums, which are different concerns and should not be assumed to belong in a
semantic shot contract
([`models/enums.ts#L34-L44`](https://github.com/XucroYuri/take/blob/47c17216b5ad74ee7dd376e8508266e29aefae2c/packages/core/src/models/enums.ts#L34-L44)).

The upstream `Shot` combines creative semantics with generated prompts,
visual-reference tokens, lifecycle status, rendered assets, and notes
([`models/types.ts#L43-L84`](https://github.com/XucroYuri/take/blob/47c17216b5ad74ee7dd376e8508266e29aefae2c/packages/core/src/models/types.ts#L43-L84)).
Its project configuration names image/video providers and models
([`models/types.ts#L100-L130`](https://github.com/XucroYuri/take/blob/47c17216b5ad74ee7dd376e8508266e29aefae2c/packages/core/src/models/types.ts#L100-L130)).
Therefore only the film vocabulary and selected pure validation/serialization
behavior are plausible donor inputs; the whole upstream `Shot` or
`ProjectConfig` is not provider-neutral authority.

The upstream integrity checker adds three cross-record checks after schema
validation: unique shot IDs, contiguous 1-based order, and no dangling beat
reference when beats are present
([`validate.ts#L38-L67`](https://github.com/XucroYuri/take/blob/47c17216b5ad74ee7dd376e8508266e29aefae2c/packages/core/src/validate.ts#L38-L67)).
The grid builder deterministically expands a shot prompt into a 3×3 scaffold
across background/action/foreground and left/center/right
([`grid.ts#L24-L43`](https://github.com/XucroYuri/take/blob/47c17216b5ad74ee7dd376e8508266e29aefae2c/packages/core/src/grid.ts#L24-L43)).

The first-party core test file contains 12 `it()` cases. It covers basic schema
accept/reject behavior; all three integrity branches; two provider-config
cases; the 3×3 grid shape; and two Markdown round trips
([`core.test.ts`](https://github.com/XucroYuri/take/blob/47c17216b5ad74ee7dd376e8508266e29aefae2c/packages/core/test/core.test.ts)).
This is useful donor evidence, but it does not test an R2 port, R2 lineage,
approval, profile behavior, or concurrency.

### 2.2 Huohuo: a narrow `爽文` policy source, not shared adaptation truth

The inspected upstream is
[`appolloqin/huohuo-drama@f104b853b3563e124d9cde25f9331d323fb483b9`](https://github.com/appolloqin/huohuo-drama/commit/f104b853b3563e124d9cde25f9331d323fb483b9).
The exact module is
[`workbench-server/src/services/novel/novel-outline-drama-fields.ts`](https://github.com/appolloqin/huohuo-drama/blob/f104b853b3563e124d9cde25f9331d323fb483b9/workbench-server/src/services/novel/novel-outline-drama-fields.ts),
whose fetched bytes matched the local source manifest SHA-256
`7a7db8a7674445d8352beb7a165fb5fe40bf02c1d526a89c31a6c74fa9029c67`
(`docs/r2/evidence/reuse-map-2026-09-07/source-manifest.json:106-112`).

The module has two layers of fields:

- book-level theme, world rules, internal/external desire, protagonist flaw,
  cast cores, arc end, and emotion palette
  ([`#L13-L22`](https://github.com/appolloqin/huohuo-drama/blob/f104b853b3563e124d9cde25f9331d323fb483b9/workbench-server/src/services/novel/novel-outline-drama-fields.ts#L13-L22)); and
- chapter-level time, place, cast, catalyst, desire, obstacle, stakes shift,
  choice, three conflict layers, emotion craft, ending question, information
  delta, theme echo, and optional `恨/爽/急/盼`
  ([`#L24-L70`](https://github.com/appolloqin/huohuo-drama/blob/f104b853b3563e124d9cde25f9331d323fb483b9/workbench-server/src/services/novel/novel-outline-drama-fields.ts#L24-L70)).

Its parser selects the last repeated tag and stops at the next tag/chapter
boundary
([`extractTagBlock`](https://github.com/appolloqin/huohuo-drama/blob/f104b853b3563e124d9cde25f9331d323fb483b9/workbench-server/src/services/novel/novel-outline-drama-fields.ts#L105-L126)).
It parses a closed conflict vocabulary (`外部`, `人际`, `自我`) separately from
invalid values and then projects tagged text into book/chapter structures
([`#L140-L213`](https://github.com/appolloqin/huohuo-drama/blob/f104b853b3563e124d9cde25f9331d323fb483b9/workbench-server/src/services/novel/novel-outline-drama-fields.ts#L140-L213)).

The generic-looking fields do not make the complete module generic. For
chapters 1–8, validation additionally requires all four `恨/爽/急/盼` beats, a
valid closed `爽型`, and a stakes check
([`#L248-L340`](https://github.com/appolloqin/huohuo-drama/blob/f104b853b3563e124d9cde25f9331d323fb483b9/workbench-server/src/services/novel/novel-outline-drama-fields.ts#L248-L340)).
The imported `爽型` set contains six tactics (`硬撕`, `拒签`, `揭穿假账`,
`示弱钓鱼`, `当众对赌`, `借力第三方`)
([`novel-commercial-appeal-isomorph.ts#L6-L22`](https://github.com/appolloqin/huohuo-drama/blob/f104b853b3563e124d9cde25f9331d323fb483b9/workbench-server/src/services/novel/novel-commercial-appeal-isomorph.ts#L6-L22)).
The prompt builder requires the `恨→爽→急→盼` order
([`novel-outline-drama-fields.ts#L343-L372`](https://github.com/appolloqin/huohuo-drama/blob/f104b853b3563e124d9cde25f9331d323fb483b9/workbench-server/src/services/novel/novel-outline-drama-fields.ts#L343-L372)),
and the upstream SSOT gives detailed phase-specific craft rules
([`novel-emotion-core-contract.ts#L10-L58`](https://github.com/appolloqin/huohuo-drama/blob/f104b853b3563e124d9cde25f9331d323fb483b9/workbench-server/src/services/novel/novel-emotion-core-contract.ts#L10-L58)).
Those are evidence for a Chinese short-drama policy pack, not universal facts
about adaptation, Canon, or all drama.

There is no related conventional `*.test.*` or `*.spec.*` suite in the inspected
[pinned repository tree](https://github.com/appolloqin/huohuo-drama/tree/f104b853b3563e124d9cde25f9331d323fb483b9).
There is, however, a first-party executable smoke verifier,
[`scripts/verify-outline-drama-fields.ts`](https://github.com/appolloqin/huohuo-drama/blob/f104b853b3563e124d9cde25f9331d323fb483b9/workbench-server/scripts/verify-outline-drama-fields.ts).
It exercises valid/missing book and chapter fields, the four emotion beats,
invalid conflict layers, last-tag-wins parsing, prompt construction, preferred
chapter resolution, and legacy-outline upgrade. The production-side caller
attempts one completion pass and then raises a typed error if the fields are
still invalid
([`novel-outline-drama-ensure.ts#L205-L243`](https://github.com/appolloqin/huohuo-drama/blob/f104b853b3563e124d9cde25f9331d323fb483b9/workbench-server/src/services/novel/novel-outline-drama-ensure.ts#L205-L243));
its pre-write path can apply or bypass the gate and returns an explicit fallback
when disabled
([`#L245-L318`](https://github.com/appolloqin/huohuo-drama/blob/f104b853b3563e124d9cde25f9331d323fb483b9/workbench-server/src/services/novel/novel-outline-drama-ensure.ts#L245-L318)).

This evidence supports an exact-source parity harness and a larger R2-owned
corpus. It does not support treating the smoke verifier as comprehensive
regression coverage.

### 2.3 Generic Western drama: no justified closed beat taxonomy yet

The reviewed primary sources provide a provider-neutral film-shot vocabulary
(`take`) and a highly specific Chinese commercial-emotion policy (Huohuo). They
do not provide a first-party, closed, culturally neutral or “generic Western”
beat taxonomy equivalent to `恨/爽/急/盼`.

Therefore the safe research conclusion is limited: generic Western drama can
share the adaptation lineage, screenplay, Director, shot-language, continuity,
and candidate-selection kernel, but its profile rules still require a named,
versioned source/corpus before they can become hard policy. Inventing a closed
Western beat enum from general screenwriting lore would exceed the evidence in
this pass.

## 3. Current R2 constraints and reusable seams

### 3.1 Frozen authority and lineage boundary

R2 already freezes four adaptation contracts: `AdaptationBranch`,
`AdaptationBrief`, `AdaptationMap`, and `ScreenplayArtifact`
(`docs/r2/R2_03_FROZEN_DOMAIN_STATE_CONTRACTS.md:694-703`). An adaptation branch
pins a parent Canon version, medium, adaptation policy, and overlay version; it
must not overwrite source Canon
(`docs/r2/R2_03_FROZEN_DOMAIN_STATE_CONTRACTS.md:707-731`). The architecture also
requires the branch to keep an immutable parent reference, explicit divergence,
versioning, and auditability instead of copying all parent Canon by default
(`docs/r2/R2_01_FROZEN_ARCHITECTURE.md:375-412`).

`AdaptationMapEntry` already has source/target refs, nine transformation
operations, rationale, fidelity risk, and approval status
(`docs/r2/R2_03_FROZEN_DOMAIN_STATE_CONTRACTS.md:735-759`). The locked decision is
that medium adaptation uses this parent-linked branch/map rather than silently
mutating source Canon
(`docs/r2/R2_04_CONSOLIDATED_DECISION_LOG.md:177-192`). Profile policy therefore
cannot acquire Canon-write authority merely because it generated or validated a
map proposal.

`ScreenplayArtifact` is branch- and `ContentBasis`-linked, retains source mapping
refs, and enters direction only when approved and locked
(`docs/r2/R2_03_FROZEN_DOMAIN_STATE_CONTRACTS.md:776-794`). `ADAPTATION`
`ContentBasis` may reference the parent Canon version, adaptation branch/version,
and map refs
(`docs/r2/R2_03_FROZEN_DOMAIN_STATE_CONTRACTS.md:798-831`). The current contract
kernel implements `ContentBasis` as a typed basis/version plus a sorted,
deduplicated non-empty ref set (`r2/contracts/content_basis.py:7-15`) and already
has the `ADAPTATION` discriminator (`r2/contracts/enums.py:44-47`).

### 3.2 Narrative inputs already carry Golden B constraints

At implementation snapshot `feat/r2-m5b-epistemic-plan-context@a2dc1c14`,
`SceneContract` carries purpose, POV, location, temporal window, participants,
required/forbidden events, reveals, forbidden knowledge, entry/exit state,
threads, payoffs, and creative constraints
(`/home/anhtuan/content-production-os-m5b/r2/contracts/narrative_plan.py:163-188`).
`NarrativePlanContent` pins an exact Canon basis and owns the scene-contract list
(`/home/anhtuan/content-production-os-m5b/r2/contracts/narrative_plan.py:191-203`).
These are direct inputs for the shared continuity/secret/state acceptance matrix;
they should not be duplicated as profile-specific truth.

`NarrativePlanService` binds proposal, approval, scope, expected version, parent,
and content hash before writing; it locks a plan head, checks optimistic version,
validates against an exact Canon version, inserts the immutable version, advances
the head, flushes, and commits in one unit of work
(`/home/anhtuan/content-production-os-m5b/r2/narrative_plan/service.py:49-140`).
It also rejects a Canon reader that returns a different identity instead of the
exact requested basis
(`/home/anhtuan/content-production-os-m5b/r2/narrative_plan/service.py:212-234`).

### 3.3 Authority/concurrency pattern available for adaptation

At the same implementation lineage, `CanonTransactionService` is the sole Canon
commit orchestrator and owns one fresh authority unit of work
(`/home/anhtuan/content-production-os-m5b/r2/narrative/canon_transaction.py:1-6`).
Before awaited work it round-trips the caller-held delta to detach approval-bound
bytes, verifies the delta hash and approval, then locks the branch
(`/home/anhtuan/content-production-os-m5b/r2/narrative/canon_transaction.py:167-187`).
Inside the lock it distinguishes exact retry from identity conflict, prevents an
approval receipt authorizing another delta, checks expected base against the
current semantic head, resolves and validates a candidate, revalidates approval,
and commits atomically
(`/home/anhtuan/content-production-os-m5b/r2/narrative/canon_transaction.py:189-262`).
The append path stores the accepted delta and immutable version, advances the
head with the expected prior head, updates the disposable projection, and flushes
them in the same transaction
(`/home/anhtuan/content-production-os-m5b/r2/narrative/canon_transaction.py:308-380`).

This is reusable evidence for an adaptation transaction design, not proof that
copying the service mechanically is correct. In PostgreSQL, `READ COMMITTED`
gives each statement a new committed snapshot, while locking commands wait and
then evaluate the updated row; repeatable-read transactions retain the earlier
transaction snapshot and can fail if the row changed
([PostgreSQL transaction isolation](https://www.postgresql.org/docs/current/transaction-iso.html#XACT-READ-COMMITTED)).
`SELECT FOR UPDATE` blocks conflicting writers/lockers until transaction end
([PostgreSQL explicit locking](https://www.postgresql.org/docs/current/explicit-locking.html#LOCKING-ROWS)).
Any M6 retry-before-write or lock/OCC protocol must specify and test the isolation
assumption rather than inheriting it implicitly.

### 3.4 Director and ShotSpec seams

The frozen Director boundary assigns fiction, screenplay, drama, and
camera-heavy work to `TakeDirector`; every adapter normalizes to `SceneSpec` and
`ShotSpec`, and no Director owns provider/runtime jobs
(`docs/r2/R2_01_FROZEN_ARCHITECTURE.md:446-493`). The locked routing decision is
format-sensitive, not provider-sensitive
(`docs/r2/R2_04_CONSOLIDATED_DECISION_LOG.md:279-294`).

At implementation snapshot `a2dc1c14`, `DirectorAdapter` accepts one already
validated script-like artifact, and narrative content deterministically routes
to the `TAKE` kind
(`/home/anhtuan/content-production-os-m5b/r2/production_intelligence/director.py:45-50,74-127`).
`DirectorSuccess` is the shared normalized carrier of `SceneSpec[]` and
`ShotSpec[]`
(`/home/anhtuan/content-production-os-m5b/r2/contracts/director.py:35-43`). The
validator revalidates even adapter-built success, requires shots, and rejects a
shot whose scene is absent
(`/home/anhtuan/content-production-os-m5b/r2/production_intelligence/director.py:135-209`).
The execution service retries transient failures, fails closed on semantic or
partial/ambiguous output, and only auto-falls back to ArcReel Native
(`/home/anhtuan/content-production-os-m5b/r2/production_intelligence/director.py:238-329`).

There is currently a `TAKE` route and adapter protocol, but no concrete class
named `TakeDirector` in the inspected implementation scope. M6 must therefore
implement the adapter rather than assume a donor class already exists. This is a
bounded source/graph observation, not a repository-wide historical absence
claim (`/home/anhtuan/content-production-os-m5b/r2/production_intelligence/director.py:1-372`;
the project checkpoint also records M6 as not started at
`docs/r2/evidence/PROJECT_DECISIONS_2026-09-09.md:255-264`).

Current `ShotSpec` has stable identity/version, scene and `ContentBasis`, purpose,
positive duration, free-form `framing` and `camera`, entity/audio/continuity/
reference-role requirements, allowed methods, quality tier, and creative
approval (`r2/contracts/production.py:36-60`). The frozen contract forbids
provider, model, endpoint, API payload, job ID, and provider-specific schema
fields (`docs/r2/R2_03_FROZEN_DOMAIN_STATE_CONTRACTS.md:909-948`), reinforced by
locked `R2-DEC-023`
(`docs/r2/R2_04_CONSOLIDATED_DECISION_LOG.md:415-430`).

The already-approved M6 retrofit decision requires the `take` shot-size,
camera-angle, and movement vocabulary to enter the M4 TakeDirector contract and
requires rerunning the M4 gates because this changes verified code
(`docs/r2/evidence/PROJECT_DECISIONS_2026-09-09.md:196-203`). It does not yet say
whether `framing`/`camera` are replaced, supplemented, or version-migrated.

### 3.5 Production lineage and candidate selection

The content fingerprint currently hashes the complete semantic `ShotSpec`,
sorted bindings, visual identity refs, and approved source assets; provider,
model, endpoint, seed, resolution, generation settings, compiler version, and
adapter version live in a separate execution fingerprint
(`r2/contracts/fingerprints.py:27-72`). This provides the existing seam for both
profiles to share semantic production authority without sharing provider/runtime
configuration.

`GenerationCandidate` separates generation lifecycle from selection state and
forbids failed or non-generated candidates from being selected, while
`ApprovedMaster` records the explicit selected candidate and approval
(`r2/contracts/results.py:11-43`). Artifact metadata records exact contract,
`ContentBasis`, direct dependency snapshots, content fingerprint, and optional
approved-master metadata, rejecting conflicting duplicate dependency refs
(`r2/production/artifact_metadata.py:21-49`). These seams already support the M6
requirement for multiple candidates without making “latest generated” the
creative authority.

## 4. Design hypotheses and evaluation inputs, not decisions

### 4.1 Shared kernel versus profile policy

The evidence motivates testing the following separation; it does not select it:

| Shared authority/semantic kernel | Profile policy plane | Execution plane |
|---|---|---|
| Parent-pinned `AdaptationBranch`; approved/versioned `AdaptationMap`; locked `ScreenplayArtifact`; exact `ContentBasis`; `SceneSpec`/`ShotSpec`; candidate selection | Generic-Western policy pack and Huohuo-derived `zh-shuang` policy pack; analysis, generation guidance, policy diagnostics and repair suggestions | Prompt/provider/model/request/job state and rendered assets |

The committed authority objects may need exact immutable references/hashes to
the policy evidence that produced an approved semantic result. That is different
from embedding `恨/爽/急/盼`, `爽型`, provider prompts, or mutable policy state in
the shared authority schema. Whether policy identity is itself part of semantic
content or only provenance remains a design decision.

### 4.2 Three architecture approaches to compare

#### Option A — one shared aggregate, two policy-pack implementations

Both profiles propose the same `AdaptationBranch`/`AdaptationMap`/
`ScreenplayArtifact` contracts. A profile-selected policy runner emits
non-authoritative findings/proposals; the same `AdaptationTransactionService`
validates approval, locks one head, commits immutable versions, and advances it.

Potential properties to test:

- smallest authority surface and clearest provider/profile neutrality;
- one concurrency, retry, integrity, and rebuild model;
- easiest shared Golden B invariants.

Risks/questions:

- a very generic proposal envelope can become an untyped JSON escape hatch;
- policy-specific evidence must remain inspectable without polluting authority;
- generic-Western hard gates are not yet source-grounded.

#### Option B — shared authority plus typed, non-authoritative profile sidecars

Keep the authority aggregate from Option A, but define immutable analysis
artifacts outside the authority writer: for example, a generic-drama analysis
sidecar and a Huohuo-derived short-drama analysis sidecar. A common compiler maps
either sidecar into the same adaptation proposal/map vocabulary. Approval binds
the resulting shared semantic bytes and, if selected, an exact sidecar evidence
reference.

Potential properties to test:

- profile-specific fields stay typed and reviewable;
- Huohuo parity can be tested without forcing Chinese labels into shared R2
  contracts;
- new profiles can be added without changing adaptation authority.

Risks/questions:

- an additional artifact lifecycle and stale-evidence rule are required;
- the compiler must prevent sidecar fields from bypassing map rationale/fidelity
  review;
- the boundary between diagnostic evidence and approval-bound semantic input
  must be explicit.

#### Option C — sibling profile branches over one pinned Canon version

Use the same authority service/contracts, but materialize generic-Western and
`zh-shuang` results as sibling `AdaptationBranch` lineages pinned to the same
Canon version. Each branch can have its own map and screenplay candidates;
shared TakeDirector and production contracts begin after screenplay approval.

Potential properties to test:

- strongest audit comparison between two adaptations of one source;
- no accidental “Western then Chinese” or “Chinese then Western” lineage;
- profile experiments cannot move each other's branch head.

Risks/questions:

- more branch/head lifecycle and cross-branch comparison UX;
- Golden B must decide whether both sibling slices are release gates;
- shared improvements may require deliberate replay/rebase semantics rather
  than silent propagation.

Options A/B concern the policy-to-authority seam; Option C concerns lineage
topology and can be combined with either. None is selected here.

### 4.3 Donor-port verification implications

For `take`, R2 can port the exact closed enums and selected pure integrity/grid/
Markdown behavior while rejecting upstream provider/status/assets fields. The
existing 12 cases are a baseline, not the full R2 gate. R2 still needs contract
neutrality, schema migration/backward compatibility, M4 regression, exact-source
parity, and Director semantic-failure tests. The existing project decision
already requires the retrofit and M4 gate rerun
(`docs/r2/evidence/PROJECT_DECISIONS_2026-09-09.md:196-203`).

For Huohuo, the existing project estimate is approximately 30–45 cases because
the prior inventory did not treat the executable smoke script as a conventional
suite (`docs/research/2026-09-09-r2-donor-reuse-maximization.md:264-268`). Primary
source inspection refines, but does not invalidate, that risk: the verifier
provides useful fixtures/assertions, yet there is no evidence here of CI coverage
or comprehensive branch/error testing. A parity gate should run the unmodified
pinned TypeScript source and the Python port on the same corpus, compare
outputs/errors/determinism, and keep that harness test-only. The Huohuo
completion/LLM service is a caller pattern, not authority or a port target.

The generic-Western profile needs its own named corpus and expected policy
behavior. It should share all authority, lineage, concurrency, Director, shot,
continuity, and selection tests with `zh-shuang`; only policy-specific fixtures
and assertions should diverge.

## 5. Unknowns and remaining Human decisions

1. **Golden B topology:** one artifact that demonstrates both policies, or two
   separately reviewable sibling Golden B slices under one M6 release gate?
2. **Profile selection authority:** is the selected profile/policy version part
   of approval-bound semantic content, immutable provenance/dependency evidence,
   or only a non-authoritative run parameter?
3. **Generic-Western policy source:** which named first-party guide/corpus and
   version defines hard versus advisory craft checks? No closed taxonomy was
   established in this pass.
4. **Huohuo port surface:** only pure field parsing/validation/prompt-block
   helpers, or also the upstream completion/repair orchestration? The latter adds
   LLM/runtime coupling and is not required to reuse the policy vocabulary.
5. **ShotSpec migration:** replace free-form `framing`/`camera`, add typed
   `shot_size`/`camera_angle`/`camera_movement` beside them, or introduce a new
   ShotSpec schema version with an explicit compatibility translator?
6. **Adaptation operation vocabulary:** are the nine frozen operations sufficient
   for cultural/localization choices, or must a new explicit operation be
   approved instead of overloading `MODIFY_FOR_MEDIUM`?
7. **Branch topology:** sibling branches per profile, a single branch containing
   multiple screenplay candidates, or both at different lifecycle stages?
8. **Approval granularity:** entry-level map approval, whole-map approval,
   screenplay lock, and branch-head advancement must be related explicitly.
9. **Policy failure semantics:** which findings block proposal, which require
   Human waiver, and which remain advisory for each profile?
10. **Dual-profile fixtures:** adapt one shared Canon source into both profiles
    for direct comparison, use two culturally native sources, or require both?
11. **Isolation and retry protocol:** exact PostgreSQL isolation level, lock
    order, uniqueness constraints, retry identity, and failure/rollback evidence
    for the new adaptation authority.

## 6. Evidence and coverage limitations

- Codebase Memory was used at Tier 2. Initial structural discovery used root
  generation `2026-09-09T10:12:51Z`, which predates several M4/M5 implementation
  files. The final coverage recheck auto-refreshed the root graph to generation
  `2026-09-12T07:10:39Z`; it reported no recorded gap for the cited frozen docs,
  M1/M2 contract files, source manifest, and prior donor inventory. The new note
  itself was reported as metadata-changed, so its source was read directly.
  Every graph coverage result remains best-effort, not completeness proof.
- The current M5C graph supplied for this research was generated
  `2026-09-11T11:57:25Z` and reported no recorded issue for the eight relevant
  M4/M5 paths. Direct source fallback used the clean M5B implementation snapshot
  `a2dc1c141c77ce1365eea8360a3593b55567c5af` for exact line evidence. No M5B/M5C
  file was modified.
- The inspected root has no implemented `r2/adaptation` package in the bounded
  source/tree scope; this agrees with the recorded checkpoint that M6 had not
  started (`docs/r2/evidence/PROJECT_DECISIONS_2026-09-09.md:255-264`). The
  frozen contracts are therefore design authority, not a claim that an
  adaptation transaction implementation already exists. A clean empty graph
  scope is not proof of global/historical absence.
- `take` was inspected at one pinned commit, not audited across repository
  history. Checksums were computed for the relevant local source files; its core
  tests were read but not rerun in this pass.
- Huohuo source, direct dependencies/caller, recursive tree, and executable
  verifier were inspected at one pinned commit. The verifier was not executed,
  and no evidence was found that it runs in CI. Absence claims are limited to
  conventional related test paths in that pinned tree.
- No primary source reviewed here defines a normative generic-Western beat
  taxonomy. That is deliberately left unknown instead of filled with secondary
  screenwriting advice.
- No donor service, package installation, migration, production discovery,
  worker, or generation run was performed. Only this research file was added.

## 7. Research round 2 — policy, topology, and validation precedents

This round narrows the remaining evidence gaps. All proposed structures below
are hypotheses for comparison. Nothing in this section recommends a topology,
policy vocabulary, severity model, or approval mechanism.

### 7.1 Primary-source matrix

| Source and inspected revision | What the source actually establishes | What it does not establish for M6 |
|---|---|---|
| BBC, *Screenplay Format for TV Shows*, official PDF, PDF metadata dated 2004-02-09, inspected bytes SHA-256 `54a6a95383fdc7198209e241e1ad7fdbfc977de4c52fb4090b59396e60e4deff` ([official PDF](https://downloads.bbc.co.uk/writersroom/scripts/screenplaytv.pdf)) | A lintable screenplay surface: scene headings identify interior/exterior, place and day/night; action follows a heading; character cues introduce dialogue; action describes what can be seen or heard. | A universal beat model. Its teaser/act, spacing, transition, continuation and paragraph guidance is a house-format convention, not culture-neutral dramatic authority. |
| Screen Australia, *Story Documents — Drama*, cover revision July 2018, inspected PDF bytes SHA-256 `e7c46003f2daf03408f0d231f2e6c907b0ed6a02a3bc7a61d1fb4346952d7f47` ([official resource](https://www.screenaustralia.gov.au/resource/story-documents-drama-2/)) | A named, versionable review rubric across feature, short, episodic, online and interactive work: dramatic problem, inciting incident, character goal/action, opposition, stakes, cause/effect, ending/resolution, and outline turning points such as escalation, revelation and reversal. The guide itself says there is no one-size-fits-all approach. | A closed schema in which every work must contain every concept at a fixed timestamp. Theme, engagement, emotional resonance, voice and hook remain evaluative craft judgments. |
| BBC Bitesize commissioning brief, published 2021-07-30, inspected PDF bytes SHA-256 `ae99bd829d4b2adfae34c575fe543818fb082ee490a77babbf7a594c4d031623` ([official brief](https://downloads.bbc.co.uk/aboutthebbc/northernireland/commissioning/bitesize-brief-ccea-ks3-english-media-july-2021.pdf)) | A first-party commissioning precedent for videos likely to run one to two minutes, plus inspectable proposal artifacts and technical delivery constraints. | A drama standard: it is an educational commission, permits duration flexibility, and cannot justify a universal 60–120 second dramatic form. |
| Academy of Motion Picture Arts and Sciences, current *Screenwriting Resources* ([official page](https://www.oscars.org/nicholl/screenwriting-resources)) | The Academy states that American professional screenwriters do not all use one absolute standard, calls listed format faults subjective, and distinguishes submission scripts from camera/scene-number-heavy shooting scripts. | A closed Western format or beat taxonomy. This is direct boundary evidence against promoting typography or camera-cue preferences into universal hard failures. |
| AcademySoftwareFoundation/OpenTimelineIO at [`31e3101e750be2aa992274ac02c0679077872e57`](https://github.com/AcademySoftwareFoundation/OpenTimelineIO/commit/31e3101e750be2aa992274ac02c0679077872e57) | Compositions can contain tracks, clips, gaps, transitions and nested compositions ([timeline model](https://github.com/AcademySoftwareFoundation/OpenTimelineIO/blob/31e3101e750be2aa992274ac02c0679077872e57/docs/tutorials/otio-timeline-structure.md#L3-L21)). Every serializable object carries a schema name/version; reads upgrade older schemas, writes can target older schemas through explicit downgrade functions and manifests ([schema versioning](https://github.com/AcademySoftwareFoundation/OpenTimelineIO/blob/31e3101e750be2aa992274ac02c0679077872e57/docs/tutorials/versioning-schemas.md#L5-L20)). | Creative branch authority, profile selection, approval custody or OCC. OTIO explicitly permits some structurally representable ranges without verifying/snapping them, leaving downstream applications responsible ([timeline limitations](https://github.com/AcademySoftwareFoundation/OpenTimelineIO/blob/31e3101e750be2aa992274ac02c0679077872e57/docs/tutorials/otio-timeline-structure.md#L77-L81)). |
| PixarAnimationStudios/OpenUSD at [`0ace5b88702edbfe00dd031369f38ff526cb07b8`](https://github.com/PixarAnimationStudios/OpenUSD/commit/0ace5b88702edbfe00dd031369f38ff526cb07b8) | Variant sets and values are authored explicitly; edits must enter a variant edit context, while a local opinion can be stronger than and mask a selected variant ([variant authoring](https://github.com/PixarAnimationStudios/OpenUSD/blob/0ace5b88702edbfe00dd031369f38ff526cb07b8/docs/tut_authoring_variants.rst#L9-L23), [edit context](https://github.com/PixarAnimationStudios/OpenUSD/blob/0ace5b88702edbfe00dd031369f38ff526cb07b8/docs/tut_authoring_variants.rst#L145-L162)). Referenced layers support non-destructive opinions and per-instance overrides ([layer references](https://github.com/PixarAnimationStudios/OpenUSD/blob/0ace5b88702edbfe00dd031369f38ff526cb07b8/docs/tut_referencing_layers.rst#L79-L128)). | R2 semantic approval or concurrency safety. Opinion-strength composition is a useful masking/staleness counterexample, not evidence that an adaptation profile should be an overlay. |
| Stoplight Spectral at [`ea1ce67d1ba736e07b6c09c355a052a4912e2e0e`](https://github.com/stoplightio/spectral/commit/ea1ce67d1ba736e07b6c09c355a052a4912e2e0e) | Rules distinguish `validation` from `style`; severity can be `error`, `warn`, `info`, `hint`, or `off`, and rulesets support format applicability, extension and overrides ([rule types](https://github.com/stoplightio/spectral/blob/ea1ce67d1ba736e07b6c09c355a052a4912e2e0e/packages/core/src/ruleset/types.ts#L6-L35), [ruleset structure](https://github.com/stoplightio/spectral/blob/ea1ce67d1ba736e07b6c09c355a052a4912e2e0e/docs/guides/4-custom-rulesets.md#L9-L18)). Parser diagnostics such as duplicate or incompatible values have configurable severity ([parser options](https://github.com/stoplightio/spectral/blob/ea1ce67d1ba736e07b6c09c355a052a4912e2e0e/docs/guides/4-custom-rulesets.md#L125-L138)). | Human approval, waiver custody, immutable lineage or retry/OCC semantics. `off` is especially not evidence that an authority invariant may be silently disabled. |
| Kubernetes at [`995680c51b5bedce2c4ee2f5bc7f0721fef0dc04`](https://github.com/kubernetes/kubernetes/commit/995680c51b5bedce2c4ee2f5bc7f0721fef0dc04) | Validating policy actions distinguish `Deny`, HTTP-warning `Warn`, and structured `Audit`; invalid action combinations are rejected ([typed contract](https://github.com/kubernetes/kubernetes/blob/995680c51b5bedce2c4ee2f5bc7f0721fef0dc04/pkg/apis/admissionregistration/types.go#L471-L510), [action enum](https://github.com/kubernetes/kubernetes/blob/995680c51b5bedce2c4ee2f5bc7f0721fef0dc04/pkg/apis/admissionregistration/types.go#L662-L676)). A first-party integration test exercises allowed-with-warning versus denied-with-audit behavior ([integration test](https://github.com/kubernetes/kubernetes/blob/995680c51b5bedce2c4ee2f5bc7f0721fef0dc04/test/integration/apiserver/cel/validatingadmissionpolicy_test.go#L402-L433)). | Per-artifact Human waiver identity, rationale, expiry or creative approval lineage. Administrator-selected enforcement actions are not an R2 approval protocol. |

The two OTIO links above use the historical `AcademySoftwareFoundation`
organization in the commit URL but the current project documentation resolves
under that same first-party repository. If GitHub later redirects the repository,
the full commit SHA and path remain the evidence identity used in this note.

### 7.2 Generic Western drama: bounded conclusion and Golden B evidence

The BBC formatting guide supports mechanically testable screenplay grammar,
not story quality. Screen Australia supports a versioned semantic review rubric,
but explicitly rejects a one-size-fits-all story-document approach. The BBC
commissioning brief shows that a named commissioner can define a 60–120 second
target and concrete acceptance artifacts, but its educational context prevents
generalization to drama.

Within the four first-party publications inspected in this round, and the `take` and
Huohuo sources inspected in round 1, no source justifies a universal, closed
Western beat taxonomy or fixed beat timing. This is a bounded negative result,
not a claim that no such model exists anywhere. A defensible versioned
generic-Western corpus could still test:

1. shared R2 integrity: exact Canon/branch/map lineage, approval, continuity,
   knowledge/state, shot identity/order and candidate selection;
2. screenplay surface integrity from a named formatting edition;
3. presence and traceability of rubric evidence such as problem, action/goal,
   opposition, stakes, cause/effect and resolution, without requiring every
   advisory concept in every 60–120 second excerpt; and
4. Human-scored craft criteria whose guide/version, assessor, score and waiver
   are recorded rather than converted into invented hard enums.

The local Golden B duration, cast, shot-count and continuity requirements remain
the actual release boundary
(`docs/r2/R2_06_FROZEN_IMPLEMENTATION_ROADMAP.md:185-213`). The external BBC
brief is only a runtime/commissioning analogue; it does not amend that authority.

### 7.3 Three profile/lineage topology hypotheses

Evaluation criteria for all three hypotheses are: unambiguous identity; exact
replay; concurrent head safety/OCC; shared-work reuse; isolated cross-profile
experimentation; explicit migration; deterministic testability; waiver
visibility; and containment of profile policy outside Canon authority.

| Hypothesis | Identity and replay | OCC and experiments | Reuse and migration | Precedent-supported failure mode / analogy limit |
|---|---|---|---|---|
| **H1: profile and policy version immutable per adaptation branch** | Branch identity can bind parent Canon plus one exact profile/policy version; replay is direct if every dependency is immutable. | Sibling profile heads isolate experiments; independent head locks reduce cross-profile contention. | Shared Canon is reused, but maps/screenplays may duplicate; a policy upgrade or mistaken profile selection requires a new branch or explicit lineage operation. | The frozen local branch already pins parent, medium, policy and overlay (`docs/r2/R2_03_FROZEN_DOMAIN_STATE_CONTRACTS.md:707-731`), but that design text does not prove profile cardinality. OTIO schema manifests show explicit versions/migration, not branch-per-policy authority. |
| **H2: profile/policy version changes as immutable versions within one branch** | Stable branch identity requires each map/screenplay version to bind the exact policy version; replay fails if policy is resolved as “latest.” | One branch head makes profile experiments contend or serialize; OCC can prevent lost updates but not semantic mixing unless parent/profile expectations are checked together. | Reuse within one history is high and migration can append versions; rollback and comparison require explicit prior-version selection. | OTIO upgrade/downgrade chains support explicit schema evolution, but OTIO normally materializes the current in-memory schema and has no creative approval/OCC, so it does not prove this topology. |
| **H3: profile overlay versioned independently of a profile-neutral branch** | Effective identity becomes a composite of branch/map version, overlay identity/version and deterministic composition order. Omitting any component makes replay ambiguous. | Separate branch and overlay heads permit parallel experiments but create compatibility races; independent OCC can accept two individually current values whose pair was never reviewed. | Maximum base reuse and cheap cross-profile overlays; migration can update an overlay without copying the branch, but existing approvals can become stale. | OpenUSD directly demonstrates non-destructive variants/overrides and the danger that stronger local opinions mask selected variants. USD has no R2 approval custody or semantic-head invariant, so it exposes an overlay failure mode rather than validating H3. |

No precedent selects among H1–H3. In particular, the round-1 Option C should be
read only as an H1-shaped experiment, not as a conclusion that every
`AdaptationBranch` must have one immutable profile. Options A/B address the
policy-to-authority seam and can be evaluated independently of H1–H3.

### 7.4 Candidate validation semantics, not a severity decision

Spectral demonstrates that an executable policy system can separate structural
validation from style and can assign several severities per rule. Huohuo shows a
different pattern: for chapters 1–8 its field validator returns errors for
missing required emotion fields or an invalid `爽型`, and its caller attempts one
repair before raising a typed error
([Huohuo validator](https://github.com/appolloqin/huohuo-drama/blob/f104b853b3563e124d9cde25f9331d323fb483b9/workbench-server/src/services/novel/novel-outline-drama-fields.ts#L248-L340),
[caller](https://github.com/appolloqin/huohuo-drama/blob/f104b853b3563e124d9cde25f9331d323fb483b9/workbench-server/src/services/novel/novel-outline-drama-ensure.ts#L205-L243)).
Neither source defines R2 Human waivers.

A candidate M6 evaluation model should therefore be tested against, without yet
adopting, these distinguishable classes:

| Candidate class | Test question | Adversarial case |
|---|---|---|
| Schema/integrity failure | Would accepting the object make identity, lineage, references, enum values, order, or replay invalid? | A “warning” for a dangling map source ref permits an unrebuildable approved screenplay. |
| Profile policy failure | Does a named/versioned policy explicitly require the property for this artifact scope? | A Huohuo chapter-1 rule is applied to chapter 9+, or a Western rubric is treated as mandatory despite its own conditional language. |
| Quality warning | Is the finding evidence-dependent and useful, but not mechanically dispositive? | A valid slow-burn scene is rejected solely because a heuristic cannot find an early reversal. |
| Human-overridable advisory | Can a named authority accept the risk while preserving the finding, rationale and exact policy version? | “Disable rule” removes all trace of a continuity warning, so a later replay appears clean. |

Evaluation criteria include deterministic rule identity/version; explicit
artifact scope; stable diagnostic codes and locations; hard separation between
authority invariants and craft heuristics; non-silent waiver identity/rationale;
unchanged replay results; cross-profile isolation; and parity between donor
fixtures and the R2 implementation. Spectral's `off` setting is a counterexample
for audit-sensitive findings unless the disabled rule remains visible as
versioned policy/waiver evidence.

### 7.5 Re-check of `恨爽急盼`, six `爽型`, and a 60–120 second slice

The pinned Huohuo condition is exact but narrower than “all short drama”:
chapters 1–8 require all four `恨/爽/急/盼` fields plus a recognized `爽型`;
the validator does not impose that same emotion-field requirement on chapter 9+
([validator condition](https://github.com/appolloqin/huohuo-drama/blob/f104b853b3563e124d9cde25f9331d323fb483b9/workbench-server/src/services/novel/novel-outline-drama-fields.ts#L248-L340)).
The six values are the exact closed set in the imported commercial-appeal module
([six values](https://github.com/appolloqin/huohuo-drama/blob/f104b853b3563e124d9cde25f9331d323fb483b9/workbench-server/src/services/novel/novel-commercial-appeal-isomorph.ts#L6-L22)).

No inspected Huohuo file maps a chapter to seconds, shots, scenes, or the local
Golden B duration. Consequently, source parity can require these fields for the
same chapter scopes, but it cannot by itself prove that every 60–120 second
screenplay slice must visibly complete all four beats or select exactly one
`爽型`. That mapping remains an empirical corpus question.

Adversarial fixtures needed to test the mapping hypothesis include: a slice that
begins after `恨` was established; a four-beat arc split across two short
episodes; a chapter-9+ excerpt; a scene with two plausible `爽型`; tags in the
right order but semantically empty content; translated dialogue with no Chinese
keywords; and a legitimate Western slow-burn or tragic scene without a public
power reversal. These are constructed counterexamples, not claims about the
upstream corpus.

### 7.6 Round-2 corrections and still-unproven hypotheses

Corrections/refinements to round 1:

- “generic Western policy needs a source” is now narrower: named first-party
  formatting and review sources exist, but none inspected supports a universal
  closed beat enum;
- sibling profile branches are one testable topology, not an inferred invariant;
- Huohuo hard validation is specifically scoped to chapters 1–8 and has no
  source-grounded time-slice mapping; and
- a severity mechanism alone is not a waiver/approval protocol.

Still unproven:

1. whether policy identity belongs in semantic content, immutable provenance,
   or both;
2. whether the profile is immutable per branch, versioned within it, or an
   independently versioned overlay;
3. whether one shared source should produce both Golden B profiles or whether
   culturally native fixtures are also required;
4. whether Screen Australia's rubric concepts can be scored consistently enough
   for automated warnings on 60–120 second excerpts;
5. whether Huohuo chapter semantics align with R2 screenplay scene/episode
   boundaries; and
6. which findings may be waived, by whom, for how long, and what subsequent
   artifact changes invalidate a waiver.

### 7.7 Round-2 coverage limits

- The generic-Western review was bounded to four first-party publications:
  one BBC screenplay-format guide, one Screen Australia story-document guide,
  one Academy resource page, and one BBC commissioning brief. The three PDF
  byte streams were hashed, but their publishers do not expose source-control
  commit histories for those publications.
- The BBC Bitesize brief is a runtime/artifact precedent only, not drama-policy
  evidence. No commissioned output corpus was audited.
- OTIO, OpenUSD and Spectral were inspected at the exact commits linked above,
  focusing on their first-party documentation and directly related source
  types. Their test suites were not executed, and repository histories were not
  exhaustively audited.
- The OTIO/OpenUSD analogies stop at schema evolution, composition, variants and
  overrides. Neither project supplies R2 branch approval, Canon authority,
  retry identity, PostgreSQL locking or Human-waiver semantics.
- Huohuo's pinned validator, imported type set, prompt contract, direct caller
  and verifier were inspected. No duration mapping or chapter-to-scene mapping
  was found in that bounded related scope; this is not a repository-wide claim.
- No human-scored Western corpus, bilingual short-drama corpus, inter-rater
  reliability study, or 60–120 second dual-profile experiment was run. Those
  remain evidence gaps rather than assumptions.

## 8. Research round 3 — bounded decision support

This final research pass turns the preceding evidence into bounded defaults for
the parent ADR/spec/plan. These are recommendations from the inspected evidence,
not architecture approval. A later ADR may reject any default by documenting new
evidence and the affected frozen decision's reopen conditions.

### 8.1 Exact frozen surface and forward-versioning boundary

The frozen adaptation surface is narrower than a full implementation design:

- `AdaptationBranch` has branch identity/version, immutable parent branch and
  Canon version, medium, `STRICT | FAITHFUL | FREE | INSPIRED_BY` adaptation
  policy, overlay version, and creator/time. It does not overwrite source Canon
  (`docs/r2/R2_03_FROZEN_DOMAIN_STATE_CONTRACTS.md:707-731`). The architecture
  classifies it as medium transformation, not alternate-continuity truth, and
  requires explicit, versioned, auditable divergence
  (`docs/r2/R2_01_FROZEN_ARCHITECTURE.md:392-412`).
- `AdaptationMapEntry` freezes source/target refs, one of nine operations,
  rationale, fidelity risk, and entry approval. `AdaptationMap` freezes its own
  identity/version, branch ref, and entries, but no aggregate approval field
  (`docs/r2/R2_03_FROZEN_DOMAIN_STATE_CONTRACTS.md:735-772`).
- The complete operation vocabulary is `PRESERVE`, `EXTERNALIZE`, `CONDENSE`,
  `COMBINE`, `SPLIT`, `OMIT`, `REORDER`, `REFRAME_POV`, and
  `MODIFY_FOR_MEDIUM` (`docs/r2/R2_01_FROZEN_ARCHITECTURE.md:416-442`).
- `ScreenplayArtifact` freezes branch and `ContentBasis` links, scenes,
  characters, source-map refs, approval status, and direction lock; only an
  approved and locked screenplay may enter Director
  (`docs/r2/R2_03_FROZEN_DOMAIN_STATE_CONTRACTS.md:776-794`).
- `AdaptationBrief` is named as a primary contract but has no frozen field block,
  authority, approval semantics, or position in the M6 flow in the four frozen
  documents inspected (`docs/r2/R2_03_FROZEN_DOMAIN_STATE_CONTRACTS.md:694-703`;
  `docs/r2/R2_06_FROZEN_IMPLEMENTATION_ROADMAP.md:190-203`). Its shape cannot be
  inferred from the other three contracts.

Logical identity and monotonic object version are separate from schema version
(`docs/r2/R2_03_FROZEN_DOMAIN_STATE_CONTRACTS.md:53-87`). Compatible additive
fields are permitted, while removal/rename requires a schema-version migration;
new cross-authority refs require owner/permission review and a new authoritative
contract needs exactly one commit authority
(`docs/r2/R2_03_FROZEN_DOMAIN_STATE_CONTRACTS.md:1507-1515`). SQL/ORM layout is
not frozen (`docs/r2/R2_03_FROZEN_DOMAIN_STATE_CONTRACTS.md:14-47`). Thus a
versioned policy-evidence reference or ShotSpec schema successor is possible,
but silent reinterpretation of existing fields is not.

The `LOCKED` lineage rule is parent-linked AdaptationBranch plus AdaptationMap,
never source-Canon mutation
(`docs/r2/R2_04_CONSOLIDATED_DECISION_LOG.md:177-192`). The Director route and
provider-neutral `SceneSpec`/`ShotSpec` are also locked
(`docs/r2/R2_04_CONSOLIDATED_DECISION_LOG.md:279-294,415-430`). By contrast,
previous-frame chaining remains `ACTIVE` and conditional, so Golden B must not
turn it into a universal continuity rule
(`docs/r2/R2_04_CONSOLIDATED_DECISION_LOG.md:330-345`).

### 8.2 Current implementation evidence at M5C HEAD

The inspected worktree HEAD was
`2dbfad701dc11dd3127e8fefd4e6830de3c73b09`. It was read only.

`ContractIdentity` already separates free-form `schema_version` from monotonic
`version` (`/home/anhtuan/content-production-os-m5c/r2/contracts/common.py:23-26`).
Current `ShotSpec` still has free-form `framing` and `camera` and no movement
field (`/home/anhtuan/content-production-os-m5c/r2/contracts/production.py:36-60`).
The content fingerprint hashes the complete serialized ShotSpec plus normalized
bindings, visual-identity refs and approved source assets, while provider/model/
endpoint/settings/compiler/adapter belong to a separate execution fingerprint
(`/home/anhtuan/content-production-os-m5c/r2/contracts/fingerprints.py:27-73`).
Tests prove ordering stability, provider separation, and that shot/basis/binding
semantic changes move the content fingerprint
(`/home/anhtuan/content-production-os-m5c/tests/unit/r2/contracts/test_fingerprints.py:71-150`).

NarrativePlan commit checks proposal and approval hashes/scopes before locking,
then locks the plan, checks the expected version, resolves the exact Canon basis,
validates, appends an immutable version and advances the head in one transaction
(`/home/anhtuan/content-production-os-m5c/r2/narrative_plan/service.py:62-153`).
Exact retry compares approval, content hash, plan identity, parent and tenant
scope (`/home/anhtuan/content-production-os-m5c/r2/narrative_plan/service.py:193-225`).

The newer narrative authority kernel states `READ COMMITTED` as a correctness
precondition, performs retry lookup before any head write, optionally prepares
genesis, locks/inserts the typed head, repeats retry lookup, checks both latest
and effective predecessors, verifies applicability, writes identity/decision,
advances the head and commits once
(`/home/anhtuan/content-production-os-m5c/r2/narrative_lifecycle/authority_kernel.py:1-19,154-256`).
It defines a canonical multi-head order and authenticates exact retries against
the stored original authorization
(`/home/anhtuan/content-production-os-m5c/r2/narrative_lifecycle/authority_kernel.py:66-103,258-307`).
PostgreSQL integration tests race two independent genesis writers, expecting one
receipt and one predecessor conflict, and prove failure before commit leaves no
partial authority writes
(`/home/anhtuan/content-production-os-m5c/tests/integration/r2/narrative_lifecycle/test_lifecycle_concurrency.py:127-176,276-290`).

Acceptance currentness is deliberately separate from historical retry outcome:
an exact retry returns its original receipt after the head moved, while
`verify_exact_current_selection` reports only the current effective choice
(`/home/anhtuan/content-production-os-m5c/tests/integration/r2/narrative_lifecycle/test_acceptance_decisions.py:223-281`).
Conflict genesis locks revision then canonically sorted review heads and rejects
competitors that are no longer effective
(`/home/anhtuan/content-production-os-m5c/r2/narrative_lifecycle/acceptance.py:73-179`).

Director policy already binds a routing-policy version and input-profile ref,
records an explicit Human override/reason, and routes non-factual content to
TAKE (`/home/anhtuan/content-production-os-m5c/r2/production_intelligence/director.py:74-127`).
Every result is normalized and semantically revalidated; empty shots and orphan
scene refs fail closed, as do contract/semantic or partial/ambiguous failures
(`/home/anhtuan/content-production-os-m5c/r2/production_intelligence/director.py:135-225,238-329`).
The unit tests also prohibit automatic cross-route fallback between TAKE and
OpenMontage
(`/home/anhtuan/content-production-os-m5c/tests/unit/r2/production_intelligence/test_director.py:205-248`).

Admission denies stale readiness, missing approval, policy failure, unavailable
capability or failed synchronous dynamic revalidation before budget reservation
(`/home/anhtuan/content-production-os-m5c/r2/production_intelligence/admission.py:90-194`;
`/home/anhtuan/content-production-os-m5c/tests/unit/r2/production_intelligence/test_admission.py:126-179,204-260`).
Promotion refuses failed/rejected, foreign-target, or stale-content candidates
(`/home/anhtuan/content-production-os-m5c/r2/production/approval_service.py:26-77`).
A later failed or merely generated candidate cannot replace the explicit master
(`/home/anhtuan/content-production-os-m5c/tests/integration/r2/m4/test_approved_master_semantics.py:85-115`).

### 8.3 Decision matrix and bounded recommended defaults

| Decision | Evidence for / evidence against | Failure window | Migration cost and required tests | Bounded recommended default |
|---|---|---|---|---|
| **Profile-policy identity binding** | Director already records policy version + profile ref, while semantic fingerprints cover full semantic inputs. Against treating policy as runtime-only: an exact retry under a changed pack would otherwise be ambiguous. | Policy evaluated at v1; approval/commit resolves mutable “latest” v2. | Low–medium: add immutable `profile_id`, policy version and digest/ref to proposal/evidence identity; hash/retry/currentness mutations. | Bind exact profile + policy-pack version + digest into the approval-bound proposal identity and dependency provenance; keep rule bodies outside shared authority. |
| **H1/H2/H3 topology** | Frozen lineage requires versioned branch/overlay but does not fix profile cardinality. H1 isolates experiments; H2 raises one-head mixing; H3 inherits overlay masking/compatibility races from §7.3. | Two profiles race or a stronger overlay silently changes an approved effective view. | H1 medium duplication but simplest OCC/replay tests; H2/H3 require composite-currentness and migration matrices. | Use **H1 for M6 v1**: sibling profile-specific adaptation branches pinned to one Canon version. Any profile change creates a new explicit lineage/version, not an in-place reinterpretation. |
| **Option A/B policy seam** | Huohuo has typed fields/parity needs; Western rules are partly advisory. A single generic envelope risks untyped escape hatches; B adds artifact lifecycle. | Profile-only fields leak into Canon/shared contracts, or stale sidecar evidence authorizes new semantics. | B medium: immutable sidecar schema, hash, compiler, stale-evidence and cross-profile tests. | Use **Option B**: typed, immutable, non-authoritative profile-analysis sidecars compiled into one shared adaptation proposal; authority binds exact sidecar digest when relied upon. |
| **Golden B fixture topology** | M6 exit is one release gate but Human selected both profiles; sibling branches provide direct controlled comparison. One combined artifact cannot show isolation. | One profile passes using the other's diagnostics or only one profile is actually exercised. | Medium: one shared Canon fixture, two branches/screenplays, shared invariant oracle plus two policy oracles. | Require two separately reviewable 60–120s slices from one pinned Canon source under one Golden B gate; both pass shared invariants, each passes its applicable policy criteria. |
| **Huohuo port surface** | Pure parser/validator/types have pinned source and smoke verifier. Completion/repair caller couples LLM/runtime and owns no R2 authority. | Donor repair mutates/commits output or changes behavior without an R2 approval. | Low–medium for pure port + parity corpus; high for orchestration. | Port only pure field parsing, validation, six-type vocabulary and deterministic prompt-block helpers. Keep completion/repair orchestration out of v1. |
| **ShotSpec migration** | Retrofit is already approved, but frozen `framing`/`camera` and current hashes make silent field reinterpretation unsafe. Current identity supports schema versions. | Old free text is coerced incorrectly; old masters become falsely current; mixed readers hash different payloads. | Medium–high: v1/v2 decoder, explicit upgrader, golden hashes, registry/neutrality/Director/M4 rerun. | Introduce a new ShotSpec schema with typed `shot_size`, `camera_angle`, `camera_movement`; dual-read old schema, new-write new schema, and require manual mapping for unrecognized legacy values rather than guessing. |
| **Adaptation operations** | Nine values are frozen and cover medium mechanics; no primary source proves a cultural-localization operation. Overloading `MODIFY_FOR_MEDIUM` could hide profile divergence. | A policy rewrite is mislabeled as medium transformation, weakening fidelity review. | Low if vocabulary unchanged; high if new enum/migrations/corpus. | Keep the nine operations for v1. Reject/unresolved-review any transformation that cannot be honestly classified; add a new operation only through a later ADR with corpus evidence. |
| **Approval granularity** | Entry approval and screenplay approval+lock are frozen; aggregate map approval and approver are absent. Current authority kernels show exact whole-command hash/OCC. | All entries appear approved but map composition changed; lock occurs without matching approval; entry approvals authorize a different aggregate. | Medium: whole-map content hash/decision receipt, screenplay decision, atomic head tests, partial-entry mutations. | Preserve entry statuses as review evidence, but make one Human Showrunner decision bind the exact whole map version/hash; separately approve+lock the exact screenplay hash before Director. Do not create independent entry authority writers. |
| **Failure/severity/waiver** | Current `QualityReport` separates blocking/advisory findings (`/home/anhtuan/content-production-os-m5c/r2/contracts/results.py:46-68`); admission already hard-denies policy/currentness. External precedents do not provide governed creative waivers. | A heuristic overrides continuity/secret truth, or `off` erases a waived finding. | Medium: stable diagnostic IDs, applicability, waiver identity/reason/scope, invalidation and no-silent-disable tests. | Shared lineage, continuity, secret/knowledge, schema and approval checks are never waivable. Applicable profile hard requirements block that profile. Craft findings warn; a Human may waive only profile findings with recorded policy version, scope and rationale, invalidated by semantic change. |
| **PostgreSQL isolation/retry/locks** | M5C kernel and PostgreSQL docs support fresh-statement `READ COMMITTED`, retry-before-write, head lock, second retry lookup, predecessor OCC and one commit. | Concurrent genesis duplicates a branch; changed policy slips between precheck/write; reverse multi-head order deadlocks. | High: real PostgreSQL barriers for same-ID/same-head/different-profile genesis, changed-policy retry, rollback and deadlock timeout. | Reuse the M5C protocol: `READ COMMITTED`; resolve exact retry before genesis; lock/insert complete branch-head key; recheck retry; compare latest/effective plus policy digest; validate under lock; append and advance atomically. Canon parent is immutable-read; when multiple adaptation heads are unavoidable, sort by family then canonical UTF-8 key. |
| **Checkpoint decomposition** | Frozen roadmap specifies flow/exit but no M6 checkpoints; it requires each task to state goal, inputs, outputs, dependencies, acceptance, tests and out-of-scope (`docs/r2/R2_06_FROZEN_IMPLEMENTATION_ROADMAP.md:314-338`). | One large merge obscures authority defects, donor drift and M4 regression. | Planning-only; each checkpoint gets focused gates plus cumulative regression. | Five gates: **M6-A** contracts/schema/migrations and policy-pack pins; **M6-B** branch/map authority+OCC; **M6-C** screenplay approval, sidecars and dual-profile validation; **M6-D** Take adapter + ShotSpec retrofit + M4 rerun; **M6-E** production/candidate integration and dual Golden B evidence. |

These defaults close the original unknowns except where §8.6 says evidence is
still insufficient. They deliberately choose the smallest behavior that can
exercise both profiles without creating a general policy-composition platform.

### 8.4 Adversarial decision scenarios

| Scenario | Required fail-closed observation |
|---|---|
| **Cross-profile contamination**: a `zh-shuang` sidecar ref is attached to a Western branch, or its findings enter the Western gate. | Profile/branch/policy binding mismatch; no map/head/master change. |
| **Stale policy evidence**: sidecar was produced under pack v1, while the proposal claims v2 or the referenced evidence changed. | Digest/version mismatch before approval and again under the branch-head lock. |
| **Exact retry after policy change**: decision ID and map bytes match, but caller substitutes a newer policy digest. | Identity conflict, not successful retry. The genuine old tuple returns its historical receipt; currentness is queried separately. |
| **Concurrent branch genesis**: two writers create the same complete profile/parent/medium lineage key. | One genesis succeeds; the other resolves exact retry or deterministic conflict; no orphan map/partial head. |
| **Overlay masking**: a stronger/newer overlay changes a screenplay after approval. | Effective composite identity becomes stale; approved/locked screenplay cannot enter Director until reapproved. |
| **Branch rebase/replay**: a branch pinned to Canon v7 is replayed against v8 without a new lineage operation. | Parent mismatch; no silent rebase and no reuse of v7 approval. |
| **Rejected candidate contamination**: a later rejected or failed candidate is “latest” and replaces the master. | Promotion refuses it; prior ApprovedMaster and content fingerprint remain current. |
| **Secret leakage**: profile heuristic asks for an early reveal forbidden by SceneContract knowledge state. | Shared epistemic/continuity invariant blocks output; profile rule cannot waive or outrank it. |
| **Heuristic overrides continuity truth**: `恨爽急盼` ordering suggests moving a prop/state event before its prerequisite. | Shared state/timeline validation blocks the proposal; diagnostic records policy conflict rather than rewriting truth. |
| **Waiver laundering**: a semantic edit retains an old craft waiver. | Content/policy fingerprint change invalidates waiver currentness; finding reappears. |
| **Legacy ShotSpec ambiguity**: `camera="cinematic"` has no exact Take enum mapping. | Upgrader requires explicit review; it never guesses an angle/movement. |
| **Approval-lock split**: screenplay is approved, then edited before `locked_for_direction`. | Hash/currentness mismatch; Director admission denied. |

### 8.5 Explicitly out of M6 v1

To preserve YAGNI, the evidence supports excluding:

- dynamic profile composition, inheritance, marketplace/discovery, user-authored
  rule DSL, hot reload, and arbitrary third-party policy execution;
- H2 in-place cross-profile switching and H3 independently mutable overlay
  composition;
- automatic branch rebase/merge, cross-branch cherry-pick, policy auto-migration,
  and conflict-free replicated adaptation heads;
- automatic semantic conversion of unknown legacy framing/camera strings;
- Huohuo completion/LLM repair services, donor persistence/runtime, and any
  source-Canon mutation;
- a universal Western beat enum, automated craft-quality score, or claim that
  60–120 seconds universally maps to one chapter/four-beat arc;
- new adaptation operations without concrete unrepresentable corpus cases;
- 3D/world/spatial Director planning, already deferred beyond this stage
  (`docs/r2/R2_04_CONSOLIDATED_DECISION_LOG.md:483-498`); and
- production-scale policy administration UI, analytics, inter-rater calibration,
  and native-culture benchmark expansion beyond Golden B.

A later ADR is required before enabling any of those, changing profile
cardinality/topology, adding an adaptation operation, changing waiver authority,
allowing automatic rebase/overlay precedence, or reopening a `LOCKED` provider-
neutrality/lineage/Director decision.

### 8.6 Residuals, corrections, and round-3 coverage limits

Residual decisions that evidence cannot lock:

1. the exact `AdaptationBrief` field schema and authority owner;
2. the persistent representation of whole-map approval and whether screenplay
   approval+lock is one command or two atomic state transitions;
3. the precise composite natural key for branch genesis;
4. how legacy free-form ShotSpec values are presented for Human mapping;
5. policy-waiver expiry rules beyond semantic/policy-fingerprint invalidation;
6. numeric Western craft thresholds and inter-rater reliability; and
7. whether a later milestone must add culturally native corpora in addition to
   the shared-source comparison.

Round-3 correction: the earlier unknown “who/what defines hard Western rules”
cannot be closed by inventing beats, but the implementation default can now
separate hard shared invariants, named-format checks, and advisory craft rubric.
Likewise, “branch topology” is no longer wholly open for M6 planning: H1 is the
bounded default for v1, while H2/H3 remain later-ADR alternatives rather than
disproved designs.

Codebase Memory was used at Tier 2. The root graph generation
`2026-09-12T07:10:39Z` reported metadata matches/no recorded issue for all five
cited frozen/decision files; its only `docs/r2` scope gap was an ignored PNG.
The M5C fast graph generation `2026-09-11T11:57:25Z` matched HEAD source metadata
for the established M4/M5 files. The newer narrative-lifecycle authority and
acceptance files were `not_tracked`, and integration tests were excluded by the
fast index, so all were read directly. Coverage signals are best-effort, not
proof of completeness.

Graph traces found 16 unit-test callers of `DirectorExecutionService.execute`,
17 unit-test-path callers of admission evaluation, and the production
ApprovedMaster path from Golden A host integration. NarrativePlan graph tracing
reported no callers despite direct integration tests; this is treated as a
graph limitation, not dead-code evidence. No test suite was run because this
pass changed only research documentation and inspected the M5C worktree read
only.

No ADR/spec/plan, implementation, test, migration, registry, other worktree, or
production state was modified in this pass.

## 9. Post-review finding — currentness proof must share the locked transaction

A 2026-09-12 M5C-2 correction review exposed a reusable authority failure mode.
The accepted M5C design says a current-selection guard must, under the head lock,
load typed decisions, validate subject/action/predecessor consistency, fold the
authoritative chain, and compare both latest and effective projections
(`docs/superpowers/specs/2026-09-09-r2-m5c-narrative-lifecycle-design.md:998-1014`).
The implementation inspected at dirty worktree HEAD
`2dbfad701dc11dd3127e8fefd4e6830de3c73b09` instead compares only the mutable
head's effective pointer during extraction admission
(`/home/anhtuan/content-production-os-m5c/r2/narrative_lifecycle/evidence.py:195-228`).
Its integrity checker rebuilds the chain, but opens separate units of work for
the chain and stored-head reads
(`/home/anhtuan/content-production-os-m5c/r2/narrative_lifecycle/integrity.py:56-120`),
so invoking that public checker before or after admission would leave a TOCTOU
window rather than satisfy the under-lock proof.

The concrete counterexample is an append-only chain `d1=ACCEPT`, `d2=REJECT`
paired with an otherwise constraint-valid corrupted head whose latest and
effective pointers both name `d2`. A pointer-only guard admits a rejected
decision. A second counterexample pairs a valid effective accepting decision for
one revision with an admission naming a different revision. Pointer identity
alone cannot prove the selected evidence binding.

Three implementation patterns were compared:

1. a checker that creates its own UoW is reusable for offline audit but cannot
   make an admission proof atomic;
2. database constraints/triggers can protect local FK/check invariants but do not
   replace the semantic fold over actions and predecessors; and
3. a repository-bound pure fold/verification operation, passed the already locked
   head and already active transaction repository, proves chain, projection and
   selected artifact together before the consuming write.

Pattern 3 is the bounded default for M6. Every adaptation approval, waiver,
screenplay lock, direction admission and downstream currentness read that grants
a capability must use it. Offline integrity/rebuild APIs may still open their own
read-only UoW, but their result is diagnostic evidence, not an admission token.
Tests must corrupt heads with FK-valid rejected or wrong-subject pointers, mutate
generations, and race supersession against admission; failure writes nothing and
never repairs the head.

This pass used Codebase Memory Tier 2 generation `2026-09-12T09:35:28Z` for the
M5C worktree. All relied-on implementation paths reported metadata matches and
no recorded gap; `scripts/` remained deliberately excluded and was read
directly. Graph class traces were sparse, so exact method snippets and direct
source reads, not absent graph callers, support the conclusion. Focused tests
were green but lacked the constructed corruption case; that is evidence of a
coverage gap, not evidence against the counterexample.

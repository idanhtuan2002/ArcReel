# R2 M9 design validation

**Assessed:** 2026-09-15

**Repository HEAD:** `a3c5d315bd388583d6283ee2291ff4d303cdb362`

**Scope:** ADR-0081, M9 research, design specification, umbrella plan, M9-A
packet, execution contract, the accepted post-M8 boundary, current R2 factual
source, pinned donor source, and first-party provider documentation.

**Recommendation:** **REMEDIATE_BEFORE_APPROVAL**

This is a design review, not implementation or production authorization. The
authority decomposition and provider fail-closed baseline are sound, but three
normative gaps prevent an independently reproducible design acceptance: the
custodian decision protocol has an authorization TOCTOU and an underspecified
concurrent-first-request path; the M9 design-acceptance artifact has no frozen,
machine-verifiable custody contract; and the documents disagree about what may
execute before A0/prerequisite acceptance. These are repairable documentation
defects, not a reason to abandon the architecture.

## Method and evidence limits

- I recomputed the six candidate document hashes at the repository HEAD and
  verified the accepted post-M8 contract/research hashes both from the current
  tree and from accepted candidate commit `016e0946...`. The acceptance commit
  `25f19b12...` has that candidate as parent and changes only ADR-0080 plus its
  acceptance record, matching the recorded policy
  ([acceptance record](../r2/evidence/R2_POST_M8_ARCHITECTURE_ACCEPTANCE.json#L1-L43),
  [acceptance contract](../r2/evidence/R2_POST_M8_ARCHITECTURE_ACCEPTANCE_CONTRACT_2026-09-14.json#L169-L194)).
- Codebase Memory Tier 2 generation `2026-09-15T03:03:49Z` was checked for all
  ten relied-on local files. Every path returned `metadata_match` and
  `no_recorded_issue`. Targeted source discovery found the factual contract
  models but no runtime `FactualAuthorityPort`, `M8CanvasSeedPort`,
  `M8LearningReadPort`, or M9 implementation symbol. This is best-effort graph
  evidence, not proof of absence; direct source and filesystem checks below
  bound the negative claims.
- Direct filesystem checks found none of
  `R2_M9_DESIGN_ACCEPTANCE.json`, `R2_M8_IMPLEMENTATION_ACCEPTANCE.json`,
  `R2_FACTUAL_AUTHORITY_IMPLEMENTATION_ACCEPTANCE.json`, or
  `R2_M9_PREREQUISITE_ACCEPTANCE.json`. Therefore the current execution
  contract must stop; this review does not treat planned seams as implemented.
- The three donor files were fetched directly from their immutable GitHub commit
  URLs. Provider claims were checked only against first-party Google/YouTube and
  TikTok documentation. No secondary summary is used.

Current candidate hashes are:

| Artifact | SHA-256 at assessed HEAD |
|---|---|
| M9 research | `0d40ba87982546e1ac5eb306ed2e008769e4e4a1efce267b928071c7672e1e1a` |
| ADR-0081 | `134786333268892fe6f09c500ee627bd5309f8a334cfa05083d997a8a57095f3` |
| design specification | `021d13c6110bc694d5fe69301cab7935c67422d3886c3d39d85f4c800a01fab7` |
| umbrella plan | `ea0a74a6290720692178b34458bfe35e2193372484e973a3f47031105059ab61` |
| M9-A packet | `3fca0d15d2b826b0863244a6ace0f4883dabcb637800ed6b3e224e09d566621e` |
| execution contract | `d70fba3211c75877753e0dca3d0179696d560ec49d6526517d4ccf77b79d8bfc` |

These hashes are observations for this review only. They are not an acceptance
record.

## Compact finding table

| ID | Severity | Status | Finding |
|---|---|---|---|
| M9V-01 | High | Open | Custodian I/O is outside the transaction, but its contract is not required to be side-effect-free/duplicate-tolerant and its decision has no expiry or policy revision. Concurrent first requests and crash-before-commit can repeat the call; revocation between evaluation and commit is not closed. |
| M9V-02 | High | Open | “Lock command receipt first” does not serialize a missing receipt row. The unique key prevents duplicate committed receipts, but the normative recovery after the losing insert is unspecified. |
| M9V-03 | High | Open | M9 design acceptance names only an output path/status. It lacks a frozen schema/review contract binding exact HEAD, all six hashes, reviewer independence/blinding, preregistered rubric, commands, skips/unknowns, and a status-only acceptance commit. |
| M9V-04 | Medium | Open | The spec says execution stops *before* A0, while the packet says A0 is the only permitted pre-prerequisite step; the umbrella/contract call M9-A “released” while design status is pending. A non-interactive executor can interpret these differently. |
| M9V-05 | — | Out of scope by sponsor direction | License analysis, evidence and acceptance conditions are excluded from M9. This review makes no license finding and does not use license as a blocker. |
| M9V-06 | — | Pass | M9/Human Greenlight, M8 Canvas/Learning, Factual, Canon/Narrative, Production and provider authority boundaries match accepted ADR-0080. Missing M8/Factual implementation is correctly fail-closed. |
| M9V-07 | — | Pass | The time-sensitive YouTube, Google Trends and TikTok baseline claims remain supported by current first-party documentation and network adapters remain optional/dormant or unavailable. |

## Findings

### M9V-01 — Custodian authorization is neither replay-safe nor current at commit

**Facts.** The design defines `may_publish` and `may_decide` as external async
ports and gives `CustodianDecision` only `authorized`, subject/evidence digests,
and `evaluated_at`
([spec](../superpowers/specs/2026-09-14-r2-m9-opportunity-research-intelligence-design.md#L90-L95),
[decision model](../superpowers/specs/2026-09-14-r2-m9-opportunity-research-intelligence-design.md#L363-L385)).
The global rule correctly forbids database transactions across external I/O
([spec](../superpowers/specs/2026-09-14-r2-m9-opportunity-research-intelligence-design.md#L1188-L1222)).
M9-A explicitly calls the custodian before opening the committing transaction
([packet](../superpowers/plans/2026-09-14-r2-m9a-foundation-cohort-profiles.md#L218-L230)).

**Inference.** Two same-command first requests can both observe no receipt and
both call the custodian. A process can also crash after the custodian response
but before the M9 commit, causing a retry to call it again. This is safe only if
the port is explicitly read-only, side-effect-free and duplicate-tolerant. The
current contract does not state that. Separately, because the returned decision
has neither `decision_id`, custodian-policy revision nor `expires_at`, a Human's
eligibility/delegation/revocation can change after `may_publish`/`may_decide`
returns and before the transaction commits. Recomputing `subject_digest` proves
what was evaluated; it does not prove the authorization is still current.

**Recommendation.** Make custodian evaluation an attest-and-verify protocol:

1. add `decision_id`, `custodian_policy_id`, `custodian_policy_version`,
   `evaluated_subject_digest`, and `expires_at` to the frozen decision;
2. state that `may_publish`/`may_decide` is read-only, side-effect-free,
   idempotent-by-subject, duplicate-tolerant, and performs no authority mutation;
3. add a host-owned, local `verify_current(decision)` seam usable during the
   short commit transaction, or define a bounded lease whose policy revision is
   locked/revalidated atomically by the host adapter;
4. forbid commit when the decision expired, was revoked, or its policy revision
   changed; and
5. test two simultaneous first calls, crash after evaluation/before commit,
   revocation between evaluation and commit, and exact replay after commit.

If the host cannot supply atomic currentness verification, the design must name
and justify an explicit maximum authorization-staleness window. It must not call
the result “exact” without that qualification.

### M9V-02 — absent-row receipt locking needs a normative winner/loser algorithm

**Facts.** The design says to lock and read the command receipt first, then
atomically commit mutation/head/event/receipt
([spec](../superpowers/specs/2026-09-14-r2-m9-opportunity-research-intelligence-design.md#L1190-L1205)).
The M9-A table has a unique key on
`(user_id, actor_id, operation, command_id)`
([packet](../superpowers/plans/2026-09-14-r2-m9a-foundation-cohort-profiles.md#L108-L117)),
and repository tests mention a duplicate-key race and race translation
([packet](../superpowers/plans/2026-09-14-r2-m9a-foundation-cohort-profiles.md#L184-L205)).

PostgreSQL documents that `SELECT ... FOR UPDATE` locks the rows actually
returned, while a conflicting insert into a unique index waits and then either
succeeds or raises a uniqueness violation after the other transaction resolves
([row locking](https://www.postgresql.org/docs/current/explicit-locking.html),
[unique checks](https://www.postgresql.org/docs/current/index-unique-checks.html)).

**Inference.** A missing receipt row cannot be row-locked. Both transactions may
perform pre-commit work and attempt the insert. The uniqueness constraint
protects committed state, but “translate races into stable results” does not say
how the losing transaction rolls back its failed transaction, re-reads the
winner, compares request digests, and returns the exact original receipt. An
implementation can easily return a generic conflict or retry the entire
custodian call.

**Recommendation.** Freeze one algorithm in spec §9 and M9-A A2/A3: reserve a
durable command-intent row with `INSERT ... ON CONFLICT`, or catch the unique
race in a savepoint/rolled-back transaction, then re-read the committed winner,
return it only for an equal request digest, and return
`M9_COMMAND_REPLAY_CONFLICT` otherwise. State explicitly that the losing path
does not repeat non-idempotent I/O and add crash cuts before/after reservation,
custodian evaluation, aggregate write, receipt write, and commit acknowledgement.

### M9V-03 — design-acceptance custody is not machine-verifiable yet

**Facts.** The accepted post-M8 architecture has a detailed normative review
contract: minimum two mutually independent blind reviewers, required reviewer
fields, exact PASS rubric, exact hash/parent rules, empty skips/unknowns, and a
status-only acceptance commit
([review policy](../r2/evidence/R2_POST_M8_ARCHITECTURE_ACCEPTANCE_CONTRACT_2026-09-14.json#L144-L167),
[commit policy](../r2/evidence/R2_POST_M8_ARCHITECTURE_ACCEPTANCE_CONTRACT_2026-09-14.json#L169-L194)).
ADR-0080 requires each milestone to freeze its contract and evidence schema
hashes at design acceptance
([schema-freeze protocol](../r2/evidence/R2_POST_M8_ARCHITECTURE_ACCEPTANCE_CONTRACT_2026-09-14.json#L47-L80)).

The M9 spec repeats the intended outcome in prose
([design conditions](../superpowers/specs/2026-09-14-r2-m9-opportunity-research-intelligence-design.md#L1692-L1715)),
but the M9 execution contract gives the design acceptance only a path and status
and its generic properties do not define a schema or reviewer custody
([contract](../r2/evidence/R2_M9_EXECUTION_CONTRACT_2026-09-14.json#L18-L49)).
No M9 design-acceptance contract/schema or acceptance artifact exists at the
assessed HEAD.

**Inference.** Absence of the final acceptance artifact is expected while review
is pending. Absence of a frozen acceptance *contract* is different: reviewers
cannot independently know the canonical fields, hash domain, exact candidate
HEAD/parent rule, whether reviews were blind before sharing, or which commit may
transition ADR status. A future JSON file with the right status string could
satisfy the present execution contract without proving the design conditions.

**Recommendation.** Before approval, add and bind a normative
`R2_M9_DESIGN_ACCEPTANCE_CONTRACT_2026-09-15.json` plus a strict JSON Schema. It
must require:

- exact candidate HEAD and parent;
- exact paths and SHA-256 values for ADR, research, spec, umbrella plan, M9-A,
  execution contract, acceptance contract and schema;
- preregistered rubric ID/hash created before reviewer verdicts;
- at least two author-independent and mutually blind reviewer records, including
  qualification, conflict declaration, reviewed HEAD, verdict and timestamp;
- review outputs/hashes or immutable refs, and proof they were not shared until
  both verdicts were sealed;
- command results used to verify hashes, lineage, dirty paths, JSON/schema
  validity and cross-document synchronization;
- empty `required_skips` and `material_unknowns`; and
- an acceptance commit whose parent is the reviewed candidate and whose
  allowlist contains only ADR status plus acceptance artifacts.

Then make the execution contract verify the acceptance artifact against that
contract/schema rather than checking only `status`.

### M9V-04 — A0 and “released” have conflicting meanings

**Facts.** The spec says execution stops “before Task A0” without accepted M8 and
Factual evidence
([spec](../superpowers/specs/2026-09-14-r2-m9-opportunity-research-intelligence-design.md#L38-L40)).
The M9-A packet says A0 is the only step permitted before all prerequisites pass
and directs it to emit a stop receipt
([packet](../superpowers/plans/2026-09-14-r2-m9a-foundation-cohort-profiles.md#L17-L37)).
The umbrella says only M9-A is “released now”
([umbrella](../superpowers/plans/2026-09-14-r2-m9-opportunity-research-intelligence.md#L82-L94)),
and the execution contract says `released_packet: M9-A` while its own status is
`DESIGN_REVIEW_PENDING`
([contract](../r2/evidence/R2_M9_EXECUTION_CONTRACT_2026-09-14.json#L1-L16)).

**Inference.** The intended behavior is discernible—read-only A0 preflight may
run and emit one uncommitted stop receipt; implementation may not start—but the
normative words permit both “do not run A0” and “run A0.” “Released” can also be
mistaken for execution authorization.

**Recommendation.** Use two explicit states everywhere:
`PACKET_AUTHORED_FOR_REVIEW` and `PACKET_EXECUTION_BLOCKED`. Replace “before Task
A0” with “before A0 production-file creation; A0 read-only preflight and an
uncommitted stop receipt are allowed.” Define that the preflight verifier must
already exist in an independently accepted bootstrap/tooling packet, or state
that it is authored only after prerequisites pass; it cannot both be absent and
be the mechanism required to fail before writes.

### M9V-05 — license explicitly excluded from M9 scope

**Facts.** Direct reads at the exact pins confirm the claimed shapes:

- OpenMontage's pinned
  [`research_brief.schema.json`](https://github.com/calesthio/OpenMontage/blob/08e2151fa02de28a5d6a312b3d575692bf147ad7/schemas/artifacts/research_brief.schema.json)
  contains landscape, saturated-angle, underserved-gap, audience/angle and source
  vocabulary.
- Kalinga's pinned
  [`research.py`](https://github.com/desaultkhan/Kalinga-Shorts-Factory/blob/e4b5a2173ca03d365aad565a89fcc43159b44f9b/pipeline/src/research.py)
  uses an adapter registry, trusts an existing mutable `facts.json`, writes that
  cache directly and contains broad exception handling, supporting its use as a
  fixture/donor-defect source rather than authority.
- Huohuo's pinned
  [`novel-outline-drama-fields.ts`](https://github.com/appolloqin/huohuo-drama/blob/f104b853b3563e124d9cde25f9331d323fb483b9/workbench-server/src/services/novel/novel-outline-drama-fields.ts)
  defines native `恨/爽/急/盼`, conflict, desire, obstacle, stakes, choice and
  related drama fields. This supports vocabulary/fixture reuse, not engagement
  or factual authority.

The donor pins and selected paths are synchronized between research and the
execution contract
([contract donor inventory](../r2/evidence/R2_M9_EXECUTION_CONTRACT_2026-09-14.json#L72-L100)).
The sponsor explicitly directs M9 to ignore all license questions. Accordingly,
this validation does not assess donor licenses, require license evidence, limit
reuse based on license, or make license-related acceptance recommendations.
License is not part of the M9 design gate.

## Validated boundaries and provider assumptions

### Authority and repository evidence

ADR-0080 assigns opportunity Greenlight to M9's Human custodian, factual claims
to existing Factual Authority, ApprovedMaster to Production Authority and
learning lifecycle to M8
([accepted contract](../r2/evidence/R2_POST_M8_ARCHITECTURE_ACCEPTANCE_CONTRACT_2026-09-14.json#L36-L45)).
ADR-0081 preserves those separations and explicitly blocks implementation on the
missing durable Factual and accepted M8 seams
([ADR-0081](../adr/0081-m9-evidence-first-opportunity-intelligence.md#L59-L76)).
The current repository contains typed `SourceRecord`, `EvidenceRecord`,
`ResearchPack`, `Claim`, and `ClaimLedger` contracts
([factual contracts](../../r2/contracts/factual.py#L29-L94)); these models do not
constitute a repository/service/transaction authority. The design's negative
claim and stop codes are therefore correctly conservative.

Greenlight is restricted to Canvas exploration and cannot promote M8, write
Canon/Narrative/Production, verify claims or approve ResearchPacks
([ADR-0081](../adr/0081-m9-evidence-first-opportunity-intelligence.md#L59-L70),
[bridge protocol](../superpowers/specs/2026-09-14-r2-m9-opportunity-research-intelligence-design.md#L1330-L1378)).
This matches the accepted post-M8 boundary
([ADR-0080](../adr/0080-post-m8-north-star-closed-loop.md#L30-L41)).

### First-party provider/API facts

- YouTube's current `search.list` documentation says results identify video,
  channel and playlist resources; its quota page gives a separate default 100
  `search.list` calls/day bucket, while `videos.list` costs one unit and permits
  up to 50 IDs. The research classification is accurate
  ([search.list](https://developers.google.com/youtube/v3/docs/search/list),
  [videos.list](https://developers.google.com/youtube/v3/docs/videos/list),
  [quota calculator](https://developers.google.com/youtube/v3/determine_quota_cost)).
- YouTube's first-party derived-metrics policy still makes the exception
  conditional on acceptance of the Analytics & Reporting amendment, requires
  derived values to be distinguished, permits qualifying statistical/derived
  retention up to 36 months, and leaves titles/names/descriptions/comment text
  under the 30-day rule. Disabled-by-default, per-signal evidence is the correct
  fail-closed baseline
  ([policy](https://developers.google.com/youtube/terms/derived-metrics-policy)).
- Google still labels Trends API as alpha, application-only, with a rolling
  five-year window, regular interval aggregations, geography and consistently
  scaled data. Optional/unavailable baseline is accurate
  ([Google Trends API](https://developers.google.com/search/apis/trends)).
- TikTok still says creators, advertisers and commercial users are ineligible
  for Research Tools; default research quotas are 1,000 requests and 100,000
  records/day; query-video search is archived, with up to 48-hour new-video and
  10-day statistics lag
  ([Research API FAQ](https://developers.tiktok.com/docs/en/research-api-faq)).
  Commercial Content endpoints use a client token and `search_id`/`has_more`
  pagination over commercial/ad content, not the organic universe
  ([getting started](https://developers.tiktok.com/docs/en/commercial-content-api-getting-started),
  [query commercial content](https://developers.tiktok.com/docs/en/commercial-content-api-query-commercial-content)).

These policy facts are time-sensitive. The existing requirement to revalidate
them at adapter design acceptance, activation and policy change is necessary;
public documentation remains policy evidence, not account authorization
([post-M8 platform policy](../r2/evidence/R2_POST_M8_ARCHITECTURE_ACCEPTANCE_CONTRACT_2026-09-14.json#L126-L142)).

## Design-time unknown closure

| Unknown from M9 research §11 | Validation |
|---|---|
| accepted M8 implementation | Correctly open and hard-blocked by `M9_M8_IMPLEMENTATION_NOT_ACCEPTED`. |
| durable Factual Authority | Correctly open and hard-blocked by `M9_FACTUAL_AUTHORITY_UNAVAILABLE`. |
| provider account authorization | Correctly deferred to exact host grants; network baseline does not depend on it. |
| scoring/calibration and cohort corpora | Correctly not invented; no universal score, later frozen per-cohort inputs required. |
| snapshot store, deletion and coverage | Contractual behavior is sufficiently shaped for a design candidate; implementation choice/evidence remains packet-gated. |
| operational envelope and product utility | Explicitly preregistered for M9-F rather than claimed now. |
| custodian eligibility/revocation/currentness | **Not closed:** M9V-01. |
| independent design acceptance custody | **Not closed:** M9V-03. |
| donor license/reuse disposition | Explicitly out of M9 scope by sponsor direction; not an acceptance blocker. |

## Exact remediation set before approval

### Design disposition recorded after this assessment

The sponsor approved remediation of M9V-01 through M9V-04 and explicitly
excluded all license questions from M9. The remediated candidate selects:

- a host-owned, command-replayable authorization lease binding the exact
  subject and custodian-policy revision with a maximum 30-second admission
  window;
- PostgreSQL `pg_advisory_xact_lock` serialization derived from a
  domain-separated hash of the full command key, followed by a full-key receipt
  reread before aggregate locks;
- a milestone-specific M9 design-acceptance contract and strict JSON Schema
  specializing the accepted post-M8 review policy; and
- `PACKET_AUTHORED_FOR_REVIEW` plus `PACKET_EXECUTION_BLOCKED`, with only
  read-only A0 preflight allowed before prerequisite acceptance.

These edits resolve the design recommendation only after independent review
rechecks their exact candidate HEAD and hashes. This report does not itself
change `REMEDIATE_BEFORE_APPROVAL` into acceptance.

1. Amend spec §§4.1, 7.1, 9, 12 and 20 plus M9-A A2/A3 with the decision
   attestation/currentness and absent-row concurrency algorithm in M9V-01/02.
2. Add a strict M9 design-acceptance contract and schema, bind them from the
   execution contract, and produce two sealed blind reviews against one exact
   candidate HEAD using a preregistered rubric as described in M9V-03.
3. Synchronize the spec, umbrella, M9-A and execution contract on
   `PACKET_AUTHORED_FOR_REVIEW`, `PACKET_EXECUTION_BLOCKED`, and the exact
   read-only A0 preflight boundary.
4. Recompute all document/contract/schema hashes after remediation, rerun the
   cross-document/stop-code verifier, require empty skips/material unknowns, and
   only then solicit two independent blind PASS verdicts.

Until those edits are accepted, M9 remains a strong architecture proposal and a
useful planning packet, but not an acceptably frozen design candidate and not an
executable implementation packet.

## 2026-09-16 independent-review remediation

Blind review of candidate `f4cc42d15b7cd42215aa2145a9125d64aede5feb`
demonstrated a new machine-verifiability counterexample: the acceptance schema
accepted duplicate reviewer identities, mismatched candidate/contract values,
incomplete rubric evidence and share times preceding seals. This supersedes the
earlier belief that one strict acceptance schema closed M9V-03.

The remediation separates three controls. A sealed-review schema fixes the
per-review shape and requires every preregistered check to PASS. The acceptance
schema hash-binds that schema and the verifier. The cross-record verifier rejects
duplicate JSON keys, binds recorded hashes to the exact sealed bytes, checks
review metadata against the acceptance record, and enforces identity and time
ordering constraints that portable Draft 2020-12 JSON Schema cannot express.
Both blind reviews must restart against the remediated candidate; the failed
review of `f4cc42d1` is diagnostic evidence only.

A second blind review cycle against `0ad3fcc2` found that the first verifier
revision closed review-bundle substitution but still trusted caller-supplied
candidate and artifact facts. The next remediation adds a repository entry
point that resolves exact Git blobs and parents, enforces the four-path
acceptance commit, recomputes all twelve candidate artifact hashes plus the
status-only ADR transition, checks embedded command output hashes and rejects a
dirty acceptance tree. Review outputs from both failed candidates remain
diagnostic only; neither may be reused for acceptance.

Blind review of `f986e8ec` found three additional closure defects: self-attested
command output was tautological, malformed review timestamps could escape
format validation and crash, and first-parent lookup did not reject merges.
The remediation removes command evidence from the authority record, makes the
executed Git-backed verifier the only command gate, validates/parses all review
timestamps fail-closed, and requires exactly one parent for both candidate and
acceptance commits.

Blind review of `8ce1ad67` found that semantic checks still ran after an
acceptance-schema failure and that the execution contract retained a generic
one-artifact acceptance sentence. The verifier now returns schema errors before
touching semantic fields, and the execution contract states the exact four-path
M9 design-acceptance commit already enforced by the contract and verifier.

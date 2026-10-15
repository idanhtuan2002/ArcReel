# R2 M8-F: evaluation inputs and the creative-profile seam

**Date:** 2026-10-15. **Base:** `r2-v2/main` `6d4f7369` (M8-E merged and pushed). **Branch:** `impl/r2-m8f-utility`.

**Sponsor direction (2026-10-15):** the reviewer roster is the sponsor alone, with a recorded deviation. The
sponsor delegated the corpus and the effect/confidence policy: "research first, compare with history and the
existing documents, then decide."

## 1. What M8-F must prove

M8-F has to show measurable M8 utility, isolated by profile, and then seal an acceptance dossier. That
dossier does not authorize production. The required proof comes from these sources:

- **Spec §12 Gate F:** end-to-end workflows run separately for `generic-western` and `zh-shuang`, with a
  pre-registered baseline and effect policy, plus resource and failure evidence.
- **Spec §9:**
  - separate corpora and qualified reviewers for each profile;
  - at least two blind reviews per artifact, with disagreement kept;
  - a pilot before a confirmatory sample;
  - `rubric_version` and reviewer qualification frozen before any result.
- **Execution contract `R2_M8_EXECUTION_CONTRACT_2026-09-13.json`, `packet_inputs.M8-F`:** three inputs are owned
  by humans: a locked corpus, an effect or confidence policy, and the reviewer roster with conflict
  declarations. If any is missing, the packet stops with `M8_EVALUATION_NOT_PREREGISTERED`.
- **Global constraint:** no paid provider or platform call, and no credential use.

## 2. Facts found in the code (`6d4f7369`)

1. **F1. Every Canvas and Format lineage binds the host profile.**
   - `r2/advanced_creative/lineage.py` (ADR-0098, resolution v1) binds `creative_profile_id = "arcreel.host"`, version `1`,
     to every episode.
   - `server/services/format_candidate.py` stamps the same host profile.
   - Learning ingest (`server/services/learning.ingest_observation`) and the spatial routes resolve their lineage
     through `episode_lineage`.
   - So no M8 artifact on V2 carries `generic-western` or `zh-shuang`.
2. **F2. Profile identities exist only in M6 and in the target registry.**
   - The M6 identities are `AdaptationProfileId.WESTERN_GENERIC` and `CN_SHORT_DRAMA_SHUANGWEN`.
     `AdaptationProfileRef` adds `profile_version` and `policy_pack_digest`.
   - Gate B (`POST /projects/{p}/gates/narrative-lock`) admits a screenplay together with its `profile_ref`.
   - Registry targets (M8-C) store the `AdmittedScreenplayRef`, which includes `profile_ref`.
   - The current admission is the `SCREENPLAY_ADMISSION` adaptation head whose `effective_decision_id` is non-null.
     A `REVOKE` clears it.
3. **F3. Learning already enforces cohort isolation, but only in the pure layer.**
   `r2/learning/cohorts.py` refuses to pool profiles (`M8_PROFILE_COHORT_LEAK`). Its tests use the string
   `generic-western`, which no host path produces.
4. **F4. ADR-0098 planned the extension:** "Binding an adaptation profile … later changes only the resolver. The
   route and the client stay the same. Each change is a new resolution version recorded in an ADR."
5. **F5. ADR-0104: an R2 project holds a single screenplay at episode 1.** Take shot masters live at
   `episode_video(1, target_id)`. Multi-episode R2 projects are out of scope.
6. **F6. Golden B puts both profiles in one project** (`tests/integration/r2/test_m6_dual_profile_acceptance.py`,
   `PROJECT`). It is a deterministic slice of 60–120 s for each profile, with no provider cost. The shuangwen
   text there is "structurally valid but minimal", and its docstring explicitly makes no claim of cultural
   representativeness.
7. **F7. M8 evidence history:**
   - **M8-D:** offline replay only; every claim is associative; the pilot/confirmatory protocol was not built
     (coverage limit).
   - **M8-E:** one blind reviewer (the sponsor) with a recorded `SINGLE_REVIEWER_DEVIATION`; the 7-item semantic
     rubric; real renders at 9:16 PAD on staging.
8. **F8. Where M8 sits in the release plan.** ADR-0089 places M8 in V2. No V2 production authorization depends
   on M8-F.

## 3. Inference

Gate F asks for workflows isolated by profile. On the current code, any such workflow would bind
`arcreel.host`. Two ways out both fail:

- Labelling fixture rows `generic-western` would bypass the host. That is the shadow-identity pattern
  ADR-0098 rejected (a client-built lineage).
- Evaluating only the host profile would leave Gate F's main requirement as a material unknown. The spec says
  material unknowns block acceptance.

So M8-F needs a prerequisite packet before F1: lineage resolution v2.

## 4. Decisions

### DEC-F-0: lineage resolution v2 binds the admitted screenplay's profile (prerequisite packet F0)

This is recorded as ADR-0105. Resolution for user U, project P and episode E:

| Effective `SCREENPLAY_ADMISSION` heads of (U, P) | E | Lineage |
|---|---|---|
| 0 | any | v1, unchanged: `arcreel.host` |
| 1 | 1 | v2: the profile comes from the admission's `profile_ref`; the content basis binds both the script bytes and the admission |
| 1 | ≠ 1 | refused: `m8_lineage_episode_out_of_scope` (ADR-0104: single screenplay at episode 1) |
| ≥ 2 | any | refused: `m8_lineage_ambiguous` (fail closed; never choose one) |

In the v2 lineage:

- `creative_profile_id` is the M6 enum value. The spec labels map to it: `WESTERN_GENERIC` is
  `generic-western` and `CN_SHORT_DRAMA_SHUANGWEN` is `zh-shuang`.
- `creative_profile_version` is `profile_version`.
- `policy_digest` is the `policy_pack_digest`.
- `content_basis_digest` is the canonical digest of
  `{basis_kind: "admitted_screenplay_episode_script", episode, script_digest, admission_decision_id,
  admission_decision_digest, screenplay_ref}`.

A Format candidate takes its lineage from the same resolver, applied to its source master's project and
episode, instead of the hard-coded host profile. A revoked or replaced admission changes the lineage, so
promotion currentness and learning cohorts see it as a new lineage.

**Why:** this is the extension ADR-0098 planned. It reuses an existing human authority (Gate B), adds no table
and no migration, keeps the episode rule of ADR-0104, and keeps the v1 bytes unchanged for host-only projects.

**Rejected alternatives:**

- **An explicit episode→screenplay binding record.** It would be a new human claim, nothing would check that
  the script matches the screenplay, and it needs a migration.
- **Profile labels in fixtures only.** They form a shadow identity.
- **Keeping only the host profile and recording a deviation.** Gate F's core requirement would stay unknown.

### DEC-F-1: the corpus is deterministic fixtures, one project per profile (the locked corpus)

- **Creative corpus.** Golden B's shared Canon is split into two projects:
  - `m8f-western`, admitted under `WESTERN_GENERIC`;
  - `m8f-shuang`, admitted under `CN_SHORT_DRAMA_SHUANGWEN`.

  Each project has an episode-1 host script, approved Take shot masters produced by the existing M3/M6 local
  primitives, and the workflows run through the host services and routes. A project with only one profile
  satisfies `≥ 2` refusal by construction, and it gives a project-disjoint unit.
- **Learning corpus.** Each profile gets two further fixture projects, `m8f-<profile>-train` and
  `m8f-<profile>-holdout`, both admitted under the same profile. Their YouTube and TikTok observation rows
  have the shape of the M8-D fixtures and are ingested through the host route. Holdout is project-disjoint and
  then future-time, as in spec §9.
- **Lock.** The protocol records the sha256 of every fixture source file and of the Canon/text inputs. It also
  records the digests the corpus builder emits for every generated input (scripts, masters, observation
  rows). These digests are produced by the builder before any workflow result exists.
- **Rejected: the real staging project `du-an-01`.**
  - Spatial and shot generation there need paid Gemini or DashScope calls, which the contract forbids.
  - It binds only the host profile, so it has no cohort.
  - It cannot be reproduced.
- **Stated limit.** The shuangwen corpus is structurally valid but culturally minimal. Following F6, M8-F does
  not claim cultural representativeness.

### DEC-F-2: the effect and confidence policy is a pre-registered capability delta with deterministic replay

The available evidence is one reviewer, deterministic offline outputs, and a sequential, non-randomized design.
None of it supports an inferential effect size. Spec §9 already limits such designs to associative claims. The
utility claim is therefore a capability claim, measured against a baseline:

- **Baseline arm.** The same corpus run through the host with no M8 surface. It is measured on the same
  dimensions, and the baseline values are recorded by running it, not assumed.
- **Endpoints for each cohort.** An endpoint passes only when both conditions hold:
  1. The M8 arm delivers at least one more gated deliverable than the baseline in **each** of the four
     capabilities, with all of that capability's gates passing:
     - **Canvas:** an exploration saved with at least two sibling alternatives and its history, reloaded
     intact and bound to the cohort lineage, while the approved masters stay untouched. Canvas has no
     promotion in M8 (spec §7, ADR-0097 decision 2), so the promotion leg of "Canvas/promotion" is exercised
     by Format and Spatial;
     - **Spatial:** a promoted constraint set available to generation;
     - **Learning:** a lineage-bound recommendation with holdout evidence;
     - **Format:** 9:16 and 1:1 deliverables that pass both the technical and the semantic report.
  2. Nothing regresses: the baseline's deliverables (approved master bytes and heads) stay byte-identical.
- **Smallest useful effect.** +1 gated deliverable for each capability in each cohort, and 0 regressions.
  Invariant violations have zero tolerance: bypass, stale promotion, lost edit, profile leak, untracked
  reframe, unknown, or required skip.
- **Confidence.** Two independent replays from an empty database must give identical artifact digests and
  verdicts. No sampling inference is made. Review verdicts are reported as exact counts, with a Wilson 95%
  interval for description only.
- **Design class.** `OFFLINE_REPLAY` / sequential. Causal wording is forbidden, and the existing
  `CausalLanguageError` guard applies.
- **Exclusions.** None are pre-declared. An exclusion after any result exists fails the packet.
- **Windows.** The fixture observation windows are fixed in the corpus lock.
- **Pilot and confirmatory sample.** Deterministic outputs and a single reviewer give no variance to estimate,
  so no confirmatory statistical sample is fixed. This is recorded as a deviation from spec §9.
- **Resource envelope.** It is pre-registered from the measured M8-E render and the M7 ceilings. The ceilings
  are fixed in the protocol, and every scenario records its wall time, peak RSS and disk.

### DEC-F-3: the reviewer roster is the sponsor alone, with deviations (sponsor decision)

- **Reviewer.** One reviewer for both cohorts, holding a showrunner grant, as in M8-E.
- **Rubric.** The reviewer reuses the M8-E rubric version for format artifacts. A Canvas/Spatial rubric is
  frozen in F1, before any result.
- **Qualification record.**
  - language and cultural cohort: Vietnamese. The reviewer is not a native reader for `zh-shuang`;
  - the rubric calibration fixture results;
  - role: sponsor and plan author;
  - the conflict declaration.
- **Recorded deviations:**
  - `SINGLE_REVIEWER_DEVIATION`;
  - `NON_NATIVE_ZH_SHUANG_REVIEWER`;
  - `REVIEWER_AUTHORED_PLAN`.
- **Effect on the dossier.** The acceptance dossier carries these deviations as limits. They do not count as
  passes of the two-reviewer requirement.

## 5. Unknowns

- **U1 (resolved).** No promotion path rereads the lineage resolver. `promotion.py` only recomputes the payload
  digest over the stored lineage. Canvas candidates are not promotable (`promotable_format` raises
  `PromotionTargetUnavailableError`). The resolver is read by:
  - the Canvas context route;
  - spatial execution (`lineage_for`);
  - learning ingest, which requires `observation.lineage == server lineage`.

  The format candidate builds its own lineage with the host profile stamped in. `episode_lineage` takes no
  user, but admissions belong to a user, so v2 needs a session and a user id at every call site.
- **U2.** Does a host episode-1 script exist in the V1/R2 operator path for an admitted project? If not, that
  path keeps v1 lineage until a script is indexed. That is acceptable, because v1 is unchanged.
- **U3.** The M7 resource ceilings for an integrated run of four workflows have not been measured yet. The
  protocol fixes ceilings before F2 runs.

## 6. Packet order

```text
F0 lineage resolution v2 (ADR-0105, tests on SQLite + PG18)
 -> F1 pre-registration (R2_M8_EVALUATION_PROTOCOL.json + schema tests + corpus builder lock)
 -> F2 integrated cohort runs, baseline arm, replay, restart/concurrency/resource, sponsor blind review
 -> F3 dossier (R2_M8_ACCEPTANCE.json), independent Codex review, stop with production unapproved
```

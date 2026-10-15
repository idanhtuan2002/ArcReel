---
status: accepted
---

# M8 lineage resolution v2 binds the admitted screenplay's creative profile

**Sponsor delegation (2026-10-15):** the sponsor asked the agent to research and decide M8-F's evaluation
inputs. M8-F cannot run without the seam this ADR fixes. The evidence is in
[`2026-10-15-r2-m8f-evaluation-and-profile-seam.md`](../research/2026-10-15-r2-m8f-evaluation-and-profile-seam.md).

## Context

Spec §12 Gate F requires M8 workflows isolated by profile, run separately for `generic-western` and
`zh-shuang`. ADR-0098 fixed lineage resolution v1, which binds every episode to the ArcReel host profile
(`arcreel.host`). The format candidate also writes that profile itself. As a result, no M8 artifact on V2
carries an M6 profile, and the pure cohort guard in `r2/learning/cohorts.py` never sees one from the host.

The M6 profile is already fixed by a human authority:

- Gate B (`narrative-lock`) admits a screenplay under an `AdaptationProfileRef`.
- The effective `SCREENPLAY_ADMISSION` head selects the current admission. A `REVOKE` clears that head.

ADR-0104 fixes an R2 project to a single screenplay at episode 1. ADR-0098 planned that binding an adaptation
profile would change only the resolver, as a new resolution version recorded in an ADR.

## Decision

1. **The resolution is user-scoped.** The resolver reads the effective `SCREENPLAY_ADMISSION` heads of
   (user, project) in the same session as the caller.

   | Effective admissions | Episode | Result |
   |---|---|---|
   | 0 | any | resolution v1, byte-identical to ADR-0098 |
   | 1 | 1 | resolution v2 (item 2) |
   | 1 | ≠ 1 | refused: `M8_LINEAGE_EPISODE_OUT_OF_SCOPE` |
   | ≥ 2 | any | refused: `M8_LINEAGE_AMBIGUOUS`; the resolver never chooses one |

   Both refusals are HTTP 409. An episode without a readable indexed script is still not found, as in v1.

2. **Resolution v2.** With exactly one effective admission (`profile_ref`, `admission_ref`, `screenplay_ref`):
   - `creative_profile_id` is `profile_ref.profile_id`, the M6 enum value: `WESTERN_GENERIC` for
     `generic-western` or `CN_SHORT_DRAMA_SHUANGWEN` for `zh-shuang`.
   - `creative_profile_version` is `profile_ref.profile_version`.
   - `policy_digest` is `profile_ref.policy_pack_digest`.
   - `content_basis_digest` is the canonical digest of
     `{"basis_kind": "admitted_screenplay_episode_script", "episode": 1, "script_digest": "sha256:<hex>",
     "admission_decision_id", "admission_decision_digest", "screenplay_id", "screenplay_version",
     "screenplay_content_hash"}`.
   - `approved_master_id` and `approved_master_digest` stay null, as in v1.

3. **Format candidates use the project's profile.** `format_candidate_lineage` keeps its source-master content
   basis. Its profile fields come from the same admission read for the project, so a host-only project still
   gets the host profile. If the project has two or more effective admissions, the candidate is refused with
   `M8_LINEAGE_AMBIGUOUS`.

4. **No route or contract changes.** The context route, the Canvas client, the spatial `lineage_for` hook and
   the learning ingest check stay the same; they read the new resolver. There is no migration.

5. **Currentness is unchanged.** Promotion still recomputes the payload digest over the stored lineage and does
   not reread the resolver. A new or revoked admission changes the lineage. Later Canvas revisions and
   observations then carry the new lineage, and learning cohorts keep the old and new lineages apart.

## Consequences

- Host-only projects keep v1 lineage bytes. Existing revisions, digests and tests are unaffected.
- A project that admits both profiles (as Golden B does) is refused for M8 until one admission is revoked. The
  M8-F corpus therefore uses one project per profile.
- Learning cohorts, format candidates and spatial executions of an admitted project now carry the M6 profile.
  That is the precondition for Gate F's profile isolation.
- The resolver now needs a database session and a user id. Every call site already has both.

## Rejected

- **An explicit record binding an episode to a screenplay.** It is a new human claim that nothing checks
  against the script, and it needs a migration.
- **Profile labels supplied by fixtures or the client.** They form a shadow identity, which ADR-0098 already
  rejected.
- **Choosing the latest admission when several exist.** It silently pools profiles and violates the spec's rule
  against a floating "latest" profile.

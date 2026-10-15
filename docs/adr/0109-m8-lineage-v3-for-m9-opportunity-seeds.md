---
status: accepted
---

# M8 lineage resolution v3 binds an M9 opportunity seed

**Context.**
- ADR-0098 requires every new M8 lineage resolution to be a new resolution version recorded in an ADR.
- ADR-0105 (resolution v2) binds a project's admitted M6 profile.
- The M9 design creates a Canvas seed from an approved Greenlight. The seed's content basis is the
  M9 creative content, not an episode script.
- The first M9 design-review pass found that putting the raw M9 `creative_content_digest` into the
  M8 `content_basis_digest` would create an untagged resolution kind that M8 consumers cannot
  identify (finding 8).

**Decision.**

1. **Resolution v3 applies only to M9 opportunity seeds.**
   - `content_basis_digest` is the canonical M8 digest of
     `{"basis_kind": "m9_opportunity_seed", "creative_content_digest": <M9 digest>,
     "greenlight_decision_id": <id>, "greenlight_binding_digest": <digest>}`.
   - The profile fields come from `project_profile` over the user's effective screenplay admissions
     (ADR-0105). Two or more admissions are refused with `M8_LINEAGE_AMBIGUOUS`.
   - `approved_master_id` and `approved_master_digest` are null.
2. **The resolver is an additive M8 function,** `resolve_opportunity_seed_lineage`, in
   `r2/advanced_creative/lineage.py`. It is pure: the host passes in the admissions.
   - Resolutions v1 and v2 keep their bytes.
   - The function is delivered by the M9-D packet as an explicit M8 evolution, under M8 tests.
3. **Only the M9 seed path calls it.**
   - The `seed_canvas` prepare transaction resolves the lineage and freezes the complete M8
     revision in a bridge intent.
   - The server-side seed adapter then appends that frozen revision verbatim through the M8
     exploration service, and exact replay makes a retry safe.
   - The client append route (ADR-0107) never accepts a v3 lineage, because its check matches
     only episode resolutions.
4. **M8 consumers distinguish the kind.** The `basis_kind` is inside the hashed object, so a v3
   basis cannot collide with a v1 or v2 basis. A future Canvas promotion must check currentness
   against the resolver of the matching kind.

**Status.** Accepted on 2026-10-15 with the M9 design revalidation, by sponsor delegation of
technical choices. It binds code only from M9-D onward, after the M9 design acceptance.

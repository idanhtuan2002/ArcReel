---
status: accepted
---

# A client Canvas revision must carry a server-resolved lineage

**Found by:** the independent Codex review of the M8-F candidate on 2026-10-15 (High 1).

## Context

ADR-0098 has the client copy the server-resolved lineage into a Canvas revision. Append itself checks
only the project and the author, and "lineage currentness is checked where authority is exercised".
Canvas has no promotion, and ADR-0105 made the lineage carry the M6 creative profile. With append
unchecked, an authenticated user could edit the profile, policy or content basis of a copied lineage,
recompute the payload digest, and store a Canvas revision under any cohort. That breaks M8's
profile-isolation claim.

## Decision

1. **Only Canvas revisions come from clients.** The append route refuses every other kind. Spatial and
   Format revisions are server-prepared, and the service already refuses client Spatial revisions.
2. **The lineage must match a server resolution.** Before appending, the route requires the
   revision's lineage to equal the lineage the server resolves now for one indexed episode of the
   project (ADR-0098 resolution v1, ADR-0105 resolution v2). An ambiguous admission set matches no
   episode. A mismatch is `M8_LINEAGE_NOT_SERVER_RESOLVED` (HTTP 409).
3. **Ordering and contract stay the same.** The scope check (project and author) still runs first and
   still answers not-found. The request contract is unchanged, and so is the client, which already
   reads the context before every save.

## Consequences

- A Canvas revision can no longer claim a cohort the server did not resolve.
- When the script or the admission changes between reading the context and saving, the save gets 409
  and the client rereads the context, as it already does after a conflict.
- Router tests now build lineages from a real project and script, not from placeholder digests.

## Rejected

- **Stamping the lineage on the server at append.** It needs the episode in the request, which changes
  the frozen contract (the alternative ADR-0098 already rejected).
- **Keeping append unchecked and filtering later.** No later Canvas authority exists to filter at.

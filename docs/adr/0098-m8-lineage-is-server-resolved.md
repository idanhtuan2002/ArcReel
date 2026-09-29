---
status: accepted
---

# M8 exploration lineage is resolved by the server

An M8 `ExplorationRevision` carries a `LineageBinding`, and its `payload_digest`
covers that lineage. The M8 spec defines the binding's shape but names no source
for its values. No host seam derives a content basis, creative profile or episode
master for an ordinary episode. M8-B B3 therefore stopped with
`M8_BASE_SEAM_CHANGED` (`docs/r2/evidence/R2_M8_B_STOP_2026-09-29.json`). The
sponsor delegated the choice. The evidence is in
`docs/research/2026-09-29-r2-m8b-canvas-lineage-seam.md`.

## Decision

- A read-only route `GET /projects/{project_name}/m8/exploration/context?episode=N`
  returns `{lineage, created_by}`. `lineage` is the `LineageBinding` the server
  resolves for the session user, the project and the episode. `created_by` is the
  session user's id, which append requires as the revision author; the client has
  no other source for it. The client copies both unchanged and never builds them
  itself.
- A read-only route `GET /projects/{project_name}/m8/exploration/candidates/{candidate_id}`
  returns the `CandidateHead` (current revision and CAS version) without any
  revision body, so opening a candidate reads the head first and then one exact
  revision. Without it, the client would have to page through full revision bodies.
- Version 1 of the resolution:
  - `content_basis_digest` is the canonical digest of
    `{"basis_kind": "host_episode_script", "episode": N, "script_digest": "sha256:<hex>"}`,
    where the hex is the SHA-256 of the bytes of the episode's indexed
    `script_file`. An episode without an indexed script, or with a missing script
    file, is not found.
  - `approved_master_id` and `approved_master_digest` are null. No host seam names
    an episode's final master.
  - `creative_profile_id` is `arcreel.host`, `creative_profile_version` is `1`,
    and `policy_digest` is the canonical digest of
    `{"profile_id": "arcreel.host", "profile_version": "1", "rules": []}`.
- The client computes `payload_digest` with a TypeScript port of
  `r2/advanced_creative/digests.py`. A differential test pins the port to the
  Python encoder on shared fixtures. The port rejects values the Python encoder
  rejects, and it also rejects object keys outside the Basic Multilingual Plane,
  so that both key orders agree.
- Append behaviour is unchanged. The server still checks only the project and the
  author, and it still recomputes `payload_digest`. Lineage currentness is checked
  where authority is exercised: at promotion, and in M8-D cohorts.

## Consequences

- An edit to the episode script changes the content basis. The next Canvas save
  carries the new lineage and so a new `payload_digest`, as spec §5 requires. The
  client fetches the lineage when it opens the Canvas and again after a 409.
- Binding an adaptation profile or an episode master later changes only the
  resolver. The route and the client stay the same. Each change is a new
  resolution version recorded in an ADR.
- A Canvas revision cannot be promoted yet (`CanvasCandidate` has no promotable
  artifact). Before Canvas promotion exists, promotion must check lineage
  currentness against this resolver.

## Rejected

- Server-stamped lineage at append. It changes the accepted, frozen request
  contract, and it needs the episode in the request.
- Client-built lineage. It would be forgeable and would carry no meaning.
- A server digest route. It adds a round trip to every autosave, and the
  differential test gives the same guarantee.

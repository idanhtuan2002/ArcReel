# M8-B Canvas lineage seam

Date: 2026-09-29. Base: r2-v2/main `d29667fd`; M8-B worktree `4a064b75` (B0–B2 done).

## Question

An M8-B Canvas save is an M8-A `ExplorationRevision`. The revision must carry a
`LineageBinding` (project, content basis digest, approved master id/digest,
creative profile id/version, policy digest) and a `payload_digest` over canonical
`{contract_version, kind, payload, lineage}`. Where does the Canvas client get
these values?

## Facts (verified at the heads above)

1. The M8-A API (`server/routers/advanced_creative.py`) has five routes: append,
   exact get, history, promotion preview, promote. None returns a lineage.
2. `ExplorationService.append_revision` (`r2/advanced_creative/exploration.py:187`)
   checks only `lineage.project_name` and `created_by`. The store recomputes
   `payload_digest` and rejects a mismatch. It never checks the other lineage
   fields against host state.
3. Promotion recomputes `digest_payload(payload, lineage)`
   (`r2/advanced_creative/promotion.py:119`). A `CanvasCandidate` has no promotable
   artifact yet (`promotable_format`), so no Canvas revision can reach promotion
   in M8-B.
4. The M8 design spec (`2026-09-13-r2-m8-canvas-learning-multiformat-design.md` §5)
   defines the `LineageBinding` shape and says a lineage change changes
   `payload_digest`. It names no source for any lineage field. The M8-A plan and
   ADR-0097 do not either.
5. Host sources that exist:
   - `ContentBasis` appears only on R2 contracts (`ShotSpec`, `R2ArtifactMetadata`).
     Only `scripts/r2/v1_operator.py` and fixture code build one. No frontend code
     and no host route derives a content basis for an ordinary episode.
   - Creative profiles and policy packs exist only in adaptation
     (`adaptation_branches.profile_id/profile_version/policy_pack_digest`,
     `r2/adaptation/profiles.py`). Adaptation screenplays have no episode column,
     so no seam links an episode to a profile.
   - The approved master of an artifact is the M7 master head
     (`MasterHeadSnapshot.candidate_id` and `content_digest`; ADR-0096). M8-A
     promotion already uses those two fields as the master id and digest.
   - The episode script is host authority: `project.json` `episodes[].script_file`.
6. Donor: DramaClaw `useCanvasSync.ts` (b299bfd9) saves `{nodes, edges, viewport,
   metadata}` with no provenance. The editor libraries used for comparison in the
   scale research (React Flow, tldraw) keep a schema version only. No donor
   behaviour covers lineage.
7. The canonical JSON encoder is `r2/advanced_creative/digests.py`. A client float
   is validated to `Decimal(str(float))`, which is the shortest round-trip form.
   JavaScript `String(number)` produces the same shortest digits, so a TypeScript
   encoder can match the Python one. The differences are exponent formatting
   (the encoder must emit fixed notation) and key order for non-BMP keys
   (UTF-16 order versus code-point order).

## Inferences

- The spec assumed that a host lineage seam exists. None does. This is
  `M8_BASE_SEAM_CHANGED` for M8-B B3: the Canvas cannot save without inventing
  lineage values, and the umbrella plan forbids executors from inventing
  architecture.
- Lineage currentness matters where authority is exercised: at promotion (spec
  §5, `M8_PROMOTION_BINDING_STALE`) and in M8-D learning cohorts. At append it is
  a recorded claim. Adding append-time validation would change accepted M8-A
  behaviour, and it would need the episode, which `ExplorationRevision` does not
  carry.

## Options

| Option | What | Assessment |
|---|---|---|
| A. Server-resolved lineage, read-only | A new `GET /projects/{p}/m8/exploration/context?episode=N` returns the `LineageBinding` a server resolver derives from host authority, and the author id append requires. The client sends it unchanged and computes `payload_digest` with a TypeScript port of the canonical encoder, pinned by a differential test against `digests.py`. Append is unchanged. | Additive. No accepted behaviour changes. The server stays the only source of lineage values. **Chosen.** |
| B. Server stamps lineage at append | The client sends no lineage or digest. | Changes the accepted public request contract (`ExplorationRevision` is frozen and requires both). It needs the episode in the request. Rejected. |
| C. Client-built lineage | The client fills placeholder or client-derived values. | Lineage becomes meaningless and forgeable, which contradicts spec §5. Rejected. |
| D. A server digest helper route | The server returns `payload_digest` for a body. | One extra round trip for every autosave, plus the same resolver is still needed. Rejected; the differential test gives the same guarantee. |

## Resolver definition (decided in ADR-0098)

- `content_basis_digest` = `digest_canonical({"basis_kind": "host_episode_script",
  "episode": N, "script_digest": "sha256:<hex of the episode script file bytes>"})`.
  An episode without an indexed script returns 404.
- `approved_master_id` / `approved_master_digest` = both null. The host has no
  "episode final master" slot: Gate C accepts any `target_ref`, and `"FINAL"`
  exists only in `scripts/r2/v1_operator.py:38` and the restore drill. Binding a
  master waits for a host seam that names the episode final (spec §5 allows
  null).
- `creative_profile_id` = `"arcreel.host"`, `creative_profile_version` = `"1"`,
  `policy_digest` = `digest_canonical({"profile_id": "arcreel.host",
  "profile_version": "1", "rules": []})`. Binding an adaptation profile waits for
  an episode→adaptation seam.

## Unknowns

- U1 (resolved): no host seam names an episode's final master. See the null
  binding above.
- U2 (decided): a project without an `episodes[]` entry holding a `script_file`
  for episode N cannot open a Canvas for it; the route returns 404.
- U3 (decided): the TypeScript encoder rejects object keys outside the BMP, so
  both key orders agree; the differential fixture pins it.

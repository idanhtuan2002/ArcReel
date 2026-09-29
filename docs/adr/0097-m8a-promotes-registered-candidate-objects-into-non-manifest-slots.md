---
status: accepted
---

# M8-A promotes an existing M7 candidate object into a non-manifest artifact slot

M8-A task A3 must bridge an `ARTIFACT_SLOT` promotion into the M7 master authority, which
ADR-0096 made the sole master authority. The M8 spec does not say which bytes become the
master when an exploration candidate is promoted. Resolving that at A3 needs files outside the
M8-A owned-file map, which the execution contract treats as `M8_BASE_SEAM_CHANGED`. The sponsor
delegated the choice.

**Facts at `38ef306e`:**

- **What the authority promotes.** The M7 authority promotes only a verified candidate object: a
  `candidate_objects` row whose bytes were written or verified through `prepare_candidate`
  (digest and media probe). `MasterAuthorityUnit.promote_staged` registers a freshly staged host
  version file and commits.
- **The payload kinds:**
  - `FormatCandidate` carries `rendered_artifact_ref`, `rendered_artifact_digest` and
    `execution_id`: a render produced by an M7 execution;
  - `CanvasCandidate` carries only a graph, with no bytes;
  - `SpatialCandidate` targets `PRODUCTION_BINDING`, which is deferred by ADR-0095.
- **Manifest artifacts belong to the host.** Every manifest `EPISODE_VIDEO` master is owned by
  Gate C and must be projected to the file manifest (ADR-0096). `verify_masters` treats any
  database head without a projection as divergence.
- **There must be a current master.** An `ARTIFACT_SLOT` preview must bind the current master's
  id and digest (spec §4), so an M8 promotion replaces an existing master; it never creates the
  first one.

**Decision:**

1. **The ARTIFACT_SLOT adapter** promotes an already registered M7 candidate object. For a
   `FormatCandidate`:
   - `rendered_artifact_ref` is the M7 `candidate_id`;
   - the object's `content_digest` must equal `rendered_artifact_digest`, and a mismatch is
     `m8_promotion_binding_stale`.
2. **Other candidates are unavailable.** A `CanvasCandidate` has no candidate object until the
   M8-B canvas materialization defines one. Until then, its promotion is
   `m8_promotion_target_unavailable`.
3. **M8 targets only non-manifest slots.** A `target_ref` that decodes as a host manifest
   artifact key of any kind is `m8_promotion_target_unavailable`. Manifest artifacts and their
   projection stay with the host flows.
4. **The authority seam gains `MasterAuthorityUnit.promote_registered`.** It promotes an existing
   candidate object through `AtomicPromotionService.promote`, with the caller's commit, so the M8
   authorization, receipt, M7 head, M7 receipt and project event commit once.
   `AtomicPromotionService` is still constructed only in `r2/host_hardening/master_authority.py`.
5. **Master verification is scoped to projected slots.** `verify_masters` compares only database
   heads whose artifact keys decode as `EPISODE_VIDEO` manifest keys, which are the only
   projected ones. Non-manifest M8 slots have no file projection by design.
6. **Identities.** The receipt's `result_master_id` is the new head's candidate id,
   `result_digest` is its content digest, and `result_artifact_ref` is the `target_ref`.
   `expected_target_version` is the head's master version.

## Considered options

- **Promote the canvas graph as JSON bytes.** Rejected. A graph is not media; it would fail the
  media probe; and it would make a planning structure an ApprovedMaster, which ADR-0079 reserves
  for production artifacts.
- **Let M8 write manifest episode-video slots and project them.** Rejected. It would duplicate
  the Gate C staging and projection path, a second writer for host-owned artifacts.
- **Allow a first master without a bound master identity.** Rejected. That relaxes the §4
  contract.

## Consequences

- **What M8-A delivers.** It delivers the complete exploration authority and preview-bound
  promotion. `FormatCandidate` is the kind that can reach a master today, into an M8-owned slot
  whose first master comes from an M7 promotion.
- **Scope.** Contract amendment 4 adds the two host files and their tests to the M8-A scope.

## Concurrency model (written before A3 code, per amendment 5)

**Actors on M8 rows and M8 slots:**

- **Append a revision.** It writes `m8_candidate_heads` and `m8_candidate_revisions`, plus a
  command receipt.
- **Create a preview.** It reads the candidate revision and the slot's current master head,
  then writes `m8_promotion_previews` and a command receipt.
- **Promote.** It writes `m8_promotion_authorizations` and `m8_promotion_receipts`, plus a
  command receipt. It also writes, through the M7 authority on the same session, the slot's
  `master_authorities` row and `master_head_versions`, the M7 promotion receipt and the
  project event.
- **Other host writers** of a slot's `master_authorities` row: Gate C phase 1 and phase 2 touch
  only manifest `EPISODE_VIDEO` keys, and Gate D's multi-row lock covers only the heads that
  `verify_masters` returns, which are also manifest `EPISODE_VIDEO` keys. Rule 3 below keeps an
  M8 slot from ever being one of those keys, so no host writer shares a row with M8.

**Invariants:**

1. **Revisions.** A candidate's revisions are append-only, and its head advances by
   compare-and-set only.
2. **Promotion.** A promotion commits only if, inside its own transaction and under its locks,
   all of these still hold:
   - the preview is unexpired;
   - the preview digest equals the authorization's;
   - the candidate head version is the expected one;
   - the revision payload digest is the previewed one;
   - the slot's master head (version, candidate id, content digest) is the previewed one;
   - the promoted candidate object exists with the payload's `rendered_artifact_digest`.
3. **Target slots.** An M8 target slot is never a manifest artifact key.
4. **One transaction per operation.** An operation commits every row it writes (M8 and M7) in
   one transaction or none of them. An exact replay returns the stored result before any
   currentness check.

**Lock protocol.** This is the normative spec §6 order, and it follows the V2-02b rule that a
write depending on a head holds that head's lock:

1. the command key (a transaction advisory lock on PostgreSQL);
2. the candidate head (`FOR UPDATE`);
3. the preview (`FOR UPDATE`), promote only;
4. the slot's `master_authorities` row (a no-op `UPDATE` on an existing row), promote only.
   A preview does not lock the slot: it reads the head, and the promotion revalidates it
   under the lock.

**Why there is no deadlock:**

- Every M8 operation takes its locks in that fixed order and holds them to one commit.
- An M8 slot's first head is written by an M7 promotion, so M7 writers do share M8 slot
  rows. Since V2-02c (amendment 6), every M7 promotion runs its pointer compare-and-set
  before it appends the head version. Every same-slot writer (Gate C/D, backfill, M8) therefore
  takes the `master_authorities` row before any `master_head_versions` row, so no writer waits
  on another's uncommitted history row while holding the row that one needs.
- Different candidates and different slots never share a lock.

**Why there are no stale writes:**

- Every write that depends on the slot head (the promotion) runs after the slot row lock and
  re-reads the head inside it.
- A preview may go stale after it is written, but the promotion refuses a stale preview with
  `m8_promotion_binding_stale`.

**SQLite.** It serializes all writers on the database write lock, so the order above cannot
cycle there either. The concurrency tests run on PostgreSQL.

## Review round 1 resolutions (Codex, `dc13cc93..21821568`)

The rules below were written before the fixes. Each has a test that fails without the fix.

1. **The promotion recomputes the payload digest.** Under the locks, the promotion recomputes
   `digest_payload(payload, lineage)` from the stored revision. It must equal both the stored
   `payload_digest` and the preview's `candidate_payload_digest`. A stored row whose bytes
   changed while its digest did not is refused with `m8_promotion_binding_stale`.
2. **One lock order for every same-slot writer.** This is covered by V2-02c and the deadlock
   argument above.
3. **Candidate identity is scoped.** The spec requires that "all public reads and writes scope
   by `(user_id, project_name)`; foreign and unknown IDs are indistinguishable". The plan's
   global `candidate_id` primary key breaks this for writes: a genesis that reuses a foreign ID
   would return 409 where an unknown ID returns 200. The spec prevails over the plan's
   persistence map. The candidate head and revision keys are
   `(user_id, project_name, candidate_id[, revision])`. The previews and receipts that
   reference them use the same composite key. The same ID in two scopes names two
   independent candidates.
4. **Evidence survives user deletion.** The plan says "Do not add cascade deletion from any
   evidence table". Every M8 table's `users.id` foreign key is `ON DELETE RESTRICT`, not the
   `UserOwnedMixin` default of `CASCADE`.
5. **The rendered object must be registered for the target slot.** Under the slot lock, the
   promotion requires the candidate object's `artifact_key` to equal the target slot. If it does
   not, the promotion is refused with `m8_promotion_binding_stale` before M7 is called. The
   slot authority also translates the M7 promotion conflicts it can still raise into M8 errors,
   so no validly shaped request reaches an unhandled server error.

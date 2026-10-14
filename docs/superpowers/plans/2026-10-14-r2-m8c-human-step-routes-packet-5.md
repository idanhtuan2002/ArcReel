# M8-C packet 5: application routes for the human steps

**Basis:**
- [ADR-0102](../../adr/0102-production-binding-is-a-versioned-production-authority.md) and [ADR-0103](../../adr/0103-showrunner-grants-and-spatial-review-custody.md), both accepted on 2026-10-13. Activation of ADR-0103 is still pending.
- The [binding authority spec](../specs/2026-09-30-r2-m8c-binding-authority-design.md), §"typed spatial promotion".
- The [binding creation spec](../specs/2026-10-05-r2-m8c-location-binding-create-design.md).
- The [grant and review evidence spec](../specs/2026-10-06-r2-m8c-grant-and-review-evidence-design.md).
- The vertical acceptance record (2026-10-14) in `docs/r2/evidence/R2_M8C_FRAME_CUSTODY_HANDOFF.md`, finding F2.

## Facts

- **Services exist; routes do not.** Binding creation, the review session, the V2 pair decision and the typed spatial promotion are implemented and tested as services, and an offline chain through them passes (`test_m8c_vertical_acceptance.py`). No HTTP route reaches any of them.
- **The app wiring is latent and wrong.** When governance is activated, `server/app.py` puts the review, pair reader and pair decision services on `app.state`, built with `projects_root` as `project_dir`. `SpatialFrameReader` resolves `<project_dir>/spatial/frames/<id>.png`, so a real project's frames would not be found. Nothing reads those `app.state` services, and `SpatialPromotionService` is never built.
- **The authentication rule is already decided.** ADR-0103 §3 requires an interactive session JWT plus the current grant for the frame and decision routes, and denies API keys and anonymous mode. `server/auth.py` already provides `InteractiveUser` (`get_current_interactive_user`), which enforces exactly that JWT rule. The services check the grant themselves under their locks.
- **The promotion body is already specified.** The binding authority spec names the request fields `candidate_id`, `candidate_revision`, the binding, `expected_binding_version`, an ordered `selected_assertion_ids` and `command_id`. The client sends no relation text and no digest.
  - The implemented service identifies the binding by the Shot `target_id` (one LOCATION binding per target) instead of `binding_id`. The route follows the service.
- **Existing precedent.** The generic M8 promotion route (`advanced_creative.py`) accepts a client-built `PromotionAuthorization` with `CurrentUser`. The binding-target variant of that generic route stays unavailable, as the spec requires.

## Decisions

1. **One new router, `server/routers/spatial_review.py`,** registered like `spatial.router` with `/api/v1`, `get_current_user` and the migration guard. Every route is under `/projects/{project_name}/m8/spatial/` and authenticates with `InteractiveUser`. The scope (`user_id`, `project_name`, `principal`) always comes from the path and the session, never from the body.
2. **Per-project services.** Each request builds its service with the project's own directory, the shared session factory and `app.state.governance_grants`. The `app.state` service instances with `projects_root` are removed.
3. **Deny by default.** Without an activated governance grant reader, the review, decision and promotion routes return 503 `m8_spatial_review_unavailable`. Binding creation does not use a grant and stays available to an interactive session.
4. **Routes:**

   | Route | Body | Result |
   |---|---|---|
   | `POST bindings` | `command_id`, `expected_target_ref`, `ordered_frame_receipts` | `BindingCreateResultV1` |
   | `POST review-sessions` | `target_id` | `ReviewSnapshotV1` |
   | `GET review-sessions/{session_id}/frames/{role}` | none | the PNG bytes |
   | `POST review-sessions/{session_id}/acknowledgments` | `attempt_id`, `role`, `png_digest`, `decoded` | `ReviewAcknowledgmentV1` |
   | `POST pair-decisions` | the V2 pair command without scope and without `review_evidence_digest` | `PairDecisionResultV2` |
   | `POST promotion-previews` | `candidate_id`, `candidate_revision`, `target_id`, `expected_binding_version`, `selected_assertion_ids`, `command_id` | `SpatialPromotionPreviewV2` and its V2 `preview_digest` |
   | `POST promotions` | `preview_id`, `preview_digest`, `command_id`, `expected_candidate_head_version` | `SpatialPromotionReceiptV2` |

   - **Frame route:** the PNG is served with `Cache-Control: no-store` and the delivery attempt ID and PNG digest in response headers, as the review service's contract says.
   - **Pair decisions:** the server reads `review_evidence_digest` from the completed review session it stored; the decision service then re-verifies it under its locks. The client still echoes every `expected_*` field and the view refs it was shown, so a change between review and decision fails as a conflict.
   - **Promotions:** the server mints the `PromotionAuthorization` from the interactive session (`actor_id` and `actor_scope` set to the session user, `decision=APPROVE`, `authorized_at` set to the request time). It accepts no client-supplied actor.
5. **Error mapping:**
   - A `PermissionError` (grant unavailable, pair authorization denied) returns 403.
   - Review session integrity errors return 409 `m8_spatial_review_session_unavailable`.
   - Source, binding and pair conflicts return 409 `m8_spatial_source_conflict`.
   - An M8 not-found error returns 404; any other M8 error returns 409 with its code.
   - An invalid body or command returns 422.
6. **Not here:**
   - The frontend UI.
   - F1 (pairs whose two frames have identical content).
   - A separate grant check in the promotion route. A new promotion already re-checks the reviewer's current grant through the current pair reader; only an exact replay skips currentness, as the binding spec's replay rule allows (corrected 2026-10-14 after independent review).
   - Live activation of ADR-0103.

## Tests (`tests/integration/server/routers/test_spatial_review_routes.py`)

- **Full human path through the routes:** binding → session → fetch both frames → acknowledge both → APPROVE → execution (service, fake vision) → preview → promote. The resulting snapshot carries the set.
- **Authentication:** an API key or no token gets 401 on every route; a missing governance grant reader gets 503.
- **Body scope:** a body carrying `user_id`, `principal`, `actor_id` or `review_evidence_digest` gets 422.
- **Frame route:** the bytes hash to the snapshot's digest and the response sets `no-store`.
- **Conflicts:**
  - a decision after the binding changed gets 409;
  - a promotion naming a changed preview digest gets 409;
  - an exact replay returns the same receipt.
- **App wiring:** an activated app builds no `projects_root`-scoped services.

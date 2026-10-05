# M8-C first LOCATION binding authority implementation

**Status:** execution plan after the fixed v1 digest packet at `b6162c23`. The design remains proposed until the database writer, persisted reader and PostgreSQL races pass review. No route or production activation belongs to this plan.

## 1. Scoped persistence schema

Add one revision after `8c8c4a0e0001` and matching ORM models for `production_binding_heads`, `production_binding_versions`, and `production_binding_commands`. The head key is `(user_id, project_name, binding_id)` and carries a nullable genesis `(current_version, current_envelope_digest)` pair. An immutable version has the same scope/key, `binding_version`, v1 body JSON/digest, envelope JSON/digest, exact Shot and Scene version keys/digests, the two frame receipt IDs, and creation time. Foreign keys connect version to head, exact existing target versions and scoped frame receipts; head points to the current version. Check constraints require positive versions and a complete current pair. The command key is `(user_id, project_name, principal, command_id)` and stores command digest plus typed result JSON/digest. Do not let the ORM or migration create a binding from only a digest column.

Test schema parity, key/FK/check constraints and upgrade→downgrade→upgrade on disposable SQLite and PostgreSQL. Update only migration tests whose pinned head/table list changes. A schema gate does not accept the writer.

## 2. Repository read, append and CAS

The repository operates only in the caller's `AsyncSession`. It claims a missing head by scoped insert-if-absent then locked reread, rejecting a committed genesis row. It recomputes body, each claim, envelope and command-result digests from typed stored JSON; checks scalar columns, exact scope, latest-version linkage, Scene/Shot refs and two receipt identities; and never treats stored digest columns as authority by themselves. Append requires a locked head and expected predecessor; advance checks the new row and expected pair. The command row is inserted last. Tests mutate stored JSON while copying digest columns, create unheaded versions, change scope, and inject a failure after append to prove rollback.

## 3. Server-internal create command

In one transaction: canonicalize the trusted command; read any command row for integrity only; take scoped receipt-parent hints; verify current full admission → Scene → Shot with the existing target consumer; claim/lock the binding head; lock sorted distinct M7 parent rows with `lock_current_master_rows`; re-read both receipts through `SpatialFrameReader.read_locked`; derive body, claims and envelope from verified rows and bytes; append, CAS, record command; commit. Reject duplicate frame IDs or parent keys, missing Scene `location_ref`, stale target/receipt/master, or a changed hint. A duplicate command loser rolls back tentative rows, then verifies the winner in a fresh transaction. Exact replay proves current target and source identity before returning the old receipt.

PostgreSQL tests must observe backend PIDs and blockers for re-admission, target and M7 advancement; assert bound parameters and the actual admission → Scene → Shot → binding → sorted M7 order. Two first writers, same command changed input, different commands for one logical binding and late failure all need distinct cases.

## 4. Exact current snapshot and readiness boundary

The snapshot reader starts from current target/admission authority and rechecks the binding head/version/body/claims plus current parent media bytes under M7 locks. It emits only the exact sorted v1 snapshot digest. A valid pair of source frames is still unavailable to live spatial READY/promotion until a separate human pair decision. Test target, binding and parent advancement, altered JSON with copied digest columns, and a legitimate newer binding version separately from corruption.

## 5. Acceptance gate

Run relevant tests first, then the affected backend static/test gates from `CONTRIBUTING.md`, PostgreSQL migration and forced-interleaving selection, test audit, `git diff --check`, clean-HEAD check and one bounded independent review. Record exact HEAD and outputs in the M8-C handoff. Keep the earlier repository-wide backend failures classified as unresolved release work; do not claim overall M8-C acceptance from this packet.

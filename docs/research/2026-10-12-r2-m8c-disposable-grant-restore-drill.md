# M8-C disposable grant rollback restore drill

Status: bounded positive/negative evidence at clean `40496a7de09351be23e986de764cd31cdb83ac7d`, 2026-10-12. This is a local PostgreSQL/algorithm drill, not startup quarantine, production recovery or acceptance of operator custody.

## Setup and exact schedule

A fresh auto-removing `postgres:16` container (`arcreel-m8c-restore-drill-20261012`) exposed one Docker-assigned localhost port, `32782`. The source database `test` was migrated with `DATABASE_URL=postgresql+asyncpg://test:test@127.0.0.1:32782/test ...python -m alembic upgrade head` to `911c4a0e0001`. A temporary host directory outside the database held `grant-checkpoint.json`; an ephemeral Python drill script under `/tmp` used only test Ed25519 private keys derived from `bytes(range(32))` for the grant event and `bytes(range(32, 64))` for the checkpoint. Those are test vectors, not operator keys. The script and directory were removed after the drill.

The Python phases used the committed `GovernanceGrantImporter`, `GovernanceGrantRecoveryScanner`, `CheckpointedShowrunnerGrantReader`, and `GovernanceCheckpointFile` APIs:

1. Insert test user `u1`; import a signed `ISSUE` at sequence 1 for exact scope `(u1, show-a, reviewer-a)`; atomically replace the current pathname with a signed checkpoint at sequence 1 naming that exact grant head. Full scan passed.
2. Capture the **pre-REVOKE** source database inside the disposable container with `pg_dump -U test -d test -Fc -f /tmp/pre_revoke.dump`.
3. Import a signed `REVOKE` at sequence 2; atomically replace the external current pathname with a signed checkpoint at sequence 2 whose `previous_checkpoint_digest` equals checkpoint 1's canonical signed-body digest. Full scan passed.
4. Create a second database using `createdb -U test restored`, then run `pg_restore -U test -d restored --no-owner --no-privileges /tmp/pre_revoke.dump`. Keep the post-REVOKE checkpoint file unchanged outside both databases.
5. Point the scanner and current reader at the restored database while they load the same post-REVOKE checkpoint. The scanner denied the exact head mismatch, and the current reader denied the resurrected ISSUE even though it was locally signed and active in the restored database.

Observed output:

```text
pre_revoke_issue_scan=pass
post_revoke_scan=pass
restored_old_db_scan=denied
restored_old_db_current_grant=denied
```

The container was stopped/auto-removed and a later filtered `docker ps -a` returned no match. The ephemeral script was deleted. This schedule is reproducible from the committed APIs and the listed `pg_dump`/`pg_restore` commands, but the exact ephemeral Python script is not retained as a test artifact. A future automated drill should preserve a versioned fixture/runner and verify the same predicates under the accepted deployment package.

## Limits

The drill did not start the application, workers or production Compose stack; it did not test failure before readiness, registry/image digest enrollment, operator high-water archive, key rotation, schema preflight, multi-process publication during a transaction, a post-REVOKE restored database, or a real operator-signed checkpoint. It demonstrates that these internal scanner/reader implementations reject one actual PostgreSQL rollback while the newer signed checkpoint remains external. It cannot support production APPROVE/READY or recovery cutover by itself.

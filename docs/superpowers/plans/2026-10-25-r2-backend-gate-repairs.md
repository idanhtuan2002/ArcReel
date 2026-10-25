# V2 baseline test and inventory reconciliation

Base: e2e7785a2f47b5ca0e1853a5fd56a71842d67b1a. Pure extraction source remains unchanged and not integrated into M10.

The released V2 baseline reproduces three fitness/evidence failures. Source tracing establishes that story approval delegates to ManuscriptCommitter, not the manifest approval; the accepted 2026-10-18 story-release amendment explicitly composes Canon genesis through CanonTransactionService. The source-derived inventory contains the Gemini story route but the offline inventory omits it. No new qualification is inferred.

Bounded work, with no production runtime changes:

1. Reconcile the Canon fitness test with exactly the existing story composition root. Permit only its factory import, require the factory call to remain an argument of CanonTransactionService, keep every other authority symbol forbidden, add refusal examples.
2. Distinguish exactly the two existing story approve delegations from manifest approve calls. A known story file is not a blanket exception: new host imports and additional approve receivers still fail the sensor. Add negative fixtures.
3. Record story:gemini-aistudio with its existing adapter version and REFUSED_UNTIL_QUALIFIED disposition in the offline route inventory. Never create a live qualification or enable a provider.
4. Repair scheduler lifecycle observation: use existing public lease APIs to seed an expired attempt, and observe completion of a real scan via a test subclass/event. Do not stop on the intentionally durable SUBMIT_OUTCOME_UNKNOWN intermediate state. No runtime scheduler change or real-time sleep.
5. Run the affected complete test files and relevant story commit/grant/route-release regressions; audit tests and static gates. One independent critical review of the authority sensors and evidence update. Preserve the failed original run.
6. Finish only the ten explicitly unfinished backend nodes separately, with unchanged runtime sources. Record combined coverage honestly; do not call it a fresh full-suite pass at a new HEAD. No files edited while a Git-cleanliness test is running.

Owned paths: this plan; tests/unit/r2/narrative/test_canon_architecture_boundaries.py; tests/unit/r2/test_master_authority_boundaries.py; tests/integration/server/services/test_execution_recovery_scheduler.py; docs/r2/evidence/R2_V1X_PAID_ROUTE_INVENTORY_2026-09-29.json; eventual exact verification/handoff evidence.

Research basis: live commit/service/router source, r2/host_hardening/execution.py reconcile_expired/reconcile, the existing qualified-route version/gate, docs/superpowers/plans/2026-10-18-r2-v2-story-release-amendment.md touchpoint2 item7. This is consistency maintenance of accepted implementations; no new owner, provider, adapter, protocol, or architecture is introduced. No donor implementation is needed for AST sensors or asyncio.Event already used by the scheduler.

## Independent review and one repair

Candidate e668017d51c5916bbeadbce33f7a7120c3a7cc36 was independently reviewed by /root/backend_fitness_repair_review and received FAIL: P1 module-qualified Canon authority imports escaped the sensor; P2 story approve exceptions lacked exact count/scope/argument fingerprints. Production wiring was verified sound. These findings are not erased by the repair.

The one repair adds module/qualified-attribute authority refusals, exact async/class containing scopes, one approve occurrence, no positional/expanded/extra kwargs, and exact principal/manifest argument expressions. RED:14 failed/29 passed on the reported gaps. Final focused gate:52 passed/1warning; type0errors0warnings; test audit0violations. Final repair verification by the independent reviewer remains pending.

The ten previously unfinished backend nodes completed:10 passed/2warnings in2815.65s. Prior consumer regressions:48 passed; clean M7 scope:1passed. Runtime lib/r2/server sources remain byte-identical to the pure-extraction checkpoint. This is combined coverage, not a fresh full-suite run at the repair HEAD. No further render rerun is justified without a new runtime-source change or unresolved media failure.

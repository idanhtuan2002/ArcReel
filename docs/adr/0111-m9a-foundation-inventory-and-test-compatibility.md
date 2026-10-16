---
status: accepted
---

# M9-A records a bounded sponsor amendment for foundation inventory and test compatibility

On 2026-10-16 the sponsor replied `duyet` to the concrete parity and test-compatibility proposals presented at clean repair HEAD `211363f69771225df0b281931f1e0992e93ce09a`. Both exact proposals and the test-only patch are retained under `docs/r2/evidence/amendments/2026-10-16-m9a-*`; their original PROPOSED labels preserve what was approved. `R2_M9_A_SPONSOR_AMENDMENT.json` records this subsequent approval.

For M9-A only, `FOUNDATION_INVENTORY_VERIFIED` may replace the runtime parity report gate while no donor runtime port exists. All nine selected blobs must match the original accepted baseline pins and hashes. Candidate evidence must explicitly record `donor_runtime_executed=false` and `runtime_parity_claimed=false`, classify every selected surface as deferred runtime, and retain passing verifier regressions. No report may label absent donor execution PASS. The foundation exemption is pinned to the current native runtime bytes; a later runtime change invalidates this exemption. Every later packet that consumes a donor behavior must still execute its pinned offline harness and prove all applicable parity dimensions at its exact HEAD.

The exact thirteen-path test compatibility patch is authorized: twelve stale migration test expectations and one test package initializer. Broader PostgreSQL/event-loop/scheduler failures are authorized for bounded diagnosis; this amendment neither waives those failures nor grants arbitrary production edits. The original accepted ADR/spec/plan/contract/baseline bytes stay unchanged. The verifier must bind this amendment's exact Git commit and bytes before extending the owned map.

All other M9-A gates remain required, including PostgreSQL concurrency/custody/rollback, auth/i18n, static checks, complete affected tests and truthful review coverage. The sponsor's separate instruction limits review repetition; it creates no reviewer PASS and no independent acceptance. Final residual review remains R1 FIXED, R2/R3 PARTIAL because final-source inspection was incomplete. No new review cycle is authorized automatically.

This amendment permits candidate evidence only. It does not accept M9-A, release B-F, authorize push, provider activation or a production migration.

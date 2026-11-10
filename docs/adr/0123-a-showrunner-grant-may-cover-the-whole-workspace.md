---
status: accepted
---

# A Showrunner grant may cover the whole workspace

Decided 2026-11-10 with the sponsor (one ceremony for every current and future project; thousands of projects). Research: [workspace grants and autopilot](../research/2026-11-10-r2-workspace-grants-and-autopilot.md) §1–2, option A3. Amends [ADR-0103](0103-showrunner-grants-and-spatial-review-custody.md) §1 (grants were per project only).

1. **A second signed event kind.** `governance.showrunner_grant_event.v2` has the v1 fields; its `project_name` is the sentinel `@workspace`, which a v2 event must carry and a v1 event must not. The schema id is part of what is signed, so a v2 signature is never read as a v1 grant or the reverse. v1 events, checkpoints and stored digests keep their bytes.
2. **Stored as one more chain.** A v2 chain lives in the existing grant ledger under the key `@workspace`, which no project can be named (`PROJECT_NAME_PATTERN`); the reader refuses a project scope starting with `@`, so nothing selects the workspace chain by name. Scopes are ordered by code point in Python before export and scan, since the database collation may order `@` differently from the signed checkpoint.
3. **One resolution, in the reader.** For a project: its own chain's current ISSUE wins; an explicit per-project REVOKE denies (it is never overridden by the workspace); a project with no chain or an expired grant falls back to the workspace chain's current ISSUE. Heads are locked exact first, then workspace. Every caller of the reader is covered by this one change. A replay's historical ISSUE reference is looked up in the chains the resolution consulted.
4. **The checkpoint covers both chains consulted.** The signed checkpoint must match the exact chain's head (or both be absent) and the workspace head; deleting a per-project REVOKE from the database therefore cannot fall through to the workspace grant.
5. **Ceremony.** `sign-event --workspace` (exclusive with `--project`), then import, next body, offline checkpoint signature and publish as today. Renewal is REVOKE then ISSUE, as for project grants.
6. **Deployment order.** The image that reads v2 ships (app and attestor) and is approved before the first v2 event is imported. After that, an image that cannot read v2 refuses governance for every project; the rollback runbook says so.

Risk accepted by the sponsor: one signed workspace event authorizes every project, so a mis-signed event or a leaked grant key is workspace-wide; expiries stay short and the ceremony is rehearsed with throwaway keys before production.

Projects carry no owner of their own: "every project of the user" is every project in the deployment's projects root, which is the whole workspace in this single-operator deployment; a deployment with several accounts would need projects bound to users first. Readers lock heads in shared mode (an import still waits for them), project before workspace; the exporter and recovery scanner lock in the same order and sort by code point only what they compare and sign.

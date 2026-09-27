---
status: accepted
---

# V1 H6 uses an offline backup fence with credential exclusion; V1 H7 exports spans over env-configured OTLP

The sponsor decided on 2026-09-27 to narrow the H6/H7 mechanisms for the bounded
V1 (ADR-0089) within ADR-0078's `BackupSet` authority.

**Offline backup fence.** A V1 backup set is captured only while the operator has
stopped the application and generation worker. Before `pg_dump` and the media
copy, capture fails closed unless it can prove that no other client session is
connected to the application database and that no Task is `queued`, `running`
or `cancelling`. The same checks run again after the copy, and any change
rejects the set. This replaces the draft's online project-lifecycle CAS fence,
the writer-by-writer fence inventory and its PostgreSQL race tests for V1. The
trade-off is a few minutes of planned downtime per backup.

**Credential exclusion.** The database dump excludes the data of
credential-bearing tables. Their schema is still captured. The manifest records
which tables were excluded. After a restore the operator re-enters provider
credentials, and the runbook documents this step. V1 therefore has no signed
custody receipt, KEK or crypto profile, and no dual-authorized disposal. A
backup set is still sensitive: it holds project content. It is not described
as secret-free.

**OTLP export over environment configuration.** Production spans are exported
through the OpenTelemetry OTLP/HTTP exporter only when the standard
`OTEL_EXPORTER_OTLP_ENDPOINT` (or `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`) is set.
When it is unset, no exporter is installed and correlation relies on the durable
IDs persisted in the database. The source-side H7 allowlist remains the redaction authority;
collector-side redaction is only defence in depth.

**Durable correlation columns.** Following the
[chain-mapping research](../research/2026-09-27-r2-v1-h7-correlation-chain-mapping.md),
the sponsor chose persisted joins over log-only joins. A per-entry `request_id`
is minted at the HTTP or agent entry and stored in a nullable `tasks.request_id`.
Usage rows gain a nullable `api_calls.task_id`. Version metadata records the
`task_id` that produced it. In V1 the chain's `candidate_id` / `master_version`
are the ArcReel version record and its selected version, because the M7
candidate/promotion store has no production caller. `method_decision_id` stays
an allowed attribute that is absent on every V1 path: no MethodDecision reaches
the Host today, and none is fabricated.

Online (zero-downtime) capture, PITR, encrypted custody and automated
maintenance mode remain possible later profiles. They are not V1 obligations.

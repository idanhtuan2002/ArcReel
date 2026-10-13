# Spatial adapter offline verification (`gemini-generate-spatial@host-spatial-v1`)

**Sponsor approval:** on 2026-10-13 the sponsor approved this adapter-level status ("chap nhan, hay hoan thanh cac phan bi chan"). The implementing agent prepared the evidence. The sponsor authorized the status change.

This file is the ADR-0091 F1 adapter-level evidence behind the profile's `OFFLINE_VERIFIED` status in `r2/provider_capabilities/registry.json`. The status covers the shipped adapter only.

The route level is a deployment record. The operator runs a canary on the exact Gemini text route, model and configuration:

```
uv run python -m scripts.r2.qualify_route --provider gemini-aistudio --media text --model <model>
```

When the spatial router assembles the vision model, `assemble_backend` enforces that record through `require_paid_route`.

## Release-mode gate

In a release deployment, `SpatialExecutionService._require_enabled_route` refuses the route unless the profile's status is `OFFLINE_VERIFIED` or better. Two tests cover both outcomes:

- `test_release_mode_refuses_an_unverified_spatial_adapter_before_the_provider`
- `test_release_mode_runs_an_offline_verified_spatial_adapter`

## R2_05 §7 qualification profile

All tests below are in `tests/integration/server/routers/`. Short names: `exec` is `test_spatial_execution.py`; `route` is `test_spatial_route.py`.

| Dimension | Spatial route behaviour | Offline evidence |
|---|---|---|
| Submit | One M7 attempt. It records `ACCEPTED`, then `SUCCEEDED` in the same transaction as the evidence and the revision. | exec `test_execution_appends_one_revision_with_exact_evidence`; route `test_frames_then_execution_append_one_revision_and_replay_is_identical` |
| Status/poll | Not applicable: the call is synchronous and `supports_poll=false`. | Capability profile |
| Restart resume | An `ACCEPTED` attempt without evidence fails closed and is never resubmitted (C2 spec §7, R4). An exact replay makes no second call. | exec `test_evidence_write_failure_after_the_revision_rolls_back_both`, `test_exact_replay_returns_head_without_a_second_call_and_changed_body_conflicts` |
| Cancellation | Not applicable: `supports_cancel=false`. | Capability profile |
| Rate limiting | Inherited from `GeminiTextBackend`. It retries only explicit 429/5xx statuses and connect-phase errors where the request was certainly not sent (ADR-0078). | `tests/unit/lib/video_backends/test_paid_sdk_submit_retry.py` (the shared `should_retry_paid_sdk_submit`). No spatial-specific test. |
| Cost capture | The call goes through `TextGenerator`. The ledger records it for the command user and binds it to the M7 `execution_id`. In release mode the ledger reserves budget before the call. | exec `test_the_ledger_records_the_vision_call_bound_to_its_execution` |
| Reference semantics | Inputs are exact frame receipts, rehashed on read. A stale, identical, unknown or advancing source writes nothing. | exec `test_stale_or_identical_sources_deny_before_the_provider`, `test_source_advance_during_the_call_rolls_back_everything`; route `test_unknown_or_repeated_frames_write_nothing` |
| First/last frame | Not applicable to image analysis. | — |
| Error redaction | API responses carry only i18n keys (`m8_spatial_*`). `str(exc)` goes only to logs, per the `lib/api_errors.py` contract. | route tests check status codes. No spatial-specific redaction test. |
| Timeout/retry | A definite failure ends as `FAILED_BEFORE_ACCEPTANCE`; an ambiguous one ends as `SUBMIT_OUTCOME_UNKNOWN`. Neither is retried, and neither creates a revision. | exec `test_provider_failure_creates_no_revision` |
| Capability metadata | Registered in `SPATIAL_SUBMIT_FAMILIES`. The entry digest is verified on load. | `tests/unit/r2/host_hardening/test_provider_capabilities.py`, route inventory tests |

Also covered in exec:
- Unusable model output (malformed, prose-wrapped, wrong-schema, partial, missing spans): `test_unusable_model_output_creates_no_revision`.
- Concurrent identical commands on PostgreSQL: `test_pg_concurrent_identical_commands_write_one_revision`.
- Head CAS conflict: `test_candidate_head_conflict_rolls_back_the_evidence`.

## Limits

- No live provider call backs this status. The live smoke run is a separate operator step: `scripts/r2/spatial_live_smoke.py`.
- Rate limiting and error redaction rely on shared host mechanisms and have no spatial-specific test.
- The implementing agent prepared the evidence; there was no independent review.

"""Pure probe service projections: scoped M7 identities and an observation bound to the exact result."""

from __future__ import annotations

from r2.quality.ports import ProbeRequest, validate_probe_result_binding
from server.services import quality_probes as service
from tests.unit.r2.quality.test_probes import probe_request_data, recipe_config


def request(**changes: object) -> ProbeRequest:
    config = recipe_config("DECODE")
    data = probe_request_data(config) | changes
    return ProbeRequest.model_validate(data)


def test_task_identity_is_bounded_and_scoped_to_the_full_command_key() -> None:
    first = service.probe_task_id(request())
    assert first.startswith("m10-probe:")
    assert len(first) == len("m10-probe:") + 64
    assert first == service.probe_task_id(request())
    assert first != service.probe_task_id(request(execution_ref="other"))
    assert first != service.probe_task_id(request(actor_id="other-actor"))


def test_route_and_provider_request_carry_only_host_identities() -> None:
    config = recipe_config("DECODE")
    route = service.probe_route(config)
    assert (route.provider_id, route.endpoint_id, route.adapter_version) == (
        "local-ffmpeg",
        "quality-probe",
        "host-quality-v1",
    )
    assert route.capability_profile_ref == "local-ffmpeg-quality-probe@host-quality-v1"
    provider = service.probe_provider_request(
        request(), config, catalog_digest="sha256:" + "a" * 64, input_digests=("sha256:" + "b" * 64,)
    )
    assert provider.host_task_ref == service.probe_task_id(request())
    assert set(provider.payload) == {
        "schema",
        "request_digest",
        "config_digest",
        "catalog_digest",
        "tool_identity_digest",
        "input_digests",
    }


def test_observation_binds_request_placement_and_exact_result_digests() -> None:
    from datetime import UTC, datetime

    from lib.db.repositories.quality_probes import StoredProbeInvocation
    from r2.quality.probes import execution_result_digest, measurement_digest
    from tests.unit.r2.quality.test_probes import result_data

    config = recipe_config("DECODE")
    probe = ProbeRequest.model_validate(probe_request_data(config))
    from r2.quality.probes import ProbeExecutionResult

    body = result_data()
    result = ProbeExecutionResult.model_validate(body)
    invocation = StoredProbeInvocation(
        request=probe,
        request_digest=body["request_digest"],
        execution_id="execution",
        task_id=service.probe_task_id(probe),
        observation_id="018f0000-0000-7000-8000-000000000001",
        route=service.probe_route(config),
        provider_request=service.probe_provider_request(
            probe, config, catalog_digest="sha256:" + "a" * 64, input_digests=result.measurement.input_digests
        ),
        config_digest=probe.rule.config_digest,
        catalog_digest="sha256:" + "a" * 64,
        tool_identity_digest=result.measurement.tool_identity_digest,
        input_digests=result.measurement.input_digests,
        prepared_at=datetime(2026, 10, 28, tzinfo=UTC),
    )
    observation = service.build_observation(invocation, result, observed_at=datetime(2026, 10, 28, tzinfo=UTC))
    assert validate_probe_result_binding(probe, observation) == observation
    assert observation.probe_receipt_ref == "execution"
    assert observation.probe_receipt_digest == execution_result_digest(result)
    assert observation.measurement_digest == measurement_digest(result.measurement)
    assert observation.status.value == result.measurement.status
    assert len(observation.findings) == len(result.measurement.findings)
    assert observation.interval_evidence_digest is None

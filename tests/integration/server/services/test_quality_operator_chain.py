"""The M10-C server-built requests drive the accepted A3-A6 services to a PASS disposition, unchanged."""

from __future__ import annotations

import os
from datetime import UTC, datetime

from r2.quality.host_catalog import HOST_CATALOG
from r2.quality.runs import run_digest
from server import auth
from server.services.quality_dispositions import DispositionCustodian, DispositionService, quality_readiness
from server.services.quality_probes import QualityProbeService
from server.services.quality_profile_custodian import InteractiveProfilePublicationCustodian
from server.services.quality_profiles import ProfilePublicationService
from server.services.quality_requests import (
    RUBRIC_CRITERIA,
    completion_request,
    disposition_request,
    probe_request,
    publication_request,
    review_request,
)
from server.services.quality_runs import HumanObservationService, QualityRunService
from server.services.quality_subjects import resolve_assessed_subject
from server.services.quality_template import default_platform_constraints, quality_policy
from tests.integration.server.services.test_quality_probes import ACTOR
from tests.integration.server.services.test_quality_runs import closure_host as closure_host

SCOPE = {"user_id": "default", "actor_id": ACTOR, "project_name": "project"}


async def test_template_to_pass_disposition_through_the_accepted_services(closure_host) -> None:
    env = closure_host
    token = auth.create_token(ACTOR)
    tree, sockets = env["governance"]
    async with env["factory"]() as session:
        subject = await resolve_assessed_subject(
            session,
            env["project"],
            user_id="default",
            project_name="project",
            root_artifact_key=env["root"].artifact_key,
        )
    policy = quality_policy(
        default_platform_constraints(
            platform_profile_id="pilot",
            width=64,
            height=64,
            min_duration_ms=1000,
            max_duration_ms=900000,
            required_locales=("en",),
        )
    )
    request = publication_request(
        **SCOPE,
        command_id="publish-template",
        profile_id=None,
        expected_revision=0,
        cohort_id="cohort-c",
        product_surface="video",
        policy=policy,
        supersession_effect="HISTORICAL_ONLY",
        now=datetime.now(UTC),
    )
    custodian = await InteractiveProfilePublicationCustodian.for_request(
        request,
        env["factory"],
        interactive_token=token,
        read_directory=tree / "read",
        socket_directory=sockets,
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
    )
    profile = await ProfilePublicationService(env["factory"], custodian=custodian).publish(request)
    observations = []
    for requirement in ("technical-container", "technical-decode"):
        probe = probe_request(
            **SCOPE, execution_ref="probe-" + requirement, subject=subject, profile=profile, requirement_id=requirement
        )
        service = await QualityProbeService.for_request(
            probe,
            env["factory"],
            interactive_token=token,
            project_root=env["project"],
            catalog=HOST_CATALOG,
            runtime=env["runtime"],
        )
        observation = await service.observe(probe)
        assert observation.status == "PASS"
        observations.append(observation)
    review = review_request(
        **SCOPE,
        command_id="review-1",
        subject=subject,
        profile=profile,
        status="PASS",
        criteria_verdicts=dict.fromkeys(RUBRIC_CRITERIA, "PASS"),
        findings=[{"rule_id": "visible-defects", "severity": "ADVISORY", "locator": "t=1000"}],
        notes="Watched in full; one soft frame at 1 s.",
    )
    human = await HumanObservationService.for_request(
        review, env["factory"], interactive_token=token, grant_reader=env["reader"], project_root=env["project"]
    )
    observations.append(await human.record(review))
    seal = completion_request(**SCOPE, command_id="seal-1", subject=subject, profile=profile, observations=observations)
    sealer = await QualityRunService.for_request(
        seal, env["factory"], interactive_token=token, grant_reader=env["reader"], project_root=env["project"]
    )
    run = await sealer.complete(seal)
    dispose = disposition_request(
        **SCOPE,
        command_id="dispose-1",
        run=run,
        run_digest=run_digest(run),
        policy=profile.policy,
        decision="PASS",
        reason="every requirement met",
        waiver_bindings=[],
        expected_version=0,
        requested_ttl_seconds=3600,
        now=datetime.now(UTC),
    )
    disposer = await DispositionCustodian.for_request(
        dispose,
        env["factory"],
        interactive_token=token,
        read_directory=tree / "read",
        socket_directory=sockets,
        expected_uid=os.getuid(),
        expected_gid=os.getgid(),
    )
    disposition = await DispositionService(env["factory"], custodian=disposer, project_root=env["project"]).issue(
        dispose
    )
    assert disposition.decision == "PASS"
    readiness = await quality_readiness(
        env["factory"],
        env["reader"],
        project_root=env["project"],
        user_id="default",
        project_name="project",
        subject_digest=run.subject_digest,
        profile_id=run.profile_id,
    )
    assert readiness.state == "READY"

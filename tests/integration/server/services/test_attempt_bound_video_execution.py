from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from lib.db.repositories.host_hardening import ExecutionAttemptRepository
from r2.contracts.execution import ProviderRequest
from r2.contracts.host_hardening import (
    AttemptSnapshot,
    ExecutionAttemptState,
    ProviderObservation,
    ProviderObservationKind,
    ProviderRouteSnapshot,
)
from r2.host_hardening.host_submit import ProviderSubmitReceipt
from server.services.execution_attempts import build_attempt_submitter, capability_resolver


async def test_video_task_result_carries_selected_version_execution_id(tmp_path, monkeypatch) -> None:
    from server.services import generation_tasks

    class _ProjectManager:
        def update_scene_asset(self, **_kwargs) -> None:
            return None

    class _Versions:
        def get_versions(self, _resource_type: str, _resource_id: str) -> dict:
            return {
                "versions": [
                    {"version": 1, "created_at": "2026-09-18T00:00:00Z"},
                    {
                        "version": 2,
                        "created_at": "2026-09-19T00:00:00Z",
                        "execution_id": "execution-2",
                    },
                ]
            }

    async def _no_thumbnail(_video_file, _thumbnail_file) -> bool:
        return False

    monkeypatch.setattr(generation_tasks, "get_project_manager", lambda: _ProjectManager())
    monkeypatch.setattr(generation_tasks, "extract_video_thumbnail", _no_thumbnail)

    result = await generation_tasks._finalize_video_task(
        project_name="demo",
        script_file="episode-1.json",
        project_path=tmp_path,
        resource_id="E1S01",
        version=2,
        video_uri=None,
        generator=SimpleNamespace(versions=_Versions()),
    )

    assert result["execution_id"] == "execution-2"
    assert result["created_at"] == "2026-09-19T00:00:00Z"


async def test_attempt_submitter_commits_attempt_truth_before_returning(session_factory) -> None:
    route = ProviderRouteSnapshot(
        provider_id="gemini",
        provider_account_ref="default",
        provider_model_id="veo-test",
        backend_model_id="veo-test",
        endpoint_id="generate_videos",
        submitted_base_url="https://generativelanguage.googleapis.com",
        adapter_version="host-video-v1",
        capability_profile_ref="gemini-generate-videos@host-video-v1",
    )
    request = ProviderRequest(
        id="request-1",
        host_task_ref="task-1",
        provider=route.provider_id,
        model=route.provider_model_id,
        endpoint=route.endpoint_id,
        payload={"prompt": "paper boat"},
        adapter_version=route.adapter_version,
    )
    observed_at = datetime.now(UTC)

    async with session_factory() as session:
        submitter = build_attempt_submitter(
            session,
            user_id="u1",
            project_name="demo",
            usage_binder=None,
        )

        async def _submit(_attempt: AttemptSnapshot) -> ProviderSubmitReceipt[str]:
            async with session_factory() as observer_session:
                durable = await ExecutionAttemptRepository(
                    observer_session,
                    capability_resolver=capability_resolver(),
                ).get_for_task_attempt(
                    user_id="u1",
                    project_name="demo",
                    task_id="task-1",
                    attempt_no=1,
                )
                assert durable is not None
                assert durable.state is ExecutionAttemptState.SUBMITTING
            return ProviderSubmitReceipt(
                observation=ProviderObservation(
                    observation_id="observation-1",
                    kind=ProviderObservationKind.ACCEPTED,
                    observed_at=observed_at,
                    provider_sequence=None,
                    provider_job_id="remote-1",
                    reason_code=None,
                    evidence_digest="sha256:" + "a" * 64,
                ),
                value="remote-1",
            )

        result = await submitter.submit(
            task_id="task-1",
            api_call_id=None,
            route=route,
            request=request,
            submit=_submit,
        )

    async with session_factory() as observer_session:
        durable = await ExecutionAttemptRepository(
            observer_session,
            capability_resolver=capability_resolver(),
        ).get_exact(user_id="u1", project_name="demo", execution_id=result.execution_id)

    assert durable is not None
    assert durable.state is ExecutionAttemptState.ACCEPTED
    assert durable.provider_job_id == "remote-1"

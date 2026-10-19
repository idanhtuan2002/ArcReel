"""The queued story run executor: route resolution against the custom provider and the run-phase guard."""

from __future__ import annotations

import functools

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.repositories.custom_provider_repo import CustomProviderRepository
from lib.db.repositories.task_repo import STORY_RUN_TASK_TYPE, TaskRepository
from lib.text_backends.ollama import OllamaChatClient
from server.story_authoring.contracts import StoryModelSelection
from server.story_authoring.executor import execute_story_run_task
from server.story_authoring.runtime import RunPhase, RunStateStore
from tests.integration.server.story_authoring.test_driver import BRIEF, MODEL, ScriptedModel
from tests.integration.server.story_authoring.test_narrative import IDENTITY, NOW

type Factory = async_sessionmaker[AsyncSession]

BASE_URL = "http://ollama:1"


async def _provider(
    factory: Factory, *, base_url: str = BASE_URL, endpoint: str = "ollama-chat", model: str = MODEL
) -> str:
    async with factory() as session:
        provider = await CustomProviderRepository(session).create_provider(
            "Ollama",
            "openai",
            base_url,
            "",
            models=[{"model_id": model, "display_name": model, "endpoint": endpoint}],
        )
        await session.commit()
        return f"custom-{provider.id}"


def _payload(provider_id: str) -> dict:
    selection = StoryModelSelection.create(
        provider_id=provider_id, endpoint="ollama-chat", base_url=BASE_URL, model_id=MODEL, has_credential=False
    )
    return {"brief": BRIEF.model_copy(update={"selection": selection}).model_dump(mode="json")}


async def _task(factory: Factory, payload: dict) -> str:
    async with factory() as session:
        task = await TaskRepository(session).enqueue(
            project_name=IDENTITY.project_name,
            task_type=STORY_RUN_TASK_TYPE,
            media_type="text",
            resource_id=IDENTITY.run_id,
            payload=payload,
            user_id=IDENTITY.user_id,
        )
    return task["task_id"]


def _execute(factory: Factory, model: ScriptedModel, tmp_path):
    def client_for(base_url: str, api_key: str | None) -> OllamaChatClient:
        assert (base_url, api_key) == (BASE_URL, None)
        return OllamaChatClient(base_url=base_url, transport=httpx.MockTransport(model.handler))

    return functools.partial(
        execute_story_run_task, session_factory=factory, project_dir=tmp_path, client_for=client_for, clock=lambda: NOW
    )


async def test_a_queued_run_waits_for_approval(concurrent_session_factory: Factory, tmp_path):
    payload = _payload(await _provider(concurrent_session_factory))
    task_id = await _task(concurrent_session_factory, payload)
    model = ScriptedModel()

    result = await _execute(concurrent_session_factory, model, tmp_path)(
        IDENTITY.project_name, IDENTITY.run_id, payload, user_id=IDENTITY.user_id, task_id=task_id
    )

    assert result == {"run_id": IDENTITY.run_id, "phase": "READY_FOR_APPROVAL"}
    state = await RunStateStore(concurrent_session_factory, task_id=task_id).load()
    assert state.phase is RunPhase.READY_FOR_APPROVAL
    assert model.calls["prose"] == 9


@pytest.mark.parametrize("change", [{"base_url": "http://other:2"}, {"endpoint": "openai-chat"}])
async def test_a_changed_route_stops_the_run_before_any_model_call(
    concurrent_session_factory: Factory, tmp_path, change
):
    provider_id = await _provider(concurrent_session_factory, **change)
    payload = _payload(provider_id)
    task_id = await _task(concurrent_session_factory, payload)
    model = ScriptedModel()

    result = await _execute(concurrent_session_factory, model, tmp_path)(
        IDENTITY.project_name, IDENTITY.run_id, payload, user_id=IDENTITY.user_id, task_id=task_id
    )

    assert result["phase"] == "MODEL_UNAVAILABLE"
    assert sum(model.calls.values()) == 0
    state = await RunStateStore(concurrent_session_factory, task_id=task_id).load()
    assert provider_id in (state.block_reason or "")


async def test_a_run_waiting_for_approval_is_not_driven_again(concurrent_session_factory: Factory, tmp_path):
    payload = _payload(await _provider(concurrent_session_factory))
    task_id = await _task(concurrent_session_factory, payload)
    await _execute(concurrent_session_factory, ScriptedModel(), tmp_path)(
        IDENTITY.project_name, IDENTITY.run_id, payload, user_id=IDENTITY.user_id, task_id=task_id
    )

    again = ScriptedModel()
    result = await _execute(concurrent_session_factory, again, tmp_path)(
        IDENTITY.project_name, IDENTITY.run_id, payload, user_id=IDENTITY.user_id, task_id=task_id
    )

    assert result["phase"] == "READY_FOR_APPROVAL"
    assert sum(again.calls.values()) == 0


JUDGE_URL = "http://judge:1"


async def test_a_judge_route_gets_its_own_gateway_and_reviews_the_run(concurrent_session_factory: Factory, tmp_path):
    writer_id = await _provider(concurrent_session_factory)
    judge_id = await _provider(concurrent_session_factory, base_url=JUDGE_URL, model="judge-12b")
    judge_route = StoryModelSelection.create(
        provider_id=judge_id, endpoint="ollama-chat", base_url=JUDGE_URL, model_id="judge-12b", has_credential=False
    )
    payload = _payload(writer_id)
    payload["brief"]["judge_selection"] = judge_route.model_dump(mode="json")
    task_id = await _task(concurrent_session_factory, payload)
    writer, judge = ScriptedModel(), ScriptedModel("judge-12b")
    judge.paragraphs = writer.paragraphs

    def client_for(base_url: str, _api_key: str | None) -> OllamaChatClient:
        model = judge if base_url == JUDGE_URL else writer
        return OllamaChatClient(base_url=base_url, transport=httpx.MockTransport(model.handler))

    result = await execute_story_run_task(
        IDENTITY.project_name,
        IDENTITY.run_id,
        payload,
        user_id=IDENTITY.user_id,
        task_id=task_id,
        session_factory=concurrent_session_factory,
        project_dir=tmp_path,
        client_for=client_for,
        clock=lambda: NOW,
    )

    assert result["phase"] == "READY_FOR_APPROVAL"
    assert judge.calls["issues"] == 12
    assert "issues" not in writer.calls


async def test_an_unconfigured_judge_route_stops_the_run_before_any_call(concurrent_session_factory: Factory, tmp_path):
    writer_id = await _provider(concurrent_session_factory)
    payload = _payload(writer_id)
    payload["brief"]["judge_selection"] = StoryModelSelection.create(
        provider_id="custom-99999",
        endpoint="ollama-chat",
        base_url=JUDGE_URL,
        model_id="judge-12b",
        has_credential=False,
    ).model_dump(mode="json")
    task_id = await _task(concurrent_session_factory, payload)
    model = ScriptedModel()

    result = await _execute(concurrent_session_factory, model, tmp_path)(
        IDENTITY.project_name, IDENTITY.run_id, payload, user_id=IDENTITY.user_id, task_id=task_id
    )

    assert result["phase"] == "MODEL_UNAVAILABLE"
    assert sum(model.calls.values()) == 0

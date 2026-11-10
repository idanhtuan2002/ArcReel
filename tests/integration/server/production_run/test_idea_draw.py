"""ADR-0125: a run started without an idea draws its idea and settings inside BRIEF, once per run."""

from __future__ import annotations

import json

import httpx
import pytest

from lib.text_backends.ollama import OllamaChatClient
from r2.contracts.automation import RunStage, RunStatus
from server.production_run.story_adapter import _load_brief
from server.story_authoring.artifacts import StoryBlobStore
from server.story_authoring.genre_packs import PACKS
from server.story_authoring.idea_profile import PROFILE_SETTING, ProjectProfile, profile_pin
from tests.integration.server.production_run.test_story_adapter import (
    Host,
    _tick,
)
from tests.integration.server.production_run.test_story_adapter import interactive_env as interactive_env
from tests.integration.server.production_run.test_story_adapter import story_host as story_host
from tests.integration.server.production_run.test_story_adapter import story_policy as story_policy
from tests.integration.server.story_authoring.test_driver import MODEL

pytestmark = pytest.mark.asyncio

FIRST = {
    "title": "Học sinh thứ mười ba",
    "idea": (
        "Một cô giáo trẻ về điểm trường vùng cao và phát hiện lớp mình có một học sinh không ai nhìn thấy. "
        "Cô muốn giữ lớp học, nhưng dân bản đòi đóng cửa trường. Nếu thất bại, đứa trẻ ấy sẽ biến mất mãi mãi."
    ),
    "genre": "Kinh dị",
    "tone": "hồi hộp",
    "audience": "phổ thông",
    "chapters": 18,
}
SECOND = {
    **FIRST,
    "title": "Chuyến đò cuối",
    "idea": (
        "Một lái đò già nhận chở người khách cuối cùng qua sông trong đêm lũ. Ông cần tiền chữa bệnh cho cháu, "
        "nhưng người khách mang theo một chiếc hòm mà cả làng đang truy tìm."
    ),
    "genre": "Trinh thám",
}


@pytest.fixture
def story_start() -> dict:
    return {"idea_mode": "auto"}


class DrawModel:
    def __init__(self, *answers: dict) -> None:
        self.answers = list(answers)
        self.prompts: list[str] = []

    async def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert "audience" in body["format"]["properties"]
        counting = body["options"]["num_predict"] == 1
        if counting:
            content = "{"
        else:
            self.prompts.append(body["messages"][1]["content"])
            content = json.dumps(self.answers.pop(0), ensure_ascii=False)
        return httpx.Response(
            200,
            json={
                "model": MODEL,
                "message": {"role": "assistant", "content": content},
                "done": True,
                "done_reason": "length" if counting else "stop",
                "prompt_eval_count": 500,
                "eval_count": 120,
            },
        )


def _serve(monkeypatch: pytest.MonkeyPatch, model: DrawModel) -> None:
    def client_for(base_url: str, api_key: str | None) -> OllamaChatClient:
        del api_key
        return OllamaChatClient(base_url=base_url, transport=httpx.MockTransport(model.handler))

    monkeypatch.setattr("server.story_authoring.service.default_ollama_client", client_for)


def _shown(host: Host, profile: ProjectProfile) -> None:
    shown = host.projects.load_project("project")[PROFILE_SETTING]
    assert shown["idea"] == profile.idea
    assert shown["run_id"] == host.run.run_id


async def test_a_run_without_an_idea_draws_one_and_briefs_from_it(story_host: Host, monkeypatch):
    host = story_host
    model = DrawModel(FIRST)
    _serve(monkeypatch, model)

    briefed = await _tick(host)
    assert (briefed.stage, briefed.status) == (RunStage.STORY, RunStatus.RUNNING)
    assert len(model.prompts) == 1
    blobs = StoryBlobStore(host.projects.get_project_path("project"))
    pinned = blobs.pinned(profile_pin(host.run.run_id))
    assert pinned is not None
    profile = ProjectProfile.model_validate_json(blobs.read_exact(pinned))
    assert (profile.title, profile.genre_pack, profile.book_chapters, profile.defaulted) == (
        "Học sinh thứ mười ba",
        "horror",
        18,
        (),
    )
    assert profile.seed.angle in model.prompts[0]
    _shown(host, profile)

    async with host.sessions() as session:
        from lib.db.repositories.production_runs import ProductionRunRepository

        receipt = await ProductionRunRepository(session).stage_receipt(run=briefed, stage=RunStage.BRIEF)
    assert receipt is not None
    brief = _load_brief(host.projects, "project", receipt.digest)
    assert brief.genre == next(pack.label for pack in PACKS if pack.pack_id == "horror")
    assert brief.idea.startswith(profile.idea)
    assert "Giọng điệu: hồi hộp" in brief.idea
    assert brief.book is not None
    assert (brief.book.spec.chapters, brief.book.part) == (18, 1)


async def test_an_idea_another_project_holds_is_drawn_again(story_host: Host, monkeypatch):
    host = story_host
    host.projects.create_project("older", content_mode="narration")
    host.projects.create_project_metadata("older", "Cũ", "", "narration")
    host.projects.update_project("older", lambda p: p.update({PROFILE_SETTING: {"title": "x", "idea": FIRST["idea"]}}))

    model = DrawModel(FIRST, SECOND)
    _serve(monkeypatch, model)
    briefed = await _tick(host)
    assert (briefed.stage, briefed.status) == (RunStage.STORY, RunStatus.RUNNING)
    assert len(model.prompts) == 2
    assert FIRST["idea"] in model.prompts[0]
    assert FIRST["idea"] in model.prompts[1]
    shown = host.projects.load_project("project")[PROFILE_SETTING]
    assert shown["title"] == "Chuyến đò cuối"
    assert shown["genre_pack"] == "mystery"


async def test_two_repeats_stop_the_run_with_idea_duplicate(story_host: Host, monkeypatch):
    host = story_host
    host.projects.create_project("older", content_mode="narration")
    host.projects.create_project_metadata("older", "Cũ", "", "narration")
    host.projects.update_project("older", lambda p: p.update({PROFILE_SETTING: {"title": "x", "idea": FIRST["idea"]}}))

    model = DrawModel(FIRST, FIRST)
    _serve(monkeypatch, model)
    blocked = await _tick(host)
    assert blocked.reason == "IDEA_DUPLICATE"
    assert blocked.stage is RunStage.BRIEF
    assert StoryBlobStore(host.projects.get_project_path("project")).pinned(profile_pin(host.run.run_id)) is None

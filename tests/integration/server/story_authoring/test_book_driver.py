"""A book written in two parts on a scripted model (ADR-0116): part 1 plans the book and commits its state; part 2
copies the cast and plan, reads the memory and numbers its chapters across the book."""

from __future__ import annotations

import json
from typing import Any

import httpx

from lib.db.repositories.task_repo import STORY_RUN_TASK_TYPE, TaskRepository
from lib.text_backends.ollama import OllamaChatClient
from server.story_authoring.artifacts import StoryBlobStore
from server.story_authoring.book import BookPart, BookSpec, BookState
from server.story_authoring.commit import load_offered_manifest
from server.story_authoring.driver import StoryRunDriver
from server.story_authoring.generation import AuthoringTextGateway
from server.story_authoring.narrative import StoryIdentity
from server.story_authoring.runtime import RunPhase, RunStateStore, StoryAttemptSink, new_run_state
from tests.integration.server.story_authoring.test_driver import BRIEF, LIMITS, MODEL, SELECTION, ScriptedModel
from tests.integration.server.story_authoring.test_narrative import NOW

SPEC = BookSpec(chapters=6, part_chapters=3)
ROLES = ("setup", "advance", "turn", "breath")


class BookModel(ScriptedModel):
    """The scripted model plus the book's own requests: skeleton, chapter rows, chapter digests, part summary."""

    def __init__(self) -> None:
        super().__init__()
        self.rows_written = 0

    def _book_answer(self, kind: str, schema: dict[str, Any]) -> Any:
        properties = schema["properties"]
        if kind == "book_outline":
            count = properties["volumes"]["minItems"]
            return {
                "logline": "Minh về làng.",
                "story_arc": "về, giằng co, giữ",
                "central_question": "Minh có giữ nhà không?",
                "ending": "Minh ở lại giữ nhà.",
                "final_image": "ngọn đèn",
                "volumes": [
                    {
                        "title": f"Quyển {v}",
                        "objective": "Minh đối mặt món nợ",
                        "key_results": ["tìm sổ", "gặp chủ nợ", "quyết định"],
                        "turning_point": "Minh chọn ở lại",
                        "new_characters": [],
                        "new_locations": [],
                    }
                    for v in range(count)
                ],
            }
        if kind == "rows":
            rows = []
            for _ in range(properties["rows"]["minItems"]):
                self.rows_written += 1
                i = self.rows_written
                rows.append(
                    {
                        "core_task": f"nhiệm vụ chương {i}",
                        "threads_advanced": "món nợ",
                        "turning_point": f"bước ngoặt chương {i}",
                        "role": "climax" if i == SPEC.chapters else ROLES[(i - 1) % len(ROLES)],
                        "plants": ["lá thư không ký tên"] if i == 1 else [],
                        "payoffs": ["h1"] if i == 3 else [],
                    }
                )
            return {"rows": rows}
        if kind == "digest":
            return {
                "summary": "Minh và Lan đối mặt món nợ.",
                "events": ["Minh mở sổ."],
                "characters": [{"name": "Minh", "state": "quyết ở lại"}, {"name": "Tuấn", "state": "bịa"}],
                "hooks": [],
                "new_threads": [],
                "time_place": "đêm, căn nhà cũ",
            }
        return {"summary": "Phần một: Minh về làng, tìm thấy sổ nợ."}

    async def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        properties = body["format"].get("properties", {})
        kind = (
            "book_outline"
            if "central_question" in properties
            else "rows"
            if "rows" in properties
            else "digest"
            if "time_place" in properties
            else "part_summary"
            if set(properties) == {"summary"}
            else None
        )
        if kind is None:
            return await super().handler(request)
        counting = body["options"]["num_predict"] == 1
        if counting:
            content = "{"
        else:
            self.calls[kind] += 1
            self.prompts.append((kind, body["messages"][1]["content"]))
            content = json.dumps(self._book_answer(kind, body["format"]), ensure_ascii=False)
        return httpx.Response(
            200,
            json={
                "model": self.model_name,
                "message": {"role": "assistant", "content": content},
                "done": True,
                "done_reason": "length" if counting else "stop",
                "prompt_eval_count": 700,
                "eval_count": 80,
            },
        )


async def _part(factory, blobs: StoryBlobStore, model: BookModel, part: BookPart, run_id: str):
    identity = StoryIdentity(user_id="default", project_name="story-test", run_id=run_id)
    async with factory() as session:
        task = await TaskRepository(session).enqueue(
            project_name=identity.project_name, task_type=STORY_RUN_TASK_TYPE, media_type="text", resource_id=run_id
        )
    store = RunStateStore(factory, task_id=task["task_id"])
    await store.initialize(new_run_state(run_id=run_id, limits=LIMITS, now=NOW))
    brief = BRIEF.model_copy(update={"book": part, "gate_a_decision_id": f"gate-{run_id}"})
    client = OllamaChatClient(base_url="http://ollama:1", transport=httpx.MockTransport(model.handler))
    sink = StoryAttemptSink(store=store, session_factory=factory, provider_id="custom-ollama", model_id=MODEL)
    gateway = AuthoringTextGateway(selection=SELECTION, limits=LIMITS, client=client, sink=sink)
    driver = StoryRunDriver(
        identity=identity,
        brief=brief,
        store=store,
        gateway=gateway,
        blobs=blobs,
        clock=lambda: NOW,
        retry_delays=(0, 0),
    )
    return await driver.run()


async def test_a_book_is_planned_once_and_its_second_part_continues_from_the_committed_state(
    concurrent_session_factory, tmp_path
):
    blobs = StoryBlobStore(tmp_path)
    first = BookModel()

    state = await _part(concurrent_session_factory, blobs, first, BookPart(spec=SPEC), "book1")

    assert state.phase is RunPhase.READY_FOR_APPROVAL, state.block_reason
    assert (first.calls["book_outline"], first.calls["rows"], first.calls["story_arc"]) == (1, 1, 0)
    assert (first.calls["digest"], first.calls["part_summary"]) == (3, 1)
    manifest = load_offered_manifest(blobs, state)
    assert [(s.chapter, s.scene) for s in manifest.scenes] == [(c, s) for c in (1, 2, 3) for s in (1, 2, 3)]
    assert manifest.quality_record_digest is not None
    record = json.loads(blobs.read_exact(manifest.quality_record_digest))
    book = BookState.model_validate_json(blobs.read_exact(record["book_state"]))
    assert (book.parts_done, book.title, record["book_part"]) == (1, "Căn nhà cũ", 1)
    assert [c for c, _ in book.memory.chapter_summaries] == [1, 2, 3]
    assert book.memory.part_summaries == ((1, "Phần một: Minh về làng, tìm thấy sổ nợ."),)
    assert [name for name, _, _ in book.memory.characters] == ["Minh"]  # "Tuấn" is never written
    assert [(h.hook_id, h.planted, h.paid) for h in book.plan.hooks] == [("h1", 1, 3)]
    export = blobs.read_exact(manifest.export_digest).decode("utf-8")
    assert export.startswith("# Căn nhà cũ — Phần 1\n")
    plan_prompts = [p for k, p in first.prompts if k == "chapter_goal"]
    assert "vai trò: setup" in plan_prompts[0]
    assert "Phục bút phải cài trong chương: lá thư không ký tên" in plan_prompts[0]
    assert all("Đây là chương cuối" not in p for p in plan_prompts)
    prose = [p for k, p in first.prompts if k == "prose"]
    assert all("Đây là cảnh cuối của truyện" not in p for p in prose)
    assert "Minh và Lan đối mặt món nợ." in prose[3]  # chapter 2 sees chapter 1's digest
    critic = next(p for k, p in first.prompts if k == "ending_resolves_conflict")
    assert "Tóm tắt các chương trước của phần này" in critic

    second = BookModel()
    state = await _part(
        concurrent_session_factory,
        blobs,
        second,
        BookPart(spec=SPEC, part=2, state_digest=record["book_state"]),
        "book2",
    )

    assert state.phase is RunPhase.READY_FOR_APPROVAL, state.block_reason
    for kind in ("working_title", "logline", "narration_style", "story_arc", "book_outline", "rows"):
        assert second.calls[kind] == 0, kind
    manifest = load_offered_manifest(blobs, state)
    export = blobs.read_exact(manifest.export_digest).decode("utf-8")
    assert export.startswith("# Căn nhà cũ — Phần 2\n")
    assert [line for line in export.splitlines() if line.startswith("## ")] == [
        "## Chương 4",
        "## Chương 5",
        "## Chương 6",
    ]
    plan_prompts = [p for k, p in second.prompts if k == "chapter_goal"]
    assert "[Chương 4 trong tiểu thuyết — vai trò: breath]" in plan_prompts[0]
    assert "Phần 1: Phần một: Minh về làng" in plan_prompts[0]
    assert "Đây là chương cuối" in plan_prompts[-1]
    prose = [p for k, p in second.prompts if k == "prose"]
    assert "Bộ nhớ truyện" in prose[0]
    assert "Đây là cảnh cuối của truyện" in prose[-1]
    record = json.loads(blobs.read_exact(load_offered_manifest(blobs, state).quality_record_digest or ""))
    assert BookState.model_validate_json(blobs.read_exact(record["book_state"])).parts_done == 2

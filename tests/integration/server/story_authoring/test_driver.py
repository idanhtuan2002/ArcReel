"""The story run driver end to end on a scripted model: convergence, resume, revision intents and blocked phases.

The model is an ``httpx.MockTransport`` behind the real Ollama client, gateway and durable attempt sink; it answers
each request by the shape of its JSON schema. Runs on PostgreSQL when DATABASE_URL points at one, else SQLite.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.db.repositories.task_repo import STORY_RUN_TASK_TYPE, TaskRepository
from lib.text_backends.ollama import OllamaChatClient
from server.story_authoring.artifacts import StoryBlobStore
from server.story_authoring.commit import load_offered_manifest
from server.story_authoring.contracts import StoryLimits, StoryModelSelection
from server.story_authoring.driver import StoryBrief, StoryRunDriver
from server.story_authoring.generation import AuthoringTextGateway
from server.story_authoring.pipeline import scene_draft
from server.story_authoring.runtime import (
    RunPhase,
    RunStateStore,
    StoryAttemptSink,
    add_intent,
    new_run_state,
    set_phase,
)
from tests.integration.server.story_authoring.test_narrative import IDENTITY, NOW

type Factory = async_sessionmaker[AsyncSession]
type Answer = Callable[[str, dict[str, Any]], Any]

MODEL = "ornith-32k:9b"
SELECTION = StoryModelSelection.create(
    provider_id="custom-ollama",
    endpoint="ollama-chat",
    base_url="http://ollama:1",
    model_id=MODEL,
    has_credential=False,
)
LIMITS = StoryLimits(input_tokens_max=10**8, output_tokens_max=10**8, wall_clock_max_seconds=10**6)
BRIEF = StoryBrief(
    idea="Một người con về làng bán căn nhà của cha và tìm thấy cuốn sổ nợ.",
    genre="đời thường",
    gate_a_decision_id="gate-a-1",
    selection=SELECTION,
    limits=LIMITS,
)

ACTIONS = (
    "đẩy cánh cổng gỗ",
    "nhìn giàn mướp khô",
    "lau mặt bàn thờ",
    "đếm từng viên gạch",
    "nghe tiếng gà gáy",
    "pha một ấm trà",
    "mở hòm áo cũ",
    "gấp tấm chăn mỏng",
    "quét lá trong sân",
    "rót nước vào chum",
    "nhóm bếp rơm",
    "xem tờ lịch treo",
    "chạm vào mái ngói",
    "dọn góc nhà kho",
    "ngồi trên bậc thềm",
    "vuốt ve con mèo",
    "kéo rèm cửa sổ",
    "thắp nén nhang",
    "lật cuốn sổ nợ",
    "cầm chiếc đèn dầu",
)
TIMES = (
    "lúc trời vừa sáng",
    "khi nắng lên cao",
    "giữa buổi trưa",
    "lúc chiều tà",
    "khi trời chạng vạng",
    "lúc đêm xuống",
    "trong cơn mưa phùn",
    "sau bữa cơm",
)
NAMES = ("Minh", "Lan")
SENTENCES_PER_PARAGRAPH = 9


def _scene(index: int) -> dict[str, Any]:
    return {
        "summary": f"cảnh thứ {index}",
        "location": "Căn nhà cũ",
        "pov": "Minh",
        "characters": ["Minh", "Lan"],
        "beats": ["Minh trở về", "Lan chờ"],
        "emotional_turn": "lặng",
        "plot_function": "mở",
        "dialogue_required": False,
    }


STRUCTURED: dict[str, Any] = {
    "working_title": {
        "working_title": "Căn nhà cũ",
        "premise": "Minh về làng bán căn nhà của cha.",
        "genre": "đời thường",
        "tone": "lặng",
        "pov": "ngôi thứ ba",
        "central_conflict": "bán hay giữ nhà",
        "ending_direction": "Minh giữ lại nhà",
        "characters": [
            {
                "name": "Minh",
                "role": "chính",
                "relation_to_protagonist": "nhân vật chính",
                "description": "con trai cả",
                "goal": "bán nhà",
            },
            {
                "name": "Lan",
                "role": "phụ",
                "relation_to_protagonist": "em gái Minh",
                "description": "ở lại làng",
                "goal": "giữ nhà",
            },
        ],
        "locations": [{"name": "Căn nhà cũ", "description": "nhà ba gian"}],
    },
    "logline": {
        "logline": "Minh về bán nhà.",
        "core_promise": "tình anh em",
        "world_rules": ["làng nhỏ"],
        "major_conflicts": ["bán hay giữ"],
        "forbidden_contradictions": ["Lan là em"],
    },
    "narration_style": {
        "narration_style": "kể chậm",
        "sentence_rhythm": "câu ngắn",
        "emotional_texture": "lặng",
        "dialogue_style": "ít lời",
        "forbidden_style": ["sáo rỗng"],
        "style_rules": ["tả cụ thể", "ít tính từ", "câu ngắn"],
    },
    "story_arc": {
        "story_arc": "về, giằng co, giữ",
        "opening": "Minh về.",
        "confrontation": "Lan phản đối.",
        "resolution": "Minh giữ nhà.",
        "chapters": [
            {"core_task": "trở về", "threads_advanced": "nợ", "turning_point": "cuốn sổ"},
            {"core_task": "giằng co", "threads_advanced": "nợ", "turning_point": "người mua"},
            {"core_task": "quyết định", "threads_advanced": "nợ", "turning_point": "trả nợ"},
        ],
        "ending": "Minh ở lại.",
        "final_image": "ngọn đèn",
    },
    "passed": {"passed": True, "problems": []},
    "chapter_goal": {
        "chapter_goal": "Minh về nhà",
        "reader_expectation": "tò mò",
        "withheld_cards": [],
        "required_changes_by_end": ["Minh thấy cuốn sổ"],
        "do_not": [],
        "scenes": [_scene(1), _scene(2), _scene(3)],
    },
}


class ScriptedModel:
    """Answers by the request's schema. ``overrides`` replace an answer kind, ``fail_at`` breaks a call number of a
    kind, and ``before`` runs a hook before a call number of a kind is answered."""

    _instances = 0

    def __init__(self) -> None:
        self.calls: Counter[str] = Counter()
        self.prompts: list[tuple[str, str]] = []
        self.paragraphs: list[str] = []
        self.overrides: dict[str, Answer] = {}
        self.fail_at: dict[str, int] = {}
        self.before: dict[tuple[str, int], Callable[[], Awaitable[None]]] = {}
        ScriptedModel._instances += 1
        self._sentence = ScriptedModel._instances * 100_000

    def _prose(self, count: int) -> dict[str, Any]:
        paragraphs = []
        for _ in range(count):
            sentences = []
            for _ in range(SENTENCES_PER_PARAGRAPH):
                i = self._sentence
                self._sentence += 1
                sentences.append(
                    f"{NAMES[i % 2]} {ACTIONS[(i // 2) % len(ACTIONS)]} {TIMES[(i // 40) % len(TIMES)]} lần thứ {i + 1}."
                )
            paragraphs.append(" ".join(sentences))
        self.paragraphs.extend(paragraphs)
        return {"paragraphs": paragraphs}

    def packaging(self) -> dict[str, Any]:
        return {
            "titles": [{"title": t, "kind": "k"} for t in ("Căn nhà cũ", "Sổ nợ", "Ngọn đèn")],
            "blurbs": ["Minh về làng.", "Một cuốn sổ nợ."],
            "selling_points": [{"point": f"điểm {i}", "evidence_quote": q} for i, q in enumerate(self.paragraphs[-3:])],
            "tags": ["làng", "nhà", "anh em", "nợ", "đời thường"],
        }

    def _answer(self, kind: str, schema: dict[str, Any], prompt: str) -> Any:
        if kind in self.overrides:
            return self.overrides[kind](prompt, schema)
        if kind == "prose":
            return self._prose(schema["properties"]["paragraphs"]["minItems"])
        if kind in STRUCTURED:
            return STRUCTURED[kind]
        if kind == "ending_resolves_conflict":
            return {"ending_resolves_conflict": True, "ending_quote": self.paragraphs[-1], "issues": []}
        if kind == "issues":
            return {"issues": []}
        if kind == "titles":
            return self.packaging()
        if kind == "patches":
            return {"patches": [], "notes": "không sửa"}
        if kind == "rewrites":
            return {"rewrites": []}
        raise AssertionError(f"unscripted request kind {kind}")

    async def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        schema = body["format"]
        properties = schema.get("properties", {})
        kind = (
            "prose"
            if "paragraphs" in properties
            else next(
                k
                for k in (*STRUCTURED, "ending_resolves_conflict", "issues", "titles", "patches", "rewrites")
                if k in properties
            )
        )
        prompt = body["messages"][1]["content"]
        counting = body["options"]["num_predict"] == 1
        if counting:
            content = "{"
        else:
            self.calls[kind] += 1
            self.prompts.append((kind, prompt))
            hook = self.before.pop((kind, self.calls[kind]), None)
            if hook is not None:
                await hook()
            if self.fail_at.get(kind) == self.calls[kind]:
                return httpx.Response(500, json={"error": "model crashed"})
            content = json.dumps(self._answer(kind, schema, prompt), ensure_ascii=False)
        return httpx.Response(
            200,
            json={
                "model": MODEL,
                "message": {"role": "assistant", "content": content},
                "done": True,
                "done_reason": "length" if counting else "stop",
                "prompt_eval_count": 700,
                "eval_count": 80,
            },
        )


async def _store(factory: Factory) -> RunStateStore:
    async with factory() as session:
        task = await TaskRepository(session).enqueue(
            project_name=IDENTITY.project_name, task_type=STORY_RUN_TASK_TYPE, media_type="text", resource_id="run1"
        )
    store = RunStateStore(factory, task_id=task["task_id"])
    await store.initialize(new_run_state(run_id=IDENTITY.run_id, limits=LIMITS, now=NOW))
    return store


def _driver(factory: Factory, store: RunStateStore, model: ScriptedModel, blobs: StoryBlobStore) -> StoryRunDriver:
    client = OllamaChatClient(base_url="http://ollama:1", transport=httpx.MockTransport(model.handler))
    sink = StoryAttemptSink(store=store, session_factory=factory, provider_id="custom-ollama", model_id=MODEL)
    gateway = AuthoringTextGateway(selection=SELECTION, limits=LIMITS, client=client, sink=sink)
    return StoryRunDriver(identity=IDENTITY, brief=BRIEF, store=store, gateway=gateway, blobs=blobs, clock=lambda: NOW)


async def _rerun(store: RunStateStore, *, intent: tuple[str, str] | None = None) -> None:
    def change(state):
        if intent is not None:
            state = add_intent(state, node_ids=(intent[0],), note=intent[1])
        return set_phase(state, RunPhase.RUNNING), None

    await store.apply(change)


async def test_a_clean_run_converges_and_offers_one_manifest(concurrent_session_factory: Factory, tmp_path):
    store = await _store(concurrent_session_factory)
    model = ScriptedModel()
    blobs = StoryBlobStore(tmp_path)

    state = await _driver(concurrent_session_factory, store, model, blobs).run()

    assert state.phase is RunPhase.READY_FOR_APPROVAL, state.block_reason
    manifest = load_offered_manifest(blobs, state)
    assert [(s.chapter, s.scene) for s in manifest.scenes] == [(c, s) for c in (1, 2, 3) for s in (1, 2, 3)]
    assert manifest.brief_digest == BRIEF.digest()
    assert manifest.quality_record_digest is not None
    export = blobs.read_exact(manifest.export_digest).decode("utf-8")
    assert export.startswith("# Căn nhà cũ\n")
    assert [line for line in export.splitlines() if line.startswith("## ")] == [
        "## Chương 1",
        "## Chương 2",
        "## Chương 3",
    ]
    assert all(s.revision.normalized_content in export for s in manifest.scenes)
    assert model.calls["prose"] == 9
    assert model.calls["issues"] == 12
    assert (model.calls["ending_resolves_conflict"], model.calls["titles"]) == (1, 1)


async def test_a_second_run_of_a_converged_story_calls_no_model(concurrent_session_factory: Factory, tmp_path):
    store = await _store(concurrent_session_factory)
    blobs = StoryBlobStore(tmp_path)
    await _driver(concurrent_session_factory, store, ScriptedModel(), blobs).run()
    first = load_offered_manifest(blobs, await store.load())
    await _rerun(store)

    again = ScriptedModel()
    state = await _driver(concurrent_session_factory, store, again, blobs).run()

    assert state.phase is RunPhase.READY_FOR_APPROVAL
    assert sum(again.calls.values()) == 0
    assert load_offered_manifest(blobs, state).digest() == first.digest()


async def test_a_crash_mid_run_resumes_without_regenerating_converged_nodes(
    concurrent_session_factory: Factory, tmp_path
):
    store = await _store(concurrent_session_factory)
    blobs = StoryBlobStore(tmp_path)
    crashing = ScriptedModel()
    crashing.fail_at["prose"] = 5

    stopped = await _driver(concurrent_session_factory, store, crashing, blobs).run()
    assert stopped.phase is RunPhase.MODEL_UNAVAILABLE
    assert stopped.commit is None

    await _rerun(store)
    healthy = ScriptedModel()
    state = await _driver(concurrent_session_factory, store, healthy, blobs).run()

    assert state.phase is RunPhase.READY_FOR_APPROVAL, state.block_reason
    assert healthy.calls["prose"] == 5
    assert not {"working_title", "logline", "narration_style", "story_arc", "chapter_goal"} & set(healthy.calls)


async def test_a_scene_revision_regenerates_that_scene_and_everything_after_it(
    concurrent_session_factory: Factory, tmp_path
):
    store = await _store(concurrent_session_factory)
    blobs = StoryBlobStore(tmp_path)
    await _driver(concurrent_session_factory, store, ScriptedModel(), blobs).run()
    before = load_offered_manifest(blobs, await store.load())

    await _rerun(store, intent=(scene_draft(3, 1), "Cho Lan nói nhiều hơn."))
    revised = ScriptedModel()
    state = await _driver(concurrent_session_factory, store, revised, blobs).run()

    assert state.phase is RunPhase.READY_FOR_APPROVAL, state.block_reason
    after = load_offered_manifest(blobs, state)
    assert [a.decision_id for a in after.scenes[:6]] == [b.decision_id for b in before.scenes[:6]]
    assert all(a.decision_id != b.decision_id for a, b in zip(after.scenes[6:], before.scenes[6:], strict=True))
    assert revised.calls["prose"] == 3
    assert revised.calls["issues"] == 4
    assert "Cho Lan nói nhiều hơn." in next(p for k, p in revised.prompts if k == "prose")


async def test_a_quoted_continuity_error_is_repaired_before_the_chapter_is_sealed(
    concurrent_session_factory: Factory, tmp_path
):
    store = await _store(concurrent_session_factory)
    blobs = StoryBlobStore(tmp_path)
    model = ScriptedModel()
    flagged: list[str] = []

    def audit(prompt: str, _schema: dict[str, Any]) -> dict[str, Any]:
        if flagged or "TÍNH LIÊN TỤC" not in prompt:
            return {"issues": []}
        flagged.append(model.paragraphs[1])
        issue = {
            "severity": "critical",
            "issue_type": "mâu_thuẫn",
            "description": "sai thời điểm",
            "quote": model.paragraphs[1],
            "suggested_fix": "sửa",
        }
        return {"issues": [issue]}

    def patch(_prompt: str, _schema: dict[str, Any]) -> dict[str, Any]:
        return {"patches": [{"before": flagged[0], "after": "Minh đứng yên rất lâu bên hiên."}], "notes": "sửa"}

    model.overrides["issues"] = audit
    model.overrides["patches"] = patch

    state = await _driver(concurrent_session_factory, store, model, blobs).run()

    assert state.phase is RunPhase.READY_FOR_APPROVAL, state.block_reason
    manifest = load_offered_manifest(blobs, state)
    assert "Minh đứng yên rất lâu bên hiên." in manifest.scenes[0].revision.normalized_content
    assert flagged[0] not in manifest.scenes[0].revision.normalized_content
    assert model.calls["patches"] == 1
    assert model.calls["issues"] == 16


async def test_an_output_that_never_validates_stops_at_the_node_cap(concurrent_session_factory: Factory, tmp_path):
    store = await _store(concurrent_session_factory)
    model = ScriptedModel()
    model.overrides["working_title"] = lambda _p, _s: {"working_title": "thiếu trường"}

    state = await _driver(concurrent_session_factory, store, model, StoryBlobStore(tmp_path)).run()

    assert state.phase is RunPhase.BLOCKED_QUALITY
    assert "seed" in (state.block_reason or "")
    assert model.calls["working_title"] == 3
    assert state.commit is None


def _critic(model: ScriptedModel, verdicts: list[bool]) -> Answer:
    def answer(_prompt: str, _schema: dict[str, Any]) -> dict[str, Any]:
        resolved = verdicts.pop(0) if len(verdicts) > 1 else verdicts[0]
        return {"ending_resolves_conflict": resolved, "ending_quote": model.paragraphs[-1], "issues": []}

    return answer


async def test_an_unresolved_ending_rewrites_the_final_scene_once(concurrent_session_factory: Factory, tmp_path):
    store = await _store(concurrent_session_factory)
    model = ScriptedModel()
    model.overrides["ending_resolves_conflict"] = _critic(model, [False, True])

    state = await _driver(concurrent_session_factory, store, model, StoryBlobStore(tmp_path)).run()

    assert state.phase is RunPhase.READY_FOR_APPROVAL, state.block_reason
    assert (model.calls["prose"], model.calls["ending_resolves_conflict"]) == (10, 2)
    assert model.calls["issues"] == 16
    last_prose_prompt = [p for k, p in model.prompts if k == "prose"][-1]
    assert "chưa khép lại xung đột trung tâm" in last_prose_prompt


async def test_an_ending_that_stays_unresolved_is_never_offered(concurrent_session_factory: Factory, tmp_path):
    store = await _store(concurrent_session_factory)
    model = ScriptedModel()
    model.overrides["ending_resolves_conflict"] = _critic(model, [False])

    state = await _driver(concurrent_session_factory, store, model, StoryBlobStore(tmp_path)).run()

    assert state.phase is RunPhase.BLOCKED_QUALITY
    assert "manuscript_review" in (state.block_reason or "")
    assert (model.calls["prose"], model.calls["ending_resolves_conflict"]) == (10, 2)
    assert state.commit is None


async def test_packaging_needs_three_selling_points_that_quote_the_manuscript(
    concurrent_session_factory: Factory, tmp_path
):
    store = await _store(concurrent_session_factory)
    model = ScriptedModel()

    def invented(_prompt: str, _schema: dict[str, Any]) -> dict[str, Any]:
        answer = model.packaging()
        answer["selling_points"][0]["evidence_quote"] = "Một câu không có trong truyện."
        return answer

    model.overrides["titles"] = invented

    state = await _driver(concurrent_session_factory, store, model, StoryBlobStore(tmp_path)).run()

    assert state.phase is RunPhase.BLOCKED_QUALITY
    assert "packaging" in (state.block_reason or "")
    assert model.calls["titles"] == 2


def test_the_brief_digest_is_what_gate_a_greenlights_and_excludes_the_decision():
    draft = BRIEF.model_copy(update={"gate_a_decision_id": None})
    assert draft.digest() == BRIEF.digest()
    assert BRIEF.model_copy(update={"idea": "Một ý khác."}).digest() != BRIEF.digest()


async def test_a_run_needs_its_gate_a_decision(concurrent_session_factory: Factory, tmp_path):
    store = await _store(concurrent_session_factory)
    driver = _driver(concurrent_session_factory, store, ScriptedModel(), StoryBlobStore(tmp_path))
    with pytest.raises(ValueError, match="Gate A"):
        StoryRunDriver(
            identity=IDENTITY,
            brief=BRIEF.model_copy(update={"gate_a_decision_id": None}),
            store=store,
            gateway=driver._gateway,
            blobs=StoryBlobStore(tmp_path),
        )


async def test_a_story_far_below_the_length_range_is_never_offered(concurrent_session_factory: Factory, tmp_path):
    store = await _store(concurrent_session_factory)
    model = ScriptedModel()
    full = model._prose

    def short(_prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        answer = full(schema["properties"]["paragraphs"]["minItems"])
        paragraphs = [". ".join(p.split(". ")[:3]).rstrip(".") + "." for p in answer["paragraphs"]]
        model.paragraphs[-len(paragraphs) :] = paragraphs
        return {"paragraphs": paragraphs}

    model.overrides["prose"] = short

    state = await _driver(concurrent_session_factory, store, model, StoryBlobStore(tmp_path)).run()

    assert state.phase is RunPhase.BLOCKED_QUALITY
    assert "STORY_LENGTH" in (state.block_reason or "")
    assert state.commit is None


async def test_a_revision_requested_while_running_is_honoured_before_the_offer(
    concurrent_session_factory: Factory, tmp_path
):
    store = await _store(concurrent_session_factory)
    model = ScriptedModel()

    async def request_revision() -> None:
        await store.apply(lambda s: (add_intent(s, node_ids=(scene_draft(1, 1),), note="Thêm mưa."), None))

    model.before[("titles", 1)] = request_revision

    state = await _driver(concurrent_session_factory, store, model, StoryBlobStore(tmp_path)).run()

    assert state.phase is RunPhase.READY_FOR_APPROVAL, state.block_reason
    assert model.calls["prose"] == 18
    assert model.calls["titles"] == 2
    assert "Thêm mưa." in [p for k, p in model.prompts if k == "prose"][9]


def _memo_issue(model: ScriptedModel, flagged: list[str]) -> Answer:
    def audit(prompt: str, _schema: dict[str, Any]) -> dict[str, Any]:
        if flagged or "GHI CHÚ CHƯƠNG" not in prompt:
            return {"issues": []}
        flagged.append(model.paragraphs[-1])
        issue = {
            "severity": "critical",
            "issue_type": "required_change_missing",
            "description": "Minh chưa thấy cuốn sổ",
            "quote": model.paragraphs[-1],
            "suggested_fix": "cho Minh thấy cuốn sổ",
        }
        return {"issues": [issue]}

    return audit


async def test_a_contract_finding_regenerates_the_scene_with_an_editor_note_inside_its_cap(
    concurrent_session_factory: Factory, tmp_path
):
    store = await _store(concurrent_session_factory)
    model = ScriptedModel()
    flagged: list[str] = []
    model.overrides["issues"] = _memo_issue(model, flagged)

    state = await _driver(concurrent_session_factory, store, model, StoryBlobStore(tmp_path)).run()

    assert state.phase is RunPhase.READY_FOR_APPROVAL, state.block_reason
    assert len(state.intents[scene_draft(1, 3)]) == 1
    assert state.intents[scene_draft(1, 3)][0].startswith("Biên tập tự động: ")
    assert "Minh chưa thấy cuốn sổ" in [p for k, p in model.prompts if k == "prose"][3]
    assert model.calls["prose"] == 10
    assert model.calls.get("patches", 0) == 0
    scene_steps = {a.step_id for a in state.attempts if a.step_id.startswith(scene_draft(1, 3))}
    assert scene_steps == {f"{scene_draft(1, 3)}@r0.0.0#1", f"{scene_draft(1, 3)}@r0.0.0#2"}


async def test_a_final_review_that_blocks_keeps_its_findings(concurrent_session_factory: Factory, tmp_path):
    store = await _store(concurrent_session_factory)
    model = ScriptedModel()

    def always(prompt: str, _schema: dict[str, Any]) -> dict[str, Any]:
        if "GHI CHÚ CHƯƠNG" not in prompt or "[Chương 1 cần thẩm định]" not in prompt:
            return {"issues": []}
        quote = prompt.rsplit("\n\n", 1)[-1].split(". ")[0] + "."
        issue = {
            "severity": "critical",
            "issue_type": "withheld_card_revealed",
            "description": "lộ bài",
            "quote": quote,
            "suggested_fix": "giấu",
        }
        return {"issues": [issue]}

    model.overrides["issues"] = always

    state = await _driver(concurrent_session_factory, store, model, StoryBlobStore(tmp_path)).run()

    assert state.phase is RunPhase.BLOCKED_QUALITY
    assert state.blocked_findings
    assert {f["code"] for f in state.blocked_findings} == {"MEMO_COMPLIANCE:withheld_card_revealed"}
    assert all(f["quote"] for f in state.blocked_findings)


async def test_a_sentence_copied_from_an_earlier_scene_is_removed_without_a_model_call(
    concurrent_session_factory: Factory, tmp_path
):
    store = await _store(concurrent_session_factory)
    model = ScriptedModel()
    full = model._prose
    copied: list[str] = []

    def copying(_prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        answer = full(schema["properties"]["paragraphs"]["minItems"])
        if model.calls["prose"] == 2:
            copied.append(model.paragraphs[0].split(". ")[0] + ".")
            answer["paragraphs"][0] = copied[0] + " " + answer["paragraphs"][0]
        return answer

    model.overrides["prose"] = copying

    state = await _driver(concurrent_session_factory, store, model, StoryBlobStore(tmp_path)).run()

    assert state.phase is RunPhase.READY_FOR_APPROVAL, state.block_reason
    manifest = load_offered_manifest(StoryBlobStore(tmp_path), state)
    assert manifest.scenes[0].revision.normalized_content.count(copied[0]) == 1
    assert copied[0] not in manifest.scenes[1].revision.normalized_content
    assert model.calls["prose"] == 9


async def test_a_chapter_plan_with_a_contradiction_is_revised_before_any_scene(
    concurrent_session_factory: Factory, tmp_path
):
    store = await _store(concurrent_session_factory)
    model = ScriptedModel()
    reviews: list[str] = []

    def review(prompt: str, _schema: dict[str, Any]) -> dict[str, Any]:
        reviews.append(prompt)
        if "Kiểm tra kế hoạch chương 2" in prompt:
            return {"passed": False, "problems": ["chapter_goal hé lộ cuốn sổ, trái với withheld_cards"]}
        return {"passed": True, "problems": []}

    model.overrides["passed"] = review

    state = await _driver(concurrent_session_factory, store, model, StoryBlobStore(tmp_path)).run()

    assert state.phase is RunPhase.READY_FOR_APPROVAL, state.block_reason
    assert model.calls["chapter_goal"] == 4
    plan_prompts = [p for k, p in model.prompts if k == "chapter_goal"]
    assert "chapter_goal hé lộ cuốn sổ, trái với withheld_cards" in plan_prompts[2]
    assert sum(1 for p in reviews if p.startswith("Kiểm tra kế hoạch chương")) == 3


async def test_a_contract_that_stays_unmet_replans_the_chapter_once(concurrent_session_factory: Factory, tmp_path):
    store = await _store(concurrent_session_factory)
    model = ScriptedModel()
    replanned: list[str] = []

    def plan(prompt: str, _schema: dict[str, Any]) -> dict[str, Any]:
        if "[Yêu cầu sửa kế hoạch]" in prompt:
            replanned.append(prompt)
            return {**STRUCTURED["chapter_goal"], "chapter_goal": "Minh về nhà và thấy cuốn sổ"}
        return STRUCTURED["chapter_goal"]

    def audit(prompt: str, _schema: dict[str, Any]) -> dict[str, Any]:
        if replanned or "GHI CHÚ CHƯƠNG" not in prompt or "[Chương 1 cần thẩm định]" not in prompt:
            return {"issues": []}
        quote = model.paragraphs[-1].split(". ")[0] + "."
        issue = {
            "severity": "critical",
            "issue_type": "do_not_violated",
            "description": "mục bắt buộc phạm mục cấm",
            "quote": quote,
            "suggested_fix": "lập lại kế hoạch",
        }
        return {"issues": [issue]}

    model.overrides["chapter_goal"] = plan
    model.overrides["issues"] = audit

    state = await _driver(concurrent_session_factory, store, model, StoryBlobStore(tmp_path)).run()

    assert state.phase is RunPhase.READY_FOR_APPROVAL, state.block_reason
    assert len(replanned) == 1
    assert "mục bắt buộc phạm mục cấm" in replanned[0]
    assert len(state.intents["chapter_plan[1]"]) == 1
    assert not any(n.startswith("scene_draft[1,") for n in state.intents)
    assert any(a.step_id.startswith("scene_draft[1,1]@r0.0.1#") for a in state.attempts)


async def test_a_replanned_chapter_that_still_fails_is_blocked_with_its_findings(
    concurrent_session_factory: Factory, tmp_path
):
    store = await _store(concurrent_session_factory)
    model = ScriptedModel()

    def audit(prompt: str, _schema: dict[str, Any]) -> dict[str, Any]:
        if "GHI CHÚ CHƯƠNG" not in prompt or "[Chương 1 cần thẩm định]" not in prompt:
            return {"issues": []}
        quote = prompt.rsplit("\n\n", 1)[-1].split(". ")[0] + "."
        issue = {
            "severity": "critical",
            "issue_type": "withheld_card_revealed",
            "description": "lộ bài",
            "quote": quote,
            "suggested_fix": "giấu",
        }
        return {"issues": [issue]}

    model.overrides["issues"] = audit

    state = await _driver(concurrent_session_factory, store, model, StoryBlobStore(tmp_path)).run()

    assert state.phase is RunPhase.BLOCKED_QUALITY
    assert len(state.intents["chapter_plan[1]"]) == 1
    assert state.blocked_findings

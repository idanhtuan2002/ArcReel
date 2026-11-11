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
from server.story_authoring.checks import count_syllables
from server.story_authoring.commit import load_offered_manifest
from server.story_authoring.contracts import StoryLimits, StoryModelSelection
from server.story_authoring.driver import (
    CONFIRM_MAX,
    PLAN_REPLANS,
    REVIEW_CYCLES,
    StoryBrief,
    StoryRunDriver,
    run_call_bound,
)
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
from server.story_authoring.service import DEFAULT_LIMITS
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

PRIOR_TEXT = (
    "Minh về làng sau mười năm. Lan, em gái anh, giữ căn nhà của cha.\n\n"
    "Hai anh em tìm thấy cuốn sổ nợ trong hòm áo cũ. Trang cuối ghi tên một người lạ.\n\n"
    "Đêm đó, có tiếng gõ cửa. Minh mở cửa và không thấy ai, chỉ có một phong thư."
)
CHAPTER_DIGEST = {
    "summary": "Minh về căn nhà cũ và thấy cuốn sổ nợ của cha.",
    "events": ["Minh về làng."],
    "characters": [{"name": "Minh", "state": "cầm cuốn sổ"}],
    "hooks": [],
    "new_threads": [],
    "time_place": "chiều tối, căn nhà cũ",
}
PRIOR_SUMMARY = {
    "events": ["Minh về làng.", "Hai anh em tìm thấy sổ nợ.", "Có người để lại phong thư."],
    "characters": [{"name": "Minh", "state": "đang cầm phong thư"}, {"name": "Lan", "state": "lo lắng"}],
    "open_threads": ["Ai để lại phong thư?"],
    "places": ["căn nhà của cha"],
}
CANON_LOCK = {
    "title_hint": "Căn nhà cũ",
    "genre": "đời thường",
    "tone": "trầm",
    "pov": "ngôi thứ ba",
    "characters": [
        {
            "name": name,
            "role": "nhân vật",
            "relation_to_protagonist": "anh em",
            "description": "người làng",
            "current_state": "ở nhà cha",
        }
        for name in ("Minh", "Lan", "Tuấn")
    ],
    "places": [],
    "chapter_events": ["Minh về làng.", "Có phong thư."],
    "open_threads": ["Ai để lại phong thư?"],
    "ending_state": "Minh cầm phong thư trước cửa.",
    "style_notes": "câu ngắn",
}

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
                "relation_to_protagonist": "chính là nhân vật chính",
                "description": "con trai cả",
                "goal": "bán nhà",
                "gender": "nam",
                "address": "anh",
                "voice": "nói ngắn, ít cảm thán",
                "flaw": "ngại đối mặt chuyện cũ",
                "age": 34,
            },
            {
                "name": "Lan",
                "role": "phụ",
                "relation_to_protagonist": "em gái Minh",
                "description": "ở lại làng",
                "goal": "giữ nhà",
                "gender": "nữ",
                "address": "cô",
                "voice": "nói nhỏ, hay hỏi lại",
                "flaw": "giữ mọi chuyện trong lòng",
                "age": 29,
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
            {
                "core_task": "trở về",
                "threads_advanced": "nợ",
                "turning_point": "cuốn sổ",
                "obstacle": "Lan",
                "choice": "ở lại",
                "ending_question": "ai ghi nợ?",
            },
            {
                "core_task": "giằng co",
                "threads_advanced": "nợ",
                "turning_point": "người mua",
                "obstacle": "Lan",
                "choice": "ở lại",
                "ending_question": "ai ghi nợ?",
            },
            {
                "core_task": "quyết định",
                "threads_advanced": "nợ",
                "turning_point": "trả nợ",
                "obstacle": "Lan",
                "choice": "ở lại",
                "ending_question": "ai ghi nợ?",
            },
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
        "closing_hook": "Ai đã ghi món nợ ấy vào cuốn sổ?",
    },
}


class ScriptedModel:
    """Answers by the request's schema. ``overrides`` replace an answer kind, ``fail_at`` breaks a call number of a
    kind, ``fail_from`` breaks every call of a kind from a call number on, and ``before`` runs a hook before a call
    number of a kind is answered."""

    _instances = 0

    def __init__(self, model_name: str = MODEL) -> None:
        self.model_name = model_name
        self.calls: Counter[str] = Counter()
        self.prompts: list[tuple[str, str]] = []
        self.paragraphs: list[str] = []
        self.overrides: dict[str, Answer] = {}
        self.fail_at: dict[str, int] = {}
        self.fail_from: dict[str, int] = {}
        self.truncate_at: dict[str, int] = {}
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

    def last_sentence(self) -> str:
        return self.paragraphs[-1].rsplit(". ", 1)[-1]

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
        if kind == "confirmed":
            return {"confirmed": True, "quote": self.last_sentence()}
        if kind == "ending_resolves_conflict":
            return {"ending_resolves_conflict": True, "ending_quote": self.last_sentence(), "issues": []}
        if kind == "issues":
            return {"issues": []}
        if kind == "titles":
            return self.packaging()
        if kind == "unsupported":
            return {"unsupported": []}
        if kind == "checks":
            return {"checks": []}
        if kind == "patches":
            return {"patches": [], "notes": "không sửa"}
        if kind == "rewrites":
            return {"rewrites": []}
        if kind == "contradicted":
            return {"missing": [], "contradicted": [], "notes": []}
        if kind == "time_place":
            return CHAPTER_DIGEST
        if kind == "events":
            return PRIOR_SUMMARY
        if kind == "title_hint":
            return CANON_LOCK
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
                for k in (
                    *STRUCTURED,
                    "time_place",
                    "events",
                    "title_hint",
                    "confirmed",
                    "ending_resolves_conflict",
                    "issues",
                    "titles",
                    "unsupported",
                    "checks",
                    "patches",
                    "rewrites",
                    "contradicted",
                )
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
            if self.fail_at.get(kind) == self.calls[kind] or self.calls[kind] >= self.fail_from.get(kind, 10**9):
                return httpx.Response(500, json={"error": "model crashed"})
            if self.truncate_at.get(kind) == self.calls[kind]:
                return httpx.Response(
                    200,
                    json={
                        "model": self.model_name,
                        "message": {"role": "assistant", "content": '{"issues": [{"severity": "crit'},
                        "done": True,
                        "done_reason": "length",
                        "prompt_eval_count": 700,
                        "eval_count": 2048,
                    },
                )
            content = json.dumps(self._answer(kind, schema, prompt), ensure_ascii=False)
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


async def _store(factory: Factory, limits: StoryLimits = LIMITS) -> RunStateStore:
    async with factory() as session:
        task = await TaskRepository(session).enqueue(
            project_name=IDENTITY.project_name, task_type=STORY_RUN_TASK_TYPE, media_type="text", resource_id="run1"
        )
    store = RunStateStore(factory, task_id=task["task_id"])
    await store.initialize(new_run_state(run_id=IDENTITY.run_id, limits=limits, now=NOW))
    return store


def _driver(
    factory: Factory, store: RunStateStore, model: ScriptedModel, blobs: StoryBlobStore, brief: StoryBrief = BRIEF
) -> StoryRunDriver:
    client = OllamaChatClient(base_url="http://ollama:1", transport=httpx.MockTransport(model.handler))
    sink = StoryAttemptSink(store=store, session_factory=factory, provider_id="custom-ollama", model_id=MODEL)
    gateway = AuthoringTextGateway(selection=SELECTION, limits=LIMITS, client=client, sink=sink)
    return StoryRunDriver(
        identity=IDENTITY,
        brief=brief,
        store=store,
        gateway=gateway,
        blobs=blobs,
        clock=lambda: NOW,
        retry_delays=(0, 0),
    )


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
    flat = " ".join(export.split())
    assert all(" ".join(s.revision.normalized_content.split()) in flat for s in manifest.scenes)
    assert model.calls["prose"] == 9
    assert model.calls["issues"] == 18
    assert (model.calls["ending_resolves_conflict"], model.calls["titles"]) == (1, 1)


async def test_a_short_story_carries_what_each_chapter_wrote_into_the_next(
    concurrent_session_factory: Factory, tmp_path
):
    store = await _store(concurrent_session_factory)
    model = ScriptedModel()
    brief = BRIEF.model_copy(update={"carries_digests": True})

    state = await _driver(concurrent_session_factory, store, model, StoryBlobStore(tmp_path), brief).run()

    assert state.phase is RunPhase.READY_FOR_APPROVAL, state.block_reason
    assert model.calls["time_place"] == 2  # chapters 1 and 2; the last chapter has no next one
    later = [prompt for kind, prompt in model.prompts if kind == "prose" and "[Đã xảy ra ở các chương trước" in prompt]
    assert len(later) == 6
    assert all(CHAPTER_DIGEST["summary"] in prompt for prompt in later)
    assert "chiều tối, căn nhà cũ" in later[0]
    continuity = [p for kind, p in model.prompts if kind == "issues" and "[Chương 2 cần thẩm định]" in p]
    assert any(CHAPTER_DIGEST["summary"] in p for p in continuity)
    again = ScriptedModel()
    await _rerun(store)
    await _driver(concurrent_session_factory, store, again, StoryBlobStore(tmp_path), brief).run()
    assert sum(again.calls.values()) == 0


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
    crashing.fail_from["prose"] = 5

    stopped = await _driver(concurrent_session_factory, store, crashing, blobs).run()
    assert stopped.phase is RunPhase.MODEL_UNAVAILABLE
    assert stopped.commit is None
    assert crashing.calls["prose"] == 7

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
    assert revised.calls["issues"] == 6
    assert "Cho Lan nói nhiều hơn." in next(p for k, p in revised.prompts if k == "prose")


async def test_a_scene_whose_calls_are_spent_keeps_its_best_version_when_an_earlier_scene_changes(
    concurrent_session_factory: Factory, tmp_path
):
    store = await _store(concurrent_session_factory)
    blobs = StoryBlobStore(tmp_path)
    first = ScriptedModel()
    full = first._prose

    def code_mixed(prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        count = schema["properties"]["paragraphs"]["minItems"]
        answer = full(count)
        if "Viết cảnh 2 của chương 1." in prompt:
            opening = (
                answer["paragraphs"][0].rsplit(". ", 1)[0] + ". Minh lướt smartphone suốt weekend, shopping thật nhiều."
            )
            answer["paragraphs"][0] = first.paragraphs[-count] = opening
        return answer

    first.overrides["prose"] = code_mixed
    drafted = await _driver(concurrent_session_factory, store, first, blobs).run()
    assert drafted.phase is RunPhase.READY_FOR_APPROVAL, drafted.block_reason
    assert first.calls["patches"] == 5

    await _rerun(store, intent=(scene_draft(1, 1), "Cho Lan nói nhiều hơn."))
    revised = ScriptedModel()
    state = await _driver(concurrent_session_factory, store, revised, blobs).run()

    assert state.phase is RunPhase.READY_FOR_APPROVAL, state.block_reason
    assert not any("Viết cảnh 2 của chương 1." in p for k, p in revised.prompts if k == "prose")
    kept = [f for f in _exceptions(blobs, state) if f["code"] == "BEST_VERSION_KEPT"]
    assert [(f["node_id"], f["severity"]) for f in kept] == [(scene_draft(1, 2), "NARRATIVE_CRITICAL")]


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
        flagged.append(model.paragraphs[1].split(". ")[0] + ".")
        issue = {
            "severity": "critical",
            "issue_type": "mâu_thuẫn",
            "description": "sai thời điểm",
            "quote": flagged[0],
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
    assert model.calls["issues"] == 24


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
        return {"ending_resolves_conflict": resolved, "ending_quote": model.last_sentence(), "issues": []}

    return answer


async def test_an_unresolved_ending_rewrites_the_final_scene_once(concurrent_session_factory: Factory, tmp_path):
    store = await _store(concurrent_session_factory)
    model = ScriptedModel()
    model.overrides["ending_resolves_conflict"] = _critic(model, [False, True])

    state = await _driver(concurrent_session_factory, store, model, StoryBlobStore(tmp_path)).run()

    assert state.phase is RunPhase.READY_FOR_APPROVAL, state.block_reason
    assert (model.calls["prose"], model.calls["ending_resolves_conflict"]) == (10, 2)
    assert model.calls["issues"] == 24
    last_prose_prompt = [p for k, p in model.prompts if k == "prose"][-1]
    assert "chưa khép lại xung đột trung tâm" in last_prose_prompt


def _exceptions(blobs: StoryBlobStore, state) -> list[dict[str, Any]]:
    manifest = load_offered_manifest(blobs, state)
    assert manifest.quality_record_digest is not None
    record = json.loads(blobs.read_exact(manifest.quality_record_digest))
    return [f for f in record["findings"] if f["id"] in manifest.exceptions_offered]


async def test_an_ending_that_stays_unresolved_reaches_the_human_after_the_rewrite(
    concurrent_session_factory: Factory, tmp_path
):
    store = await _store(concurrent_session_factory)
    model = ScriptedModel()
    model.overrides["ending_resolves_conflict"] = _critic(model, [False])
    blobs = StoryBlobStore(tmp_path)

    state = await _driver(concurrent_session_factory, store, model, blobs).run()

    assert state.phase is RunPhase.READY_FOR_APPROVAL, state.block_reason
    # The final scene is rewritten once, then the last chapter is replanned once toward the outline's ending (here
    # the scripted plan comes back the same, so its scenes stand) and the ending is judged a third time.
    assert (model.calls["prose"], model.calls["ending_resolves_conflict"]) == (10, 3)
    flagged = [f for f in _exceptions(blobs, state) if f["code"] == "NO_ENDING"]
    assert [f["severity"] for f in flagged] == ["NARRATIVE_CRITICAL"]
    assert flagged[0]["message"].startswith("[hết lượt sửa tự động] ")


async def test_an_unconfirmed_unresolved_ending_reaches_the_human_as_an_exception(
    concurrent_session_factory: Factory, tmp_path
):
    store = await _store(concurrent_session_factory)
    model = ScriptedModel()
    model.overrides["ending_resolves_conflict"] = _critic(model, [False])
    model.overrides["confirmed"] = lambda _prompt, _schema: {"confirmed": False, "quote": model.last_sentence()}

    state = await _driver(concurrent_session_factory, store, model, StoryBlobStore(tmp_path)).run()

    assert state.phase is RunPhase.READY_FOR_APPROVAL, state.block_reason
    assert (model.calls["prose"], model.calls["ending_resolves_conflict"], model.calls["confirmed"]) == (9, 1, 1)
    confirm_prompt = [p for k, p in model.prompts if k == "confirmed"][-1]
    assert "theo kết thúc đã duyệt" in confirm_prompt
    blobs = StoryBlobStore(tmp_path)
    manifest = load_offered_manifest(blobs, state)
    assert manifest.quality_record_digest is not None
    record = json.loads(blobs.read_exact(manifest.quality_record_digest))
    assert [f["severity"] for f in record["findings"] if f["code"] == "NO_ENDING"] == ["NARRATIVE_CRITICAL"]


async def test_packaging_without_three_quoted_selling_points_reaches_the_human_after_its_tries(
    concurrent_session_factory: Factory, tmp_path
):
    store = await _store(concurrent_session_factory)
    model = ScriptedModel()
    blobs = StoryBlobStore(tmp_path)

    def invented(_prompt: str, _schema: dict[str, Any]) -> dict[str, Any]:
        answer = model.packaging()
        answer["selling_points"][0]["evidence_quote"] = "Một câu không có trong truyện."
        return answer

    model.overrides["titles"] = invented

    state = await _driver(concurrent_session_factory, store, model, blobs).run()

    assert state.phase is RunPhase.READY_FOR_APPROVAL, state.block_reason
    assert model.calls["titles"] == 2
    flagged = [f for f in _exceptions(blobs, state) if f["code"] == "SELLING_POINT_UNVERIFIED"]
    assert [(f["severity"], f["quote"]) for f in flagged] == [("NARRATIVE_CRITICAL", "Một câu không có trong truyện.")]


async def test_a_blurb_claim_the_manuscript_lacks_reaches_the_human_and_stays_out_of_the_export(
    concurrent_session_factory: Factory, tmp_path
):
    store = await _store(concurrent_session_factory)
    model = ScriptedModel()
    model.overrides["unsupported"] = lambda _prompt, _schema: {
        "unsupported": [{"blurb": 1, "claim": "Nhà sắp bị phá dỡ", "reason": "truyện không có"}]
    }
    model.overrides["checks"] = lambda _prompt, _schema: {"checks": [{"claim": 1, "quote": "", "supported": False}]}
    model.overrides["titles"] = lambda _prompt, _schema: {
        **model.packaging(),
        "blurbs": ["Nhà sắp bị phá dỡ. Minh về làng.", "Minh tìm thấy cuốn sổ."],
    }
    blobs = StoryBlobStore(tmp_path)

    state = await _driver(concurrent_session_factory, store, model, blobs).run()

    assert state.phase is RunPhase.READY_FOR_APPROVAL, state.block_reason
    assert (model.calls["titles"], model.calls["unsupported"], model.calls["checks"]) == (1, 1, 1)
    manifest = load_offered_manifest(blobs, state)
    export = blobs.read_exact(manifest.export_digest).decode("utf-8")
    assert "> Minh tìm thấy cuốn sổ." in export
    assert manifest.quality_record_digest is not None
    record = json.loads(blobs.read_exact(manifest.quality_record_digest))
    flagged = [f for f in record["findings"] if f["code"] == "BLURB_UNSUPPORTED"]
    assert [(f["severity"], f["quote"]) for f in flagged] == [("NARRATIVE_CRITICAL", "Nhà sắp bị phá dỡ")]
    assert flagged[0]["id"] in manifest.exceptions_offered
    assert record["packaging"]["blurbs"] == ["Minh tìm thấy cuốn sổ.", "Nhà sắp bị phá dỡ. Minh về làng."]


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


async def test_a_story_outside_the_target_length_is_offered_with_a_stylistic_finding(
    concurrent_session_factory: Factory, tmp_path
):
    store = await _store(concurrent_session_factory)
    blobs = StoryBlobStore(tmp_path)
    model = ScriptedModel()
    full = model._prose

    def lean(_prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        answer = full(schema["properties"]["paragraphs"]["minItems"])
        paragraphs = [". ".join(p.split(". ")[:6]).rstrip(".") + "." for p in answer["paragraphs"]]
        model.paragraphs[-len(paragraphs) :] = paragraphs
        return {"paragraphs": paragraphs}

    model.overrides["prose"] = lean

    state = await _driver(concurrent_session_factory, store, model, blobs).run()

    assert state.phase is RunPhase.READY_FOR_APPROVAL, state.block_reason
    manifest = load_offered_manifest(blobs, state)
    assert manifest.quality_record_digest is not None
    record = json.loads(blobs.read_exact(manifest.quality_record_digest))
    assert [f["severity"] for f in record["findings"] if f["code"] == "STORY_LENGTH"] == ["STYLISTIC"]
    assert sum(count_syllables(s.revision.normalized_content) for s in manifest.scenes) < 7000


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
        flagged.append(model.last_sentence())
        issue = {
            "severity": "critical",
            "issue_type": "required_change_missing",
            "description": "Minh chưa thấy cuốn sổ",
            "quote": model.last_sentence(),
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
    assert scene_steps == {f"{scene_draft(1, 3)}@r0.0.0#1", f"{scene_draft(1, 3)}@r0.0.0+1#1"}


async def test_a_withheld_card_that_stays_revealed_is_patched_replanned_then_offered_to_the_human(
    concurrent_session_factory: Factory, tmp_path
):
    store = await _store(concurrent_session_factory)
    model = ScriptedModel()
    blobs = StoryBlobStore(tmp_path)

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

    state = await _driver(concurrent_session_factory, store, model, blobs).run()

    assert state.phase is RunPhase.READY_FOR_APPROVAL, state.block_reason
    assert model.calls["patches"] >= 1
    assert not any(n.startswith("scene_draft[") for n in state.intents)
    assert len(state.intents["chapter_plan[1]"]) == PLAN_REPLANS
    exceptions = _exceptions(blobs, state)
    assert {f["code"] for f in exceptions} == {"MEMO_COMPLIANCE:withheld_card_revealed"}
    assert all(f["message"].startswith("[hết lượt sửa tự động] ") and f["quote"] for f in exceptions)


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
            answer["paragraphs"][0] = copied[0] + " " + answer["paragraphs"][0].split(". ", 1)[1]
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
    # The replanned chapter passes, so no further replan is asked for.
    assert len(state.intents["chapter_plan[1]"]) == 1
    assert not any(n.startswith("scene_draft[1,") for n in state.intents)
    assert any(a.step_id.startswith("scene_draft[1,1]@r0.0.1#") for a in state.attempts)


async def test_a_required_change_that_stays_missing_reaches_the_human_after_the_replan(
    concurrent_session_factory: Factory, tmp_path
):
    # Every replan of the chapter fails too: the run needs the structural bound that counts them.
    bound = run_call_bound()
    store = await _store(
        concurrent_session_factory,
        LIMITS.model_copy(update={"generate_calls_max": bound, "count_calls_max": bound}),
    )
    model = ScriptedModel()
    blobs = StoryBlobStore(tmp_path)

    def audit(prompt: str, _schema: dict[str, Any]) -> dict[str, Any]:
        if "GHI CHÚ CHƯƠNG" not in prompt or "[Chương 1 cần thẩm định]" not in prompt:
            return {"issues": []}
        quote = prompt.rsplit("\n\n", 1)[-1].split(". ")[0] + "."
        issue = {
            "severity": "critical",
            "issue_type": "required_change_missing",
            "description": "Minh chưa thấy cuốn sổ",
            "quote": quote,
            "suggested_fix": "cho Minh thấy cuốn sổ",
        }
        return {"issues": [issue]}

    model.overrides["issues"] = audit

    state = await _driver(concurrent_session_factory, store, model, blobs).run()

    assert state.phase is RunPhase.READY_FOR_APPROVAL, state.block_reason
    assert len(state.intents["chapter_plan[1]"]) == PLAN_REPLANS
    assert {f["code"] for f in _exceptions(blobs, state)} == {"MEMO_COMPLIANCE:required_change_missing"}


async def test_an_unconfirmed_blocking_claim_reaches_the_human_as_an_exception(
    concurrent_session_factory: Factory, tmp_path
):
    store = await _store(concurrent_session_factory)
    model = ScriptedModel()
    blobs = StoryBlobStore(tmp_path)

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
    model.overrides["confirmed"] = lambda _p, _s: {"confirmed": False, "quote": model.last_sentence()}

    state = await _driver(concurrent_session_factory, store, model, blobs).run()

    assert state.phase is RunPhase.READY_FOR_APPROVAL, state.block_reason
    assert not state.intents
    manifest = load_offered_manifest(blobs, state)
    assert manifest.quality_record_digest is not None
    record = json.loads(blobs.read_exact(manifest.quality_record_digest))
    exceptions = [f for f in record["findings"] if f["id"] in manifest.exceptions_offered]
    assert {f["code"] for f in exceptions} == {"MEMO_COMPLIANCE:withheld_card_revealed"}
    assert all(f["message"].startswith("[chưa kiểm chứng] ") for f in exceptions)
    assert all(f["severity"] == "NARRATIVE_CRITICAL" for f in exceptions)


async def test_a_truncated_audit_is_retried_under_a_new_step(concurrent_session_factory: Factory, tmp_path):
    store = await _store(concurrent_session_factory)
    model = ScriptedModel()
    model.truncate_at["issues"] = 2

    state = await _driver(concurrent_session_factory, store, model, StoryBlobStore(tmp_path)).run()

    assert state.phase is RunPhase.READY_FOR_APPROVAL, state.block_reason
    assert model.calls["issues"] == 19


JUDGE = StoryModelSelection.create(
    provider_id="custom-judge",
    endpoint="ollama-chat",
    base_url="http://judge:1",
    model_id="judge-12b",
    has_credential=False,
)


async def test_review_calls_go_to_the_judge_route_and_drafting_stays_with_the_writer(
    concurrent_session_factory: Factory, tmp_path
):
    store = await _store(concurrent_session_factory)
    writer, judge = ScriptedModel(), ScriptedModel("judge-12b")
    judge.paragraphs = writer.paragraphs
    brief = BRIEF.model_copy(update={"judge_selection": JUDGE})

    def gateway(model: ScriptedModel, selection: StoryModelSelection, base: str) -> AuthoringTextGateway:
        client = OllamaChatClient(base_url=base, transport=httpx.MockTransport(model.handler))
        sink = StoryAttemptSink(
            store=store,
            session_factory=concurrent_session_factory,
            provider_id=selection.provider_id,
            model_id=selection.model_id,
        )
        return AuthoringTextGateway(selection=selection, limits=LIMITS, client=client, sink=sink)

    driver = StoryRunDriver(
        identity=IDENTITY,
        brief=brief,
        store=store,
        gateway=gateway(writer, SELECTION, "http://ollama:1"),
        judge_gateway=gateway(judge, JUDGE, "http://judge:1"),
        blobs=StoryBlobStore(tmp_path),
        clock=lambda: NOW,
    )

    state = await driver.run()

    assert state.phase is RunPhase.READY_FOR_APPROVAL, state.block_reason
    assert set(judge.calls) == {"passed", "issues", "ending_resolves_conflict", "unsupported"}
    assert judge.calls["issues"] == 18
    assert not {"passed", "issues", "ending_resolves_conflict", "unsupported"} & set(writer.calls)
    assert writer.calls["prose"] == 9


def test_a_judge_gateway_must_match_the_brief():
    with pytest.raises(ValueError, match="judge"):
        StoryRunDriver(
            identity=IDENTITY,
            brief=BRIEF.model_copy(update={"judge_selection": JUDGE}),
            store=None,
            gateway=None,
            blobs=None,
        )


def test_the_judge_route_is_part_of_what_gate_a_greenlights():
    assert BRIEF.model_copy(update={"judge_selection": JUDGE}).digest() != BRIEF.digest()
    assert BRIEF.judge == SELECTION


async def test_a_collective_character_outside_the_bible_does_not_stop_the_plan(
    concurrent_session_factory: Factory, tmp_path
):
    store = await _store(concurrent_session_factory)
    model = ScriptedModel()
    schemas: list[dict[str, Any]] = []

    def plan(_prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        schemas.append(schema)
        scenes = [{**_scene(i), "characters": ["Minh", "Lũ trẻ"]} for i in (1, 2, 3)]
        return {**STRUCTURED["chapter_goal"], "scenes": scenes}

    model.overrides["chapter_goal"] = plan

    state = await _driver(concurrent_session_factory, store, model, StoryBlobStore(tmp_path)).run()

    assert state.phase is RunPhase.READY_FOR_APPROVAL, state.block_reason
    assert model.calls["chapter_goal"] == 3
    planned = schemas[0]["properties"]["scenes"]["items"]
    assert planned["properties"]["pov"]["enum"] == ["Minh", "Lan"]
    assert planned["properties"]["location"]["enum"] == ["Căn nhà cũ"]
    assert "Lũ trẻ" in next(p for k, p in model.prompts if k == "prose")


async def test_a_revealed_withheld_card_is_patched_in_place_instead_of_regenerating_the_scene(
    concurrent_session_factory: Factory, tmp_path
):
    store = await _store(concurrent_session_factory)
    blobs = StoryBlobStore(tmp_path)
    model = ScriptedModel()
    flagged: list[str] = []

    def audit(prompt: str, _schema: dict[str, Any]) -> dict[str, Any]:
        if flagged or "GHI CHÚ CHƯƠNG" not in prompt:
            return {"issues": []}
        flagged.append(model.paragraphs[1].split(". ")[0] + ".")
        issue = {
            "severity": "critical",
            "issue_type": "withheld_card_revealed",
            "description": "lộ bí mật cuốn sổ",
            "quote": flagged[0],
            "suggested_fix": "bỏ câu này",
        }
        return {"issues": [issue]}

    model.overrides["issues"] = audit
    model.overrides["patches"] = lambda _p, _s: {
        "patches": [{"before": flagged[0], "after": "Minh đứng yên rất lâu bên hiên."}],
        "notes": "giấu bí mật",
    }

    state = await _driver(concurrent_session_factory, store, model, blobs).run()

    assert state.phase is RunPhase.READY_FOR_APPROVAL, state.block_reason
    assert model.calls["patches"] == 1
    assert not state.intents
    assert not any("lộ bí mật cuốn sổ" in p for k, p in model.prompts if k == "prose")
    first_scene = [a for a in state.attempts if a.step_id.startswith(scene_draft(1, 1)) and a.kind.value == "GENERATE"]
    assert len(first_scene) == 2
    manifest = load_offered_manifest(blobs, state)
    assert flagged[0] not in manifest.scenes[0].revision.normalized_content


async def test_a_patch_that_adds_a_blocking_defect_is_not_kept(concurrent_session_factory: Factory, tmp_path):
    store = await _store(concurrent_session_factory)
    blobs = StoryBlobStore(tmp_path)
    model = ScriptedModel()
    flagged: list[str] = []

    def audit(prompt: str, _schema: dict[str, Any]) -> dict[str, Any]:
        if flagged or "TÍNH LIÊN TỤC" not in prompt:
            return {"issues": []}
        flagged.append(model.paragraphs[1].split(". ")[0] + ".")
        issue = {
            "severity": "critical",
            "issue_type": "mâu_thuẫn",
            "description": "sai thời điểm",
            "quote": flagged[0],
            "suggested_fix": "sửa",
        }
        return {"issues": [issue]}

    model.overrides["issues"] = audit
    model.overrides["patches"] = lambda _p, _s: {
        "patches": [{"before": flagged[0], "after": "Minh đứng dậy và\n\nrồi"}],
        "notes": "sửa",
    }

    state = await _driver(concurrent_session_factory, store, model, blobs).run()

    assert state.phase is RunPhase.READY_FOR_APPROVAL, state.block_reason
    assert model.calls["patches"] == 1
    manifest = load_offered_manifest(blobs, state)
    assert flagged[0] in manifest.scenes[0].revision.normalized_content
    assert "Minh đứng dậy và" not in manifest.scenes[0].revision.normalized_content


async def test_a_story_that_stays_under_the_hard_length_reaches_the_human_as_an_exception(
    concurrent_session_factory: Factory, tmp_path
):
    store = await _store(concurrent_session_factory)
    blobs = StoryBlobStore(tmp_path)
    model = ScriptedModel()
    full = model._prose

    def at_the_floor(_prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        answer = full(schema["properties"]["paragraphs"]["minItems"])
        paragraphs = []
        for paragraph in answer["paragraphs"]:
            kept = ""
            for sentence in paragraph.split(". "):
                kept = f"{kept} {sentence.rstrip('.')}.".strip()
                if len(kept) >= 280:
                    break
            paragraphs.append(kept)
        model.paragraphs[-len(paragraphs) :] = paragraphs
        return {"paragraphs": paragraphs}

    model.overrides["prose"] = at_the_floor

    state = await _driver(concurrent_session_factory, store, model, blobs).run()

    assert state.phase is RunPhase.READY_FOR_APPROVAL, state.block_reason
    flagged = [f for f in _exceptions(blobs, state) if f["code"] == "STORY_LENGTH"]
    assert [f["severity"] for f in flagged] == ["NARRATIVE_CRITICAL"]
    assert flagged[0]["message"].startswith("[hết lượt sửa tự động] ")


async def test_a_transient_model_outage_is_retried_without_stopping_the_run(
    concurrent_session_factory: Factory, tmp_path
):
    store = await _store(concurrent_session_factory)
    model = ScriptedModel()
    model.fail_at["prose"] = 5
    model.fail_at["issues"] = 3

    state = await _driver(concurrent_session_factory, store, model, StoryBlobStore(tmp_path)).run()

    assert state.phase is RunPhase.READY_FOR_APPROVAL, state.block_reason
    assert model.calls["prose"] == 10
    failed = [a for a in state.attempts if a.failure_code is not None]
    assert {a.failure_code.value for a in failed} == {"PROVIDER_ERROR"}
    assert len(failed) == 2


async def test_a_story_whose_every_review_fails_reaches_the_human_inside_the_default_budget(
    concurrent_session_factory: Factory, tmp_path
):
    store = await _store(concurrent_session_factory, DEFAULT_LIMITS)
    model = ScriptedModel()
    blobs = StoryBlobStore(tmp_path)

    def audit(prompt: str, _schema: dict[str, Any]) -> dict[str, Any]:
        if "GHI CHÚ CHƯƠNG" not in prompt:
            return {"issues": []}
        paragraphs = prompt.split("cần thẩm định]\n", 1)[1].split("\n\n")
        issue = {
            "severity": "critical",
            "issue_type": "required_change_missing",
            "description": "Minh chưa thấy cuốn sổ",
            "suggested_fix": "cho Minh thấy cuốn sổ",
        }
        return {"issues": [{**issue, "quote": p.split(". ")[0] + "."} for p in paragraphs[:6]]}

    model.overrides["issues"] = audit
    model.overrides["passed"] = lambda _p, _s: {"passed": False, "problems": ["mục cấm mâu thuẫn mục bắt buộc"]}
    model.overrides["chapter_goal"] = lambda _p, _s: {
        **STRUCTURED["chapter_goal"],
        "chapter_goal": f"mục tiêu lần {model.calls['chapter_goal']}",
    }

    state = await _driver(concurrent_session_factory, store, model, blobs).run()

    assert state.phase is RunPhase.READY_FOR_APPROVAL, state.block_reason
    assert all(len(state.intents[f"chapter_plan[{c}]"]) == PLAN_REPLANS for c in (1, 2, 3))
    plan_3 = {a.step_id.rsplit("#", 1)[0] for a in state.attempts if a.step_id.startswith("chapter_plan[3]")}
    # Its first round, then one for each replan of chapters 1 to 3 (each regenerates every later plan).
    assert len(plan_3) == 1 + 3 * PLAN_REPLANS
    assert {f["code"] for f in _exceptions(blobs, state)} == {"MEMO_COMPLIANCE:required_change_missing"}
    assert state.usage.generate_calls <= run_call_bound(scenes_per_chapter=3)
    reviews = {a.step_id.rsplit("#", 1)[0] for a in state.attempts if a.step_id.startswith("chapter_review[")}
    assert model.calls["confirmed"] <= len(reviews) * (REVIEW_CYCLES + 1) * CONFIRM_MAX


async def test_a_scene_the_review_asks_to_rewrite_twice_has_calls_for_each_rewrite(
    concurrent_session_factory: Factory, tmp_path
):
    store = await _store(concurrent_session_factory)
    model = ScriptedModel()
    full = model._prose
    memo_calls: list[str] = []
    broken: list[int] = []

    def audit(prompt: str, _schema: dict[str, Any]) -> dict[str, Any]:
        if "GHI CHÚ CHƯƠNG" not in prompt or "[Chương 1 cần thẩm định]" not in prompt:
            return {"issues": []}
        memo_calls.append(prompt)
        if len(memo_calls) > 2:
            return {"issues": []}
        issue = {
            "severity": "critical",
            "issue_type": "required_change_missing",
            "description": "Minh chưa thấy cuốn sổ",
            "quote": prompt.rsplit("\n\n", 1)[-1].split(". ")[0] + ".",
            "suggested_fix": "cho Minh thấy cuốn sổ",
        }
        return {"issues": [issue]}

    def prose(prompt: str, schema: dict[str, Any]) -> dict[str, Any]:
        if "yêu cầu viết lại cảnh này" in prompt and len(broken) < 4:
            broken.append(1)
            return {"paragraphs": ["ngắn"] * schema["properties"]["paragraphs"]["minItems"]}
        return full(schema["properties"]["paragraphs"]["minItems"])

    model.overrides["issues"] = audit
    model.overrides["prose"] = prose

    state = await _driver(concurrent_session_factory, store, model, StoryBlobStore(tmp_path)).run()

    assert state.phase is RunPhase.READY_FOR_APPROVAL, state.block_reason
    assert len(state.intents[scene_draft(1, 3)]) == 2
    rounds = {a.step_id.rsplit("#", 1)[0] for a in state.attempts if a.step_id.startswith(scene_draft(1, 3))}
    assert rounds == {f"{scene_draft(1, 3)}@r0.0.0", f"{scene_draft(1, 3)}@r0.0.0+1", f"{scene_draft(1, 3)}@r0.0.0+2"}


def _prior_driver(factory, store, model, blobs, mode):
    from server.story_authoring.driver import StoryPrior

    digest = blobs.put(PRIOR_TEXT.encode("utf-8"))
    brief = BRIEF.model_copy(update={"prior": StoryPrior(mode=mode, text_digest=digest)})
    client = OllamaChatClient(base_url="http://ollama:1", transport=httpx.MockTransport(model.handler))
    sink = StoryAttemptSink(store=store, session_factory=factory, provider_id="custom-ollama", model_id=MODEL)
    gateway = AuthoringTextGateway(selection=SELECTION, limits=LIMITS, client=client, sink=sink)
    driver = StoryRunDriver(
        identity=IDENTITY,
        brief=brief,
        store=store,
        gateway=gateway,
        blobs=blobs,
        clock=lambda: NOW,
        retry_delays=(0, 0),
    )
    return driver, brief


async def test_a_continuation_reads_the_prior_story_and_opens_where_it_ended(concurrent_session_factory, tmp_path):
    store = await _store(concurrent_session_factory)
    model = ScriptedModel()
    blobs = StoryBlobStore(tmp_path)
    driver, brief = _prior_driver(concurrent_session_factory, store, model, blobs, "continuation")

    state = await driver.run()

    assert state.phase is RunPhase.READY_FOR_APPROVAL, state.block_reason
    assert (model.calls["events"], model.calls["title_hint"]) == (1, 1)
    lock = json.loads(blobs.read_exact(state.revisions[state.node("canon_lock").head_revision_id].digest))
    assert [c["name"] for c in lock["characters"]] == ["Minh", "Lan"]  # "Tuấn" is never named in the prior text
    seed_prompt = next(prompt for kind, prompt in model.prompts if kind == "working_title")
    assert "PHẦN 2" in seed_prompt
    assert "Ai để lại phong thư?" in seed_prompt
    assert all("BẢN KHÓA CANON" in prompt for kind, prompt in model.prompts if kind in {"logline", "story_arc"})
    prose = [prompt for kind, prompt in model.prompts if kind == "prose"]
    assert "PHẦN TRƯỚC KẾT THÚC" in prose[0]
    assert "chỉ có một phong thư" in prose[0]
    assert not any("PHẦN TRƯỚC KẾT THÚC" in prompt for prompt in prose[1:])
    assert "prior" in brief.model_dump(mode="json")


async def test_a_variant_reads_the_whole_story_and_never_opens_on_its_ending(concurrent_session_factory, tmp_path):
    store = await _store(concurrent_session_factory)
    model = ScriptedModel()
    blobs = StoryBlobStore(tmp_path)
    driver, _ = _prior_driver(concurrent_session_factory, store, model, blobs, "variant")

    state = await driver.run()

    assert state.phase is RunPhase.READY_FOR_APPROVAL, state.block_reason
    seed_prompt = next(prompt for kind, prompt in model.prompts if kind == "working_title")
    assert "PHIÊN BẢN KHÁC" in seed_prompt
    assert not any("PHẦN TRƯỚC KẾT THÚC" in prompt for kind, prompt in model.prompts if kind == "prose")


def test_a_brief_without_a_prior_keeps_its_digest():
    assert "prior" not in BRIEF.model_dump(mode="json")


def _quality(blobs: StoryBlobStore, state) -> list[dict[str, Any]]:
    manifest = load_offered_manifest(blobs, state)
    assert manifest.quality_record_digest is not None
    return json.loads(blobs.read_exact(manifest.quality_record_digest))["findings"]


async def test_a_craft_finding_that_repair_leaves_open_is_recorded_as_stylistic(concurrent_session_factory, tmp_path):
    store = await _store(concurrent_session_factory)
    model = ScriptedModel()
    blobs = StoryBlobStore(tmp_path)

    def audit(prompt: str, _schema: dict[str, Any]) -> dict[str, Any]:
        if "KỸ THUẬT VÀ SỨC KÉO" not in prompt:
            return {"issues": []}
        issue = {
            "severity": "major",
            "issue_type": "flat_ending",
            "description": "chương kết bằng khoảng lắng",
            "quote": model.last_sentence(),
            "suggested_fix": "kết bằng một móc",
        }
        return {"issues": [issue]}

    model.overrides["issues"] = audit

    state = await _driver(concurrent_session_factory, store, model, blobs).run()

    assert state.phase is RunPhase.READY_FOR_APPROVAL, state.block_reason
    craft = [f for f in _quality(blobs, state) if f["code"].startswith("CRAFT:")]
    assert craft
    assert {f["severity"] for f in craft} == {"STYLISTIC"}
    assert not [f for f in _exceptions(blobs, state) if f["code"].startswith("CRAFT:")]
    assert model.calls["patches"] + model.calls["rewrites"] > 0  # repair was tried before the seal


async def test_a_variant_that_drops_a_source_event_is_replanned_once_then_offered_as_an_exception(
    concurrent_session_factory, tmp_path
):
    store = await _store(concurrent_session_factory)
    model = ScriptedModel()
    blobs = StoryBlobStore(tmp_path)
    model.overrides["contradicted"] = lambda _p, _s: {"missing": [2], "contradicted": [], "notes": ["bỏ sổ nợ"]}
    driver, _ = _prior_driver(concurrent_session_factory, store, model, blobs, "variant")

    state = await driver.run()

    assert state.phase is RunPhase.READY_FOR_APPROVAL, state.block_reason
    # The scripted plans come back identical, so the review is not asked again and its verdict stands.
    assert model.calls["contradicted"] == 1
    outline_prompts = [p for k, p in model.prompts if k == "story_arc"]
    assert "[Yêu cầu sửa dàn ý]" in outline_prompts[-1]
    assert "2. Có phong thư." in outline_prompts[-1]
    spine = [f for f in _exceptions(blobs, state) if f["code"] == "VARIANT_SPINE"]
    assert len(spine) == 1
    assert "Có phong thư." in spine[0]["message"]


async def test_a_long_prior_story_is_read_whole_through_arc_summaries_and_its_voice_is_kept(
    concurrent_session_factory, tmp_path
):
    from server.story_authoring.driver import StoryPrior
    from server.story_authoring.prompts.prior import split_prior

    store = await _store(concurrent_session_factory)
    model = ScriptedModel()
    blobs = StoryBlobStore(tmp_path)
    paragraph = "Minh và Lan ngồi bên bếp lửa, kể lại chuyện cũ của làng cho nhau nghe trong đêm dài. " * 9
    text = "\n\n".join(f"{paragraph}Lần thứ {i}." for i in range(140))
    chunks = len(split_prior(text))
    assert chunks > 12
    digest = blobs.put(text.encode("utf-8"))
    brief = BRIEF.model_copy(update={"prior": StoryPrior(mode="continuation", text_digest=digest)})
    client = OllamaChatClient(base_url="http://ollama:1", transport=httpx.MockTransport(model.handler))
    sink = StoryAttemptSink(
        store=store, session_factory=concurrent_session_factory, provider_id="custom-ollama", model_id=MODEL
    )
    gateway = AuthoringTextGateway(selection=SELECTION, limits=LIMITS, client=client, sink=sink)
    driver = StoryRunDriver(
        identity=IDENTITY,
        brief=brief,
        store=store,
        gateway=gateway,
        blobs=blobs,
        clock=lambda: NOW,
        retry_delays=(0, 0),
    )

    state = await driver.run()

    assert state.phase is RunPhase.READY_FOR_APPROVAL, state.block_reason
    arcs = -(-(chunks - 12) // 12)
    assert model.calls["events"] == chunks + arcs  # every chunk summarized, earlier ones condensed into arcs
    assert any(node.startswith("arc_summary[") for node in state.nodes)
    seed_prompt = next(prompt for kind, prompt in model.prompts if kind == "working_title")
    assert "Văn phong truyện gốc" in seed_prompt


async def test_the_genre_pack_of_the_brief_guides_planning_and_drafting(concurrent_session_factory, tmp_path):
    store = await _store(concurrent_session_factory)
    model = ScriptedModel()

    state = await _driver(concurrent_session_factory, store, model, StoryBlobStore(tmp_path)).run()

    assert state.phase is RunPhase.READY_FOR_APPROVAL, state.block_reason
    outline = next(p for k, p in model.prompts if k == "story_arc")
    assert "[Thể loại: Tâm lý – gia đình]" in outline  # the brief's genre "đời thường"
    plan = next(p for k, p in model.prompts if k == "chapter_goal")
    assert "[Thể loại: Tâm lý – gia đình]" in plan
    prose = next(p for k, p in model.prompts if k == "prose")
    assert "'nước mắt lăn dài'" in prose


async def test_a_variant_outline_sent_back_after_a_revised_first_outline_gets_a_new_round_of_calls(
    concurrent_session_factory, tmp_path
):
    store = await _store(concurrent_session_factory)
    model = ScriptedModel()
    blobs = StoryBlobStore(tmp_path)
    reviews: list[int] = []

    def review(_prompt: str, _schema: dict[str, Any]) -> dict[str, Any]:
        reviews.append(1)
        return {"passed": False, "problems": ["mở đầu chưa rõ"]} if len(reviews) == 1 else STRUCTURED["passed"]

    model.overrides["passed"] = review
    model.overrides["contradicted"] = lambda _p, _s: {"missing": [2], "contradicted": [], "notes": []}
    driver, _ = _prior_driver(concurrent_session_factory, store, model, blobs, "variant")

    state = await driver.run()

    assert state.phase is RunPhase.READY_FOR_APPROVAL, state.block_reason
    assert model.calls["story_arc"] == 3  # generated, revised, generated again after the variant note


async def test_the_safety_audit_reads_at_the_briefs_content_safety_level(concurrent_session_factory, tmp_path):
    store = await _store(concurrent_session_factory)
    model = ScriptedModel()
    client = OllamaChatClient(base_url="http://ollama:1", transport=httpx.MockTransport(model.handler))
    sink = StoryAttemptSink(
        store=store, session_factory=concurrent_session_factory, provider_id="custom-ollama", model_id=MODEL
    )
    gateway = AuthoringTextGateway(selection=SELECTION, limits=LIMITS, client=client, sink=sink)
    driver = StoryRunDriver(
        identity=IDENTITY,
        brief=BRIEF.model_copy(update={"content_safety": "off"}),
        store=store,
        gateway=gateway,
        blobs=StoryBlobStore(tmp_path),
        clock=lambda: NOW,
        retry_delays=(0, 0),
    )

    state = await driver.run()

    assert state.phase is RunPhase.READY_FOR_APPROVAL, state.block_reason
    safety = [p for k, p in model.prompts if k == "issues" and "NỘI DUNG NHẠY CẢM" in p]
    assert safety
    assert all("chỉ ghi là minor" in p and "người dưới 18 tuổi" in p for p in safety)

"""The story run driver: converge every node of the pipeline, then offer the manuscript at touchpoint 2.

One :meth:`StoryRunDriver.run` walks the node graph in topological order. Each node's fingerprint is computed from
the current heads of its inputs; a node whose head already carries that fingerprint is kept, any other node is
regenerated, and later nodes are judged against the new heads. A restart, a revision request or a retry
therefore resumes where the state says, and never regenerates a fresh node.

Every model call goes through the Task1 gateway and the Task2 attempt sink; every node has a call cap (a scene's
cap covers drafting, repair and regeneration together) and the run's budget caps all calls. A node that cannot
be made acceptable inside its cap stops the run in a typed blocked phase; nothing incomplete is offered.

Stages: seed, story bible, style bible, outline (generate, deterministic and judged review, one revision), one
chapter plan per chapter, then per chapter its scenes (draft, L1 checks, deterministic fixes, span repair,
length normalizing, regeneration) and the chapter loop (four L2 audits, repair of the scenes they name, at most
two cycles), then the L3 critic with its ending check, then packaging. The manifest built at the end holds the
Canon genesis, the plan and every scene's evidence for the Human's single approval.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from server.story_authoring.artifacts import StoryBlobStore, content_digest
from server.story_authoring.audits import (
    CHAPTER_DIMENSIONS,
    AuditDimension,
    anti_ai_findings,
    audit_chapter,
    confirm_finding,
    critic_manuscript,
    unconfirmed,
)
from server.story_authoring.checks import Finding, SceneLengthWindow, Severity, check_scene_prose, count_syllables
from server.story_authoring.commit import ManuscriptCommitManifest, SceneEntry, load_offered_manifest, offer_manifest
from server.story_authoring.contracts import (
    AttemptKind,
    OutputMode,
    StoryDecoding,
    StoryFailureCode,
    StoryLimits,
    StoryModelSelection,
    StoryScope,
    StoryStepKind,
    StoryStepRequest,
)
from server.story_authoring.generation import AuthoringTextGateway, StoryStepError
from server.story_authoring.narrative import (
    ChapterOutlineInput,
    ProvisionalAcceptance,
    SceneBases,
    SceneOutlineInput,
    SceneRef,
    StoryBibleInput,
    StoryEntityInput,
    StoryIdentity,
    StoryOutlineInput,
    build_candidate,
    build_genesis_delta,
    build_plan_proposal,
    build_revision,
    compile_scene_context,
    genesis_canon_version_id,
    provisional_canon_view,
    provisional_plan,
    provisional_readers,
    revision_decision_id,
    scene_contract,
    scene_refs,
)
from server.story_authoring.pipeline import chapter_plan, chapter_review, fingerprint
from server.story_authoring.prompts import drafting, planning
from server.story_authoring.prompts import outline as outline_prompts
from server.story_authoring.prompts import packaging as packaging_prompts
from server.story_authoring.prompts.schemas import (
    ChapterPlan,
    OutlineReview,
    Packaging,
    ShortOutline,
    StoryBibleOut,
    StorySeed,
    StyleBibleOut,
)
from server.story_authoring.repair import deterministic_fixes, normalize_length, span_repair
from server.story_authoring.runtime import RunPhase, RunState, RunStateStore, add_intent, promote, require, set_phase

CHAPTERS = 3
NODE_CAPS = {
    "seed": 3,
    "story_bible": 3,
    "style_bible": 3,
    "outline": 4,
    "chapter_plan": 8,
    "scene_draft": 6,
    "chapter_review": 12,
    "manuscript_review": 4,
    "packaging": 3,
}
REVIEW_CYCLES = 2
CONVERGE_PASSES = 6
JUDGE_ATTEMPTS = 3
MIN_VERIFIED_SELLING_POINTS = 3
STORY_HARD_RANGE = (6000, 12500)
STORY_TARGET_RANGE = (7000, 11000)
AUTO_NOTE = "Biên tập tự động: "
PLAN_REPAIR_NOTE = (
    "kế hoạch chương này đã khiến các cảnh không thể đạt yêu cầu: các mục bắt buộc, giữ kín và cấm mâu thuẫn nhau. "
    "Lập lại kế hoạch sao cho mọi mục bắt buộc làm được mà không phạm mục cấm hay lộ bài giữ kín. Lỗi thẩm định: "
)
REGENERATE_NOTE = (
    "\n\n[Lưu ý] Bản viết trước quá ngắn hoặc chép lại câu của các cảnh trước. Viết lại toàn bộ cảnh, đủ độ dài, bằng "
    "câu chữ hoàn toàn mới."
)
ENDING_NOTE = AUTO_NOTE + (
    "biên tập viên thấy cảnh này chưa khép lại xung đột trung tâm. Viết lại để kết thúc giải quyết trọn vẹn xung đột, "
    "trả lời câu hỏi mở đầu và dừng ở hình ảnh cuối đã định trong dàn ý."
)
RETRYABLE = frozenset(
    {
        StoryFailureCode.OUTPUT_INVALID,
        StoryFailureCode.OUTPUT_TRUNCATED,
        StoryFailureCode.CJK_IN_OUTPUT,
        StoryFailureCode.COUNT_MISMATCH,
        StoryFailureCode.OUTCOME_UNKNOWN,
    }
)
REPAIRABLE = frozenset({Severity.HARD_INTEGRITY, Severity.HARD_STRUCTURAL, Severity.NARRATIVE_CRITICAL})
PLANNING = {"temperature": 0.6, "top_p": 0.9, "top_k": 40, "presence_penalty": 0.0}
REVIEW = {"temperature": 0.2, "top_p": 0.9, "top_k": 40, "presence_penalty": 0.0}
DRAFT = {"temperature": 0.7, "top_p": 0.8, "top_k": 20, "presence_penalty": 0.0, "repeat_penalty": 1.1}
REPAIR = {"temperature": 0.3, "top_p": 0.9, "top_k": 40, "presence_penalty": 0.0}


class StoryBrief(BaseModel):
    """The Gate A input of a run. Its digest, which the Human greenlights, covers everything but the decision id."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    idea: str = Field(min_length=1)
    genre: str = Field(min_length=1)
    gate_a_decision_id: str | None = Field(default=None, min_length=1)
    story_target_syllables: int = Field(default=9000, ge=7000, le=11000)
    scene_window: tuple[int, int, int] = (600, 1000, 1400)
    selection: StoryModelSelection
    limits: StoryLimits

    def digest(self) -> str:
        content = self.model_dump(mode="json", exclude={"gate_a_decision_id"})
        raw = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


class Blocked(Exception):
    def __init__(self, phase: RunPhase, reason: str, findings: Sequence[Finding] = ()) -> None:
        self.phase = phase
        self.reason = reason
        self.findings = tuple(findings)
        super().__init__(f"{phase.value}: {reason}")


class _Restart(Exception):
    """The run state changed under a promotion (a new intent or phase); converge again from the top."""


def _seed_value(step_id: str) -> int:
    return int(hashlib.sha256(step_id.encode()).hexdigest()[:8], 16) % (2**31)


def _decoding(params: dict[str, float], step_id: str) -> StoryDecoding:
    return StoryDecoding.model_validate({**params, "seed": _seed_value(step_id)})


def _finding_dict(finding: Finding) -> dict[str, str]:
    return {
        "code": finding.code,
        "severity": finding.severity.value,
        "node_id": finding.node_id,
        "message": finding.message,
        "quote": finding.quote,
    }


def _finding_from(data: dict[str, str]) -> Finding:
    return Finding(data["code"], Severity(data["severity"]), data["node_id"], data["message"], data.get("quote", ""))


@dataclass(frozen=True)
class _Story:
    seed: StorySeed
    bible: StoryBibleOut
    style: StyleBibleOut
    outline: ShortOutline
    plans: tuple[ChapterPlan, ...]
    bible_input: StoryBibleInput
    outline_input: StoryOutlineInput
    names: dict[str, str]


class StoryRunDriver:
    def __init__(
        self,
        *,
        identity: StoryIdentity,
        brief: StoryBrief,
        store: RunStateStore,
        gateway: AuthoringTextGateway,
        blobs: StoryBlobStore,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if brief.gate_a_decision_id is None:
            raise ValueError("a story run starts only after its Gate A greenlight")
        self._identity = identity
        self._brief = brief
        self._gate_a_decision_id = brief.gate_a_decision_id
        self._store = store
        self._gateway = gateway
        self._blobs = blobs
        self._clock = clock
        self._scope = StoryScope(
            user_id=identity.user_id, project_name=identity.project_name, actor_id=f"run:{identity.run_id}"
        )
        window = brief.scene_window
        self._window = SceneLengthWindow(minimum=window[0], maximum=window[1], hard_maximum=window[2])

    # --- entry point -------------------------------------------------------------------------------

    async def run(self) -> RunState:
        state = await self._store.load()
        if state.phase is not RunPhase.RUNNING:
            return state
        try:
            for _ in range(CONVERGE_PASSES):
                intents = human_intents(await self._store.load())
                try:
                    story = await self._converge()
                except _Restart:
                    continue
                if human_intents(await self._store.load()) == intents:
                    break
            else:
                raise Blocked(RunPhase.BLOCKED_PROPAGATION, "the run kept changing while converging")
            manifest = await self._manifest(story)
            await offer_manifest(self._store, self._blobs, manifest)
        except Blocked as blocked:
            await self._set_phase(blocked.phase, blocked.reason, blocked.findings)
        except StoryStepError as error:
            if error.code is StoryFailureCode.MODEL_UNAVAILABLE or error.code is StoryFailureCode.PROVIDER_ERROR:
                await self._set_phase(RunPhase.MODEL_UNAVAILABLE, str(error))
            elif (
                error.code is not StoryFailureCode.RUN_NOT_RUNNING
                and error.code is not StoryFailureCode.BUDGET_EXHAUSTED
            ):
                await self._set_phase(RunPhase.BLOCKED_QUALITY, str(error))
        return await self._store.load()

    async def _set_phase(self, phase: RunPhase, reason: str, findings: Sequence[Finding] = ()) -> None:
        recorded = tuple(_finding_dict(f) for f in findings)

        def change(state: RunState) -> tuple[RunState, None]:
            if state.phase is not RunPhase.RUNNING:
                return state, None
            return set_phase(state, phase, reason=reason).model_copy(update={"blocked_findings": recorded}), None

        await self._store.apply(change)

    # --- node mechanics ----------------------------------------------------------------------------

    def _route(self) -> str:
        return self._brief.selection.config_digest

    async def _ensure(
        self,
        node: str,
        *,
        inputs: Sequence[tuple[str, str]],
        decoding: dict[str, float],
        produce: Callable[[int], Awaitable[bytes]],
        extra: dict[str, Any] | None = None,
    ) -> bytes:
        state = await self._store.load()
        fp = fingerprint(
            node=node,
            route_digest=self._route(),
            decoding=decoding,
            inputs=inputs,
            intents=state.intents.get(node, ()),
            extra=extra,
        )
        state, _ = await self._store.apply(lambda s: (require(s, node_id=node, fingerprint=fp), None))
        head = state.node(node)
        if head.head_revision_id is not None and state.revisions[head.head_revision_id].fingerprint == fp:
            return self._blobs.read_exact(state.revisions[head.head_revision_id].digest)
        data = await produce(head.generation_epoch)
        await self._promote(node, data, fp, expected=head.head_revision_id, epoch=head.generation_epoch)
        return data

    async def _promote(self, node: str, data: bytes, fp: str, *, expected: str | None, epoch: int) -> None:
        digest = self._blobs.put(data)
        now = self._clock()
        _, promoted = await self._store.apply(
            lambda s: promote(
                s,
                revision_id=uuid.uuid4().hex,
                node_id=node,
                digest=digest,
                fingerprint=fp,
                attempt_id=None,
                expected_head_revision_id=expected,
                generation_epoch=epoch,
                now=now,
            )
        )
        if not promoted:
            raise _Restart(node)

    async def _replace_head(self, node: str, data: bytes) -> None:
        """A repair revision inside the same node: same fingerprint, new head."""
        state = await self._store.load()
        head = state.node(node)
        assert head.head_revision_id is not None
        fp = state.revisions[head.head_revision_id].fingerprint
        await self._promote(node, data, fp, expected=head.head_revision_id, epoch=head.generation_epoch)

    async def _head(self, node: str) -> bytes:
        state = await self._store.load()
        head = state.node(node)
        assert head.head_revision_id is not None
        return self._blobs.read_exact(state.revisions[head.head_revision_id].digest)

    async def _step(
        self,
        node: str,
        epoch: int,
        *,
        kind: StoryStepKind,
        system: str,
        prompt: str,
        decoding: dict[str, float],
        model: type[BaseModel] | None = None,
        max_output_tokens: int = 4096,
        paragraphs: tuple[int, int] = (1, 40),
        paragraph_chars: int = 20,
        paragraph_max_chars: int | None = None,
    ) -> str:
        """One generation of a node, retried within the node's cap on recoverable output failures."""
        cap = NODE_CAPS[node.split("[", 1)[0]]
        while True:
            state = await self._store.load()
            prefix = step_prefix(state, node)
            used = sum(1 for a in state.attempts if a.kind is AttemptKind.GENERATE and a.step_id.startswith(prefix))
            if used >= cap:
                raise Blocked(RunPhase.BLOCKED_QUALITY, f"{node}: call cap {cap} reached without an acceptable output")
            step_id = f"{prefix}{used + 1}"
            try:
                output = await self._gateway.generate(
                    scope=self._scope,
                    request=StoryStepRequest(
                        step_id=step_id,
                        kind=kind,
                        context_digest=self._brief.digest(),
                        selection=self._brief.selection,
                        system_prompt=system,
                        prompt=prompt,
                        output_mode=OutputMode.STRUCTURED if model else OutputMode.PROSE,
                        response_model=model,
                        decoding=_decoding(decoding, step_id),
                        max_output_tokens=max_output_tokens,
                        min_paragraphs=paragraphs[0],
                        min_paragraph_chars=paragraph_chars,
                        max_paragraph_chars=paragraph_max_chars,
                        max_paragraphs=paragraphs[1],
                    ),
                )
                return output.text
            except StoryStepError as error:
                if error.code not in RETRYABLE:
                    raise

    # --- stages ------------------------------------------------------------------------------------

    async def _converge(self) -> _Story:
        brief = ("brief", self._brief.digest())
        seed_raw = await self._ensure(
            "seed",
            inputs=[brief],
            decoding=PLANNING,
            produce=lambda e: self._json(
                "seed",
                e,
                StoryStepKind.SEED,
                planning.PLANNING_SYSTEM,
                planning.seed_prompt(idea=self._brief.idea, genre=self._brief.genre),
                StorySeed,
            ),
        )
        seed = StorySeed.model_validate_json(seed_raw)
        seed_in = ("seed", content_digest(seed_raw))
        bible_raw = await self._ensure(
            "story_bible",
            inputs=[seed_in],
            decoding=PLANNING,
            produce=lambda e: self._json(
                "story_bible",
                e,
                StoryStepKind.BIBLE,
                planning.PLANNING_SYSTEM,
                planning.story_bible_prompt(seed),
                StoryBibleOut,
            ),
        )
        bible = StoryBibleOut.model_validate_json(bible_raw)
        bible_in = ("story_bible", content_digest(bible_raw))
        style_raw = await self._ensure(
            "style_bible",
            inputs=[seed_in, bible_in],
            decoding=PLANNING,
            produce=lambda e: self._json(
                "style_bible",
                e,
                StoryStepKind.BIBLE,
                planning.PLANNING_SYSTEM,
                planning.style_bible_prompt(seed, bible),
                StyleBibleOut,
            ),
        )
        style = StyleBibleOut.model_validate_json(style_raw)
        style_in = ("style_bible", content_digest(style_raw))
        outline_raw = await self._ensure(
            "outline", inputs=[seed_in], decoding=PLANNING, produce=lambda e: self._outline(e, seed)
        )
        outline = ShortOutline.model_validate(json.loads(outline_raw)["outline"])
        outline_in = ("outline", content_digest(outline_raw))

        names, locations = entity_keys(seed)
        plans: list[ChapterPlan] = []
        plan_ins: list[tuple[str, str]] = []
        for c in range(1, CHAPTERS + 1):
            previous = tuple(plans)
            node = chapter_plan(c)
            raw = await self._ensure(
                node,
                inputs=[seed_in, bible_in, outline_in, *plan_ins],
                decoding=PLANNING,
                produce=lambda e, c=c, previous=previous: self._chapter_plan(
                    e, c, seed, bible, outline, previous, names, locations
                ),
            )
            plans.append(ChapterPlan.model_validate_json(raw))
            plan_ins.append((node, content_digest(raw)))

        bible_input = story_bible_input(seed, style)
        outline_input = story_outline_input(outline, plans, names, locations)
        story = _Story(
            seed,
            bible,
            style,
            outline,
            tuple(plans),
            bible_input,
            outline_input,
            {**{k: n for n, k in names.items()}, **{k: n for n, k in locations.items()}},
        )
        await self._write_chapters(story, seed_in, bible_in, style_in, plan_ins)
        await self._manuscript_review(story, outline_in)
        await self._packaging(story, seed_in)
        return story

    async def _json(
        self, node: str, epoch: int, kind: StoryStepKind, system: str, prompt: str, model: type[BaseModel]
    ) -> bytes:
        text = await self._step(node, epoch, kind=kind, system=system, prompt=prompt, decoding=PLANNING, model=model)
        return model.model_validate_json(text).model_dump_json().encode("utf-8")

    async def _outline(self, epoch: int, seed: StorySeed) -> bytes:
        def generate(prompt: str) -> Awaitable[str]:
            return self._step(
                "outline",
                epoch,
                kind=StoryStepKind.OUTLINE,
                system=outline_prompts.OUTLINE_SYSTEM,
                prompt=prompt,
                decoding=PLANNING,
                model=ShortOutline,
            )

        outline = ShortOutline.model_validate_json(await generate(outline_prompts.outline_prompt(seed)))
        review = OutlineReview.model_validate_json(
            await self._step(
                "outline",
                epoch,
                kind=StoryStepKind.OUTLINE,
                system=outline_prompts.OUTLINE_SYSTEM,
                prompt=outline_prompts.outline_review_prompt(seed, outline),
                decoding=REVIEW,
                model=OutlineReview,
            )
        )
        problems = [*outline_prompts.deterministic_outline_problems(outline), *review.problems]
        if problems:
            outline = ShortOutline.model_validate_json(
                await generate(outline_prompts.outline_revision_prompt(seed, outline, problems))
            )
        remaining = outline_prompts.deterministic_outline_problems(outline)
        if remaining:
            raise Blocked(RunPhase.BLOCKED_QUALITY, "outline: " + "; ".join(remaining))
        return json.dumps({"outline": outline.model_dump(), "review_problems": problems}, ensure_ascii=False).encode(
            "utf-8"
        )

    async def _chapter_plan(
        self,
        epoch: int,
        chapter: int,
        seed: StorySeed,
        bible: StoryBibleOut,
        outline: ShortOutline,
        previous: tuple[ChapterPlan, ...],
        names: dict[str, str],
        locations: dict[str, str],
    ) -> bytes:
        prompt = planning.chapter_plan_prompt(
            chapter_number=chapter,
            outline=outline,
            bible=bible,
            character_names=list(names),
            location_names=list(locations),
            previous_plans=previous,
        )
        node = chapter_plan(chapter)
        notes = (await self._store.load()).intents.get(node, ())
        if notes:
            prompt += "\n\n[Yêu cầu sửa kế hoạch]\n" + "\n".join(f"- {n}" for n in notes)

        async def generate(text: str) -> tuple[ChapterPlan, list[str]]:
            plan = ChapterPlan.model_validate_json(
                await self._step(
                    node,
                    epoch,
                    kind=StoryStepKind.SCENE_CONTRACT,
                    system=planning.PLANNING_SYSTEM,
                    prompt=text,
                    decoding=PLANNING,
                    model=ChapterPlan,
                )
            )
            unknown = sorted(
                {n for s in plan.scenes for n in (s.pov, *s.characters) if planning.resolve_name(n, names) is None}
                | {s.location for s in plan.scenes if planning.resolve_name(s.location, locations) is None}
            )
            return plan, unknown

        plan, unknown = await generate(prompt)
        if unknown:
            prompt += (
                f"\n\nLần trước dùng tên không có trong danh sách: {', '.join(unknown)}. Chỉ dùng đúng các tên đã cho."
            )
            plan, unknown = await generate(prompt)
        if unknown:
            raise Blocked(RunPhase.BLOCKED_QUALITY, f"{node}: names outside the bible: {', '.join(unknown)}")
        review = OutlineReview.model_validate_json(
            await self._step(
                node,
                epoch,
                kind=StoryStepKind.SCENE_CONTRACT,
                system=planning.PLANNING_SYSTEM,
                prompt=planning.chapter_plan_review_prompt(plan, chapter),
                decoding=REVIEW,
                model=OutlineReview,
            )
        )
        if review.problems:
            revised, unknown = await generate(planning.chapter_plan_revision_prompt(prompt, plan, review.problems))
            if not unknown:
                plan = revised
        return plan.model_dump_json().encode("utf-8")

    # --- scenes and the chapter loop ---------------------------------------------------------------

    def _plan_state(self, story: _Story) -> tuple[Any, str, Any, Any]:
        delta = build_genesis_delta(
            self._identity, story.bible_input, created_by=f"run:{self._identity.run_id}", created_at=self._started
        )
        version = genesis_canon_version_id(delta)
        proposal = build_plan_proposal(
            self._identity,
            story.outline_input,
            canon_version_id=version,
            created_by=f"run:{self._identity.run_id}",
            created_at=self._started,
        )
        plan = provisional_plan(
            proposal, approval_ref="provisional", committed_by="provisional", committed_at=self._started
        )
        return delta, version, proposal, plan

    async def _write_chapters(
        self,
        story: _Story,
        seed_in: tuple[str, str],
        bible_in: tuple[str, str],
        style_in: tuple[str, str],
        plan_ins: list[tuple[str, str]],
    ) -> None:
        self._started = (await self._store.load()).started_at
        delta, version, proposal, plan = self._plan_state(story)
        refs = scene_refs(story.outline_input)
        for c in range(1, CHAPTERS + 1):
            chapter_refs = [r for r in refs if r.chapter == c]
            for cycle in range(REVIEW_CYCLES + 1):
                for ref in chapter_refs:
                    await self._ensure_scene(
                        story, ref, refs, delta, version, proposal, plan, [seed_in, bible_in, style_in, plan_ins[c - 1]]
                    )
                if cycle == REVIEW_CYCLES or not await self._review_chapter(story, c, chapter_refs, final=False):
                    break
            await self._review_chapter(story, c, chapter_refs, final=True)

    async def _acceptances(
        self, refs: Sequence[SceneRef], upto: int, version: str, proposal: Any
    ) -> list[ProvisionalAcceptance]:
        acceptances: list[ProvisionalAcceptance] = []
        for ref in refs[:upto]:
            head = json.loads(await self._head(ref.node_id))
            contract = scene_contract(proposal, ref)
            candidate = build_candidate(
                self._identity,
                ref,
                SceneBases(version, 1, contract.version, head["context_pack_id"]),
                head["prose"],
                model=self._brief.selection.model_id,
                writer_version="story-drafting-v1",
                created_by=f"run:{self._identity.run_id}",
                created_at=self._started,
            )
            revision = build_revision(candidate, created_by=f"run:{self._identity.run_id}", created_at=self._started)
            acceptances.append(
                ProvisionalAcceptance(
                    revision=revision, decision_id=revision_decision_id(self._identity, ref, revision)
                )
            )
        return acceptances

    async def _ensure_scene(
        self,
        story: _Story,
        ref: SceneRef,
        refs: Sequence[SceneRef],
        delta: Any,
        version: str,
        proposal: Any,
        plan: Any,
        inputs: list[tuple[str, str]],
    ) -> None:
        acceptances = await self._acceptances(refs, ref.global_index, version, proposal)
        readers = provisional_readers(
            self._identity,
            story.bible_input,
            canon_view=provisional_canon_view(delta),
            plan=plan,
            acceptances=acceptances,
        )
        contract = scene_contract(proposal, ref)
        pack = await compile_scene_context(
            readers,
            self._identity,
            ref,
            contract=contract,
            canon_version_id=version,
            plan_version=1,
            recent_decision_ids=[a.decision_id for a in acceptances],
        )
        binding = {"context_pack_id": pack.context_pack_id, "context_content_hash": pack.content_hash}
        context = drafting.render_context(pack, story.names)
        chapter = story.plans[ref.chapter - 1]
        planned = chapter.scenes[ref.scene - 1]
        is_last = ref.scene == len(chapter.scenes)
        is_final = is_last and ref.chapter == CHAPTERS
        target = drafting.target_syllables_for(
            chapter.scenes, story_target=self._brief.story_target_syllables, chapters=CHAPTERS
        )
        allowed = set(story.names.values())
        earlier = [a.revision.normalized_content for a in acceptances]

        async def produce(epoch: int) -> bytes:
            state = await self._store.load()
            note = "\n".join(state.intents.get(ref.node_id, ())) or None
            prompt = drafting.scene_draft_prompt(
                context=context,
                scene=planned,
                plan=chapter,
                chapter_number=ref.chapter,
                scene_number=ref.scene,
                is_last_scene_of_chapter=is_last,
                is_final_scene=is_final,
                target_syllables=target,
                revision_note=note,
            )
            prose, findings = await self._draft_until_clean(
                ref.node_id, epoch, prompt, context, allowed, planned.dialogue_required, target, earlier
            )
            return json.dumps(
                {**binding, "prose": prose, "findings": [_finding_dict(f) for f in findings]}, ensure_ascii=False
            ).encode("utf-8")

        await self._ensure(
            ref.node_id,
            inputs=[*inputs, *(("decision", a.decision_id) for a in acceptances)],
            decoding=DRAFT,
            produce=produce,
            extra=binding,
        )

    async def _draft_until_clean(
        self,
        node: str,
        epoch: int,
        prompt: str,
        context: str,
        allowed: set[str],
        dialogue: bool,
        target: int,
        earlier: Sequence[str],
    ) -> tuple[str, tuple[Finding, ...]]:
        bounds = drafting.paragraph_bounds(target)
        prose = await self._step(
            node,
            epoch,
            kind=StoryStepKind.SCENE_DRAFT,
            system=drafting.DRAFT_SYSTEM,
            prompt=prompt,
            decoding=DRAFT,
            paragraphs=bounds,
            paragraph_chars=drafting.paragraph_min_chars(target),
            paragraph_max_chars=drafting.paragraph_max_chars(target),
        )
        history: list[str] = []
        while True:
            findings = check_scene_prose(
                prose,
                node_id=node,
                window=self._window,
                allowed_names=allowed,
                requires_dialogue=dialogue,
                earlier=earlier,
            )
            repairable = [f for f in findings if f.severity in REPAIRABLE]
            if not repairable:
                return prose, findings
            if any(f.code == "SCENE_TOO_SHORT" for f in repairable):
                prose = await self._step(
                    node,
                    epoch,
                    kind=StoryStepKind.SCENE_DRAFT,
                    system=drafting.DRAFT_SYSTEM,
                    prompt=prompt + REGENERATE_NOTE,
                    decoding=DRAFT,
                    paragraphs=bounds,
                    paragraph_chars=drafting.paragraph_min_chars(target),
                    paragraph_max_chars=drafting.paragraph_max_chars(target),
                )
                continue
            fixed, notes = deterministic_fixes(prose, repairable, earlier=earlier)
            if notes:
                prose = fixed
                continue
            try:
                prose = await self._repair_once(node, epoch, prose, repairable, context, history)
            except Blocked:
                if any(f.blocking for f in repairable):
                    raise
                return prose, findings

    async def _repair_once(
        self, node: str, epoch: int, prose: str, findings: Sequence[Finding], context: str, history: list[str]
    ) -> str:
        """One bounded repair: length normalizing for length findings, else a span patch, else a regeneration."""
        state = await self._store.load()
        prefix = step_prefix(state, node)
        used = sum(1 for a in state.attempts if a.kind is AttemptKind.GENERATE and a.step_id.startswith(prefix))
        if used >= NODE_CAPS["scene_draft"]:
            raise Blocked(
                RunPhase.BLOCKED_QUALITY,
                f"{node}: findings remain after {used} calls: " + "; ".join(f.code for f in findings),
            )
        step_id = f"{prefix}{used + 1}"
        decoding = _decoding(REPAIR, step_id)
        common = {
            "scope": self._scope,
            "selection": self._brief.selection,
            "step_id": step_id,
            "context_digest": self._brief.digest(),
            "decoding": decoding,
        }
        try:
            if all(f.code == "LENGTH_HARD" for f in findings):
                outcome = await normalize_length(self._gateway, text=prose, window=self._window, **common)
            else:
                outcome = await span_repair(
                    self._gateway,
                    text=prose,
                    findings=findings,
                    context_block=context,
                    attempt_history=history,
                    **common,
                )
        except StoryStepError as error:
            if error.code not in RETRYABLE:
                raise
            history.append(f"{error.code.value}")
            return prose
        history.append(outcome.reason)
        return outcome.text

    async def _review_chapter(self, story: _Story, chapter: int, refs: Sequence[SceneRef], *, final: bool) -> bool:
        """Run the chapter's audits; repair named scenes. Returns whether a scene changed. ``final`` seals the chapter."""
        node = chapter_review(chapter)
        heads = {ref.node_id: json.loads(await self._head(ref.node_id)) for ref in refs}
        inputs = [
            (n, content_digest(json.dumps(h, ensure_ascii=False, sort_keys=True).encode())) for n, h in heads.items()
        ]
        state = await self._store.load()
        fp = fingerprint(node=node, route_digest=self._route(), decoding=REVIEW, inputs=inputs)
        head = state.node(node)
        if head.head_revision_id is not None and state.revisions[head.head_revision_id].fingerprint == fp:
            return False
        state, _ = await self._store.apply(lambda s: (require(s, node_id=node, fingerprint=fp), None))
        scenes = [(n, h["prose"]) for n, h in heads.items()]
        plan = story.plans[chapter - 1]
        facts = "\n".join(f"- {c.name}: {c.relation_to_protagonist}. {c.description}" for c in story.seed.characters)
        previous = " ".join(p.chapter_goal for p in story.plans[: chapter - 1])
        findings: list[Finding] = [f for n, h in heads.items() for f in anti_ai_findings(h["prose"], node_id=n)]
        for dimension in CHAPTER_DIMENSIONS:
            result = await self._judge(
                node,
                lambda step_id, decoding, dimension=dimension: audit_chapter(
                    self._gateway,
                    scope=self._scope,
                    selection=self._brief.selection,
                    step_id=step_id,
                    context_digest=self._brief.digest(),
                    decoding=decoding,
                    dimension=dimension,
                    chapter_number=chapter,
                    scenes=scenes,
                    plan=plan,
                    facts=facts,
                    previous_summary=previous,
                ),
            )
            findings.extend(result.findings)
            state = await self._store.load()
        findings = [
            await self._confirmed(node, f, scenes, plan) if f.blocking and ":" in f.code else f for f in findings
        ]
        repairable = [f for f in findings if f.severity in REPAIRABLE]
        if not final and repairable:
            changed = False
            for scene_node in sorted({f.node_id for f in repairable}):
                scene_findings = [f for f in repairable if f.node_id == scene_node]
                memo = [f for f in scene_findings if f.code.startswith(f"{AuditDimension.MEMO_COMPLIANCE.value}:")]
                contract = [f for f in memo if f.blocking]
                scene_findings = [f for f in scene_findings if f not in memo]
                if contract:
                    note = (
                        AUTO_NOTE
                        + f"thẩm định chương {chapter} yêu cầu viết lại cảnh này để sửa: "
                        + "; ".join(f"{f.message} (trích: “{f.quote}”)" for f in contract)
                    )
                    await self._store.apply(
                        lambda s, n=scene_node, note=note: (add_intent(s, node_ids=(n,), note=note), None)
                    )
                    changed = True
                    continue
                if not scene_findings:
                    continue
                state = await self._store.load()
                scene_epoch = state.node(scene_node).generation_epoch
                scene_head = heads[scene_node]
                repaired = await self._repair_once(
                    scene_node, scene_epoch, scene_head["prose"], scene_findings, facts, []
                )
                if repaired != scene_head["prose"]:
                    await self._replace_head(
                        scene_node, json.dumps({**scene_head, "prose": repaired}, ensure_ascii=False).encode("utf-8")
                    )
                    changed = True
            if changed:
                return True
        blocking = [f for f in findings if f.blocking]
        contract = f"{AuditDimension.MEMO_COMPLIANCE.value}:"
        if final and blocking and all(f.code.startswith(contract) for f in blocking):
            plan_node = chapter_plan(chapter)
            state = await self._store.load()
            if not state.intents.get(plan_node):
                note = AUTO_NOTE + PLAN_REPAIR_NOTE + "; ".join(f"{f.message} (trích: “{f.quote}”)" for f in blocking)
                scene_nodes = tuple(ref.node_id for ref in refs)
                await self._store.apply(
                    lambda s: (
                        add_intent(drop_auto_intents(s, scene_nodes), node_ids=(plan_node,), note=note),
                        None,
                    )
                )
                raise _Restart(plan_node)
        if final and any(f.blocking for f in findings):
            raise Blocked(
                RunPhase.BLOCKED_QUALITY,
                f"{node}: " + "; ".join(f"{f.code} {f.node_id}" for f in findings if f.blocking),
                [f for f in findings if f.blocking],
            )
        record = json.dumps({"findings": [_finding_dict(f) for f in findings]}, ensure_ascii=False).encode("utf-8")
        await self._promote(
            node, record, fp, expected=state.node(node).head_revision_id, epoch=state.node(node).generation_epoch
        )
        return False

    async def _confirmed(
        self, node: str, finding: Finding, scenes: Sequence[tuple[str, str]], plan: ChapterPlan
    ) -> Finding:
        """A blocking audit claim stays blocking only if an independent second reading confirms it."""
        confirmed = await self._judge(
            node,
            lambda step_id, decoding: confirm_finding(
                self._gateway,
                scope=self._scope,
                selection=self._brief.selection,
                step_id=step_id,
                context_digest=self._brief.digest(),
                decoding=decoding,
                finding=finding,
                scenes=scenes,
                plan=plan,
            ),
        )
        return finding if confirmed else unconfirmed(finding)

    async def _judge[T](self, node: str, call: Callable[[str, StoryDecoding], Awaitable[T]]) -> T:
        """One judgment of a review node, retried under a new step id on a recoverable output failure."""
        for attempt in range(JUDGE_ATTEMPTS):
            state = await self._store.load()
            prefix = step_prefix(state, node)
            used = sum(1 for a in state.attempts if a.kind is AttemptKind.GENERATE and a.step_id.startswith(prefix))
            step_id = f"{prefix}{used + 1}"
            try:
                return await call(step_id, _decoding(REVIEW, step_id))
            except StoryStepError as error:
                if error.code not in RETRYABLE or attempt == JUDGE_ATTEMPTS - 1:
                    raise
        raise AssertionError("unreachable")

    async def _manuscript_review(self, story: _Story, outline_in: tuple[str, str]) -> None:
        refs = scene_refs(story.outline_input)
        heads = [(ref.node_id, json.loads(await self._head(ref.node_id))["prose"]) for ref in refs]
        inputs = [outline_in, *((n, content_digest(p.encode())) for n, p in heads)]

        async def produce(epoch: int) -> bytes:
            result = await self._judge(
                "manuscript_review",
                lambda step_id, decoding: critic_manuscript(
                    self._gateway,
                    scope=self._scope,
                    selection=self._brief.selection,
                    step_id=step_id,
                    context_digest=self._brief.digest(),
                    decoding=decoding,
                    scenes=heads,
                    outline=story.outline,
                ),
            )
            blocking = [f for f in result.findings if f.blocking]
            final_scene = heads[-1][0]
            if [f.code for f in blocking] == ["NO_ENDING"]:
                state = await self._store.load()
                if ENDING_NOTE not in state.intents.get(final_scene, ()):
                    await self._store.apply(lambda s: (add_intent(s, node_ids=(final_scene,), note=ENDING_NOTE), None))
                    raise _Restart(final_scene)
            if blocking:
                raise Blocked(
                    RunPhase.BLOCKED_QUALITY,
                    "manuscript_review: " + "; ".join(f.message for f in result.findings if f.blocking),
                    blocking,
                )
            return json.dumps(
                {
                    "findings": [_finding_dict(f) for f in result.findings],
                    "discarded_unquoted": result.discarded_unquoted,
                },
                ensure_ascii=False,
            ).encode("utf-8")

        await self._ensure("manuscript_review", inputs=inputs, decoding=REVIEW, produce=produce)

    async def _packaging(self, story: _Story, seed_in: tuple[str, str]) -> None:
        refs = scene_refs(story.outline_input)
        manuscript = "\n\n".join([json.loads(await self._head(r.node_id))["prose"] for r in refs])
        inputs = [seed_in, ("manuscript", content_digest(manuscript.encode()))]

        async def produce(epoch: int) -> bytes:
            for _ in range(2):
                packaging = Packaging.model_validate_json(
                    await self._step(
                        "packaging",
                        epoch,
                        kind=StoryStepKind.PACKAGING,
                        system=packaging_prompts.PACKAGING_SYSTEM,
                        prompt=packaging_prompts.packaging_prompt(
                            manuscript=manuscript, working_title=story.seed.working_title, premise=story.seed.premise
                        ),
                        decoding=PLANNING,
                        model=Packaging,
                    )
                )
                unverified = packaging_prompts.unverified_selling_points(packaging, manuscript)
                kept = [p.model_dump() for p in packaging.selling_points if p.point not in unverified]
                if len(kept) >= MIN_VERIFIED_SELLING_POINTS:
                    verified = Packaging.model_validate({**packaging.model_dump(), "selling_points": kept})
                    return verified.model_dump_json().encode("utf-8")
            raise Blocked(RunPhase.BLOCKED_QUALITY, "packaging: fewer than three selling points quote the manuscript")

        await self._ensure("packaging", inputs=inputs, decoding=PLANNING, produce=produce)

    # --- manifest ----------------------------------------------------------------------------------

    async def _manifest(self, story: _Story) -> ManuscriptCommitManifest:
        delta, version, proposal, _ = self._plan_state(story)
        refs = scene_refs(story.outline_input)
        entries: list[SceneEntry] = []
        findings: list[Finding] = []
        chapters: dict[int, list[str]] = {}
        for ref in refs:
            head = json.loads(await self._head(ref.node_id))
            contract = scene_contract(proposal, ref)
            candidate = build_candidate(
                self._identity,
                ref,
                SceneBases(version, 1, contract.version, head["context_pack_id"]),
                head["prose"],
                model=self._brief.selection.model_id,
                writer_version="story-drafting-v1",
                created_by=f"run:{self._identity.run_id}",
                created_at=self._started,
            )
            revision = build_revision(candidate, created_by=f"run:{self._identity.run_id}", created_at=self._started)
            entries.append(
                SceneEntry(
                    node_id=ref.node_id,
                    chapter=ref.chapter,
                    scene=ref.scene,
                    global_index=ref.global_index,
                    candidate=candidate,
                    revision=revision,
                    decision_id=revision_decision_id(self._identity, ref, revision),
                    context_pack_id=head["context_pack_id"],
                    context_content_hash=head["context_content_hash"],
                )
            )
            findings.extend(_finding_from(f) for f in head["findings"])
            chapters.setdefault(ref.chapter, []).append(revision.normalized_content)
        for node in (*(chapter_review(c) for c in chapters), "manuscript_review"):
            findings.extend(_finding_from(f) for f in json.loads(await self._head(node))["findings"])
        packaging = Packaging.model_validate_json(await self._head("packaging"))
        findings.extend(story_length_findings([chapters[c] for c in sorted(chapters)]))
        blocking = [f for f in findings if f.blocking]
        if blocking:
            raise Blocked(RunPhase.BLOCKED_QUALITY, "; ".join(f"{f.code} {f.node_id}" for f in blocking), blocking)
        record = [{**_finding_dict(f), "id": f"F{i + 1:03d}"} for i, f in enumerate(findings)]
        quality_digest = self._blobs.put(
            json.dumps({"findings": record, "packaging": packaging.model_dump()}, ensure_ascii=False).encode("utf-8")
        )
        exceptions = tuple(
            r["id"]
            for r in record
            if r["severity"] in (Severity.NARRATIVE_CRITICAL.value, Severity.LOCAL_MODEL_LIMIT.value)
        )
        export = render_markdown(
            title=packaging.titles[0].title, blurb=packaging.blurbs[0], chapters=[chapters[c] for c in sorted(chapters)]
        )
        export_digest = self._blobs.put(export.encode("utf-8"))
        state = await self._store.load()
        committed = state.commit.completed_steps if state.commit is not None else ()
        predecessor = load_offered_manifest(self._blobs, state).digest() if committed else None
        return ManuscriptCommitManifest(
            run_id=self._identity.run_id,
            predecessor_manifest_digest=predecessor,
            committed_prefix=tuple(committed),
            brief_digest=self._brief.digest(),
            gate_a_decision_id=self._gate_a_decision_id,
            canon_genesis=delta,
            canon_version_id=version,
            plan=proposal,
            scenes=tuple(entries),
            findings_open=tuple(r["id"] for r in record),
            exceptions_offered=exceptions,
            export_digest=export_digest,
            quality_record_digest=quality_digest,
        )


def human_intents(state: RunState) -> dict[str, tuple[str, ...]]:
    """Revision notes from the Human; the driver's own notes (``AUTO_NOTE``) are excluded."""
    notes = {node: tuple(n for n in found if not n.startswith(AUTO_NOTE)) for node, found in state.intents.items()}
    return {node: found for node, found in notes.items() if found}


def drop_auto_intents(state: RunState, node_ids: Sequence[str]) -> RunState:
    """Remove the driver's own notes from nodes whose contract is about to be replanned."""
    intents = dict(state.intents)
    for node_id in node_ids:
        kept = tuple(n for n in intents.get(node_id, ()) if not n.startswith(AUTO_NOTE))
        if kept:
            intents[node_id] = kept
        else:
            intents.pop(node_id, None)
    return state.model_copy(update={"intents": intents})


def step_prefix(state: RunState, node: str) -> str:
    """Attempts of a node in one round share its call cap. A round ends with a Human revision or retry; for a
    scene or chapter review it also ends when its chapter plan is replanned, since the contract is new."""
    replans = 0
    if node.startswith(("scene_draft[", "chapter_review[")):
        chapter = node.split("[", 1)[1].split(",", 1)[0].rstrip("]")
        replans = len(state.intents.get(chapter_plan(int(chapter)), ()))
    return f"{node}@r{len(human_intents(state).get(node, ()))}.{state.retries}.{replans}#"


def entity_keys(seed: StorySeed) -> tuple[dict[str, str], dict[str, str]]:
    """Name -> key for the seed's characters and locations, in seed order, keys unique across both."""
    taken: list[str] = []
    names: dict[str, str] = {}
    for character in seed.characters:
        names[character.name] = planning.entity_key(character.name, taken)
        taken.append(names[character.name])
    locations: dict[str, str] = {}
    for location in seed.locations:
        locations[location.name] = planning.entity_key(location.name, taken)
        taken.append(locations[location.name])
    return names, locations


def story_bible_input(seed: StorySeed, style: StyleBibleOut) -> StoryBibleInput:
    """The bible the narrative owners see; the driver and the approval both derive it from the same heads."""
    names, locations = entity_keys(seed)
    return StoryBibleInput(
        title=seed.working_title,
        premise=seed.premise,
        characters=tuple(
            StoryEntityInput(
                key=names[c.name], name=c.name, description=f"{c.relation_to_protagonist}. {c.description}"
            )
            for c in seed.characters
        ),
        locations=tuple(
            StoryEntityInput(key=locations[loc.name], name=loc.name, description=loc.description)
            for loc in seed.locations
        ),
        style_rules=tuple(style.style_rules),
    )


def story_outline_input(
    outline: ShortOutline, plans: Sequence[ChapterPlan], names: dict[str, str], locations: dict[str, str]
) -> StoryOutlineInput:
    """The plan the narrative owners see: the outline's frame and each chapter plan's scenes, names as keys."""
    return StoryOutlineInput(
        story_frame=f"{outline.story_arc} {outline.opening} {outline.confrontation}",
        chapters=tuple(
            ChapterOutlineInput(
                intent=plan.chapter_goal,
                scenes=tuple(
                    SceneOutlineInput(
                        purpose=f"{scene.summary} ({scene.plot_function})",
                        pov=planning.resolve_name(scene.pov, names),
                        location=planning.resolve_name(scene.location, locations),
                        participants=tuple(k for k in (planning.resolve_name(n, names) for n in scene.characters) if k),
                        beats=tuple(scene.beats),
                    )
                    for scene in plan.scenes
                ),
            )
            for plan in plans
        ),
    )


def story_length_findings(chapters: Sequence[Sequence[str]]) -> tuple[Finding, ...]:
    """Whole-story length: outside the hard range is structural, outside the target range stylistic."""
    total = syllables_of(chapters)
    if not STORY_HARD_RANGE[0] <= total <= STORY_HARD_RANGE[1]:
        bounds = f"{STORY_HARD_RANGE[0]}-{STORY_HARD_RANGE[1]}"
        return (Finding("STORY_LENGTH", Severity.HARD_STRUCTURAL, "manuscript", f"{total} syllables outside {bounds}"),)
    if not STORY_TARGET_RANGE[0] <= total <= STORY_TARGET_RANGE[1]:
        bounds = f"{STORY_TARGET_RANGE[0]}-{STORY_TARGET_RANGE[1]}"
        return (Finding("STORY_LENGTH", Severity.STYLISTIC, "manuscript", f"{total} syllables outside {bounds}"),)
    return ()


def render_markdown(*, title: str, blurb: str, chapters: Sequence[Sequence[str]]) -> str:
    """The exported manuscript: deterministic from the approved scene texts and the first title and blurb."""
    parts = [f"# {title}", "", f"> {blurb}", ""]
    for number, scenes in enumerate(chapters, start=1):
        parts.extend([f"## Chương {number}", "", "\n\n* * *\n\n".join(scenes), ""])
    return "\n".join(parts).rstrip() + "\n"


def syllables_of(chapters: Sequence[Sequence[str]]) -> int:
    return sum(count_syllables(s) for scenes in chapters for s in scenes)

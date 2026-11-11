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

import asyncio
import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from r2.narrative.canon_state import ResolvedCanonView
from server.story_authoring import book as books
from server.story_authoring.artifacts import StoryBlobStore, content_digest
from server.story_authoring.audits import (
    CHAPTER_DIMENSIONS,
    AuditDimension,
    SafetyLevel,
    anti_ai_findings,
    audit_chapter,
    confirm_finding,
    critic_manuscript,
    unconfirmed,
    unfaithful_blurbs,
)
from server.story_authoring.cast_checks import (
    fix_gender_openings,
    fix_near_names,
    gender_findings,
    missing_idea_names,
    name_pov,
    plan_conflicts,
    pov_findings,
    pov_person_findings,
    seed_problems,
)
from server.story_authoring.checks import (
    ESCALATED_MARK,
    Finding,
    SceneLengthWindow,
    Severity,
    check_scene_prose,
    count_syllables,
    escalate_or_block,
    foreign_script,
    json_leaks,
    notes_leaks,
)
from server.story_authoring.commit import ManuscriptCommitManifest, SceneEntry, load_offered_manifest, offer_manifest
from server.story_authoring.contracts import (
    AttemptKind,
    CloudRouteProfile,
    OutputMode,
    StoryDecoding,
    StoryFailureCode,
    StoryLimits,
    StoryModelSelection,
    StoryScope,
    StoryStepKind,
    StoryStepRequest,
)
from server.story_authoring.craft_checks import (
    closing_hook_findings,
    drift_findings,
    long_span_findings,
    opening_findings,
)
from server.story_authoring.generation import AuthoringTextGateway, StoryStepError
from server.story_authoring.genre_packs import GenrePack, craft_rules, fatigue_findings, pack_for, planning_block
from server.story_authoring.layout import natural_paragraphs
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
    recent_indices,
    revision_decision_id,
    scene_contract,
    scene_refs,
)
from server.story_authoring.pipeline import chapter_plan, chapter_review, fingerprint, scene_draft
from server.story_authoring.prompts import book as book_prompts
from server.story_authoring.prompts import drafting, planning
from server.story_authoring.prompts import outline as outline_prompts
from server.story_authoring.prompts import packaging as packaging_prompts
from server.story_authoring.prompts import prior as prior_prompts
from server.story_authoring.prompts.prior import CanonLock, PriorSummary, VariantReview, variant_review_prompt
from server.story_authoring.prompts.schemas import (
    SCENES_PER_CHAPTER_MAX,
    ChapterPlan,
    OutlineReview,
    Packaging,
    SeedCharacter,
    ShortOutline,
    StoryBibleOut,
    StorySeed,
    StyleBibleOut,
    bound_chapter_plan,
    bound_short_outline,
)
from server.story_authoring.repair import deterministic_fixes, normalize_length, span_repair
from server.story_authoring.runtime import RunPhase, RunState, RunStateStore, add_intent, promote, require, set_phase

CHAPTERS = 3
#: The node recording which committed Canon head the run branches from, so a resume keeps the same base.
CANON_BASE_NODE = "canon_base"
NODE_CAPS = {
    "canon_base": 1,
    "variant_review": 2,
    "arc_summary": 3,
    "seed": 3,
    "story_bible": 3,
    "style_bible": 3,
    "outline": 4,
    "chapter_plan": 8,
    "scene_draft": 6,
    "chapter_review": 12,
    "manuscript_review": 4,
    "packaging": 3,
    "prior_summary": 3,
    "canon_lock": 3,
    "book_outline": 3,
    "book_chapters": 18,
    "chapter_digest": 3,
    "part_summary": 3,
    "book_state": 1,
}
TRANSPORT = frozenset({StoryFailureCode.MODEL_UNAVAILABLE, StoryFailureCode.PROVIDER_ERROR})
TRANSPORT_RETRY_DELAYS = (5.0, 20.0)
REVIEW_CYCLES = 2
CONVERGE_PASSES = 6
JUDGE_ATTEMPTS = 3
CONFIRM_MAX = 3
PLAN_CALLS = 4
#: Automatic replans of one chapter plan before its unmet contract goes to the Showrunner (ADR-0127).
PLAN_REPLANS = 3
MIN_VERIFIED_SELLING_POINTS = 3
STORY_HARD_RANGE = (6000, 12500)
STORY_TARGET_RANGE = (7000, 11000)
#: A book part's length bounds as fractions of its target (chapters x syllables per chapter).
PART_TARGET_SPREAD = 0.2
PART_HARD_SPREAD = 0.4
SHORT_SEED = (5, 4)
AUTO_NOTE = "Biên tập tự động: "
PLAN_REPAIR_NOTE = (
    "kế hoạch chương này đã khiến các cảnh không thể đạt yêu cầu: các mục bắt buộc, giữ kín và cấm mâu thuẫn nhau. "
    "Lập lại kế hoạch sao cho mọi mục bắt buộc làm được mà không phạm mục cấm hay lộ bài giữ kín. Lỗi thẩm định: "
)
REGENERATE_NOTE = (
    "\n\n[Lưu ý] Bản viết trước quá ngắn hoặc chép lại câu của các cảnh trước. Viết lại toàn bộ cảnh, đủ độ dài, bằng "
    "câu chữ hoàn toàn mới."
)
PART_ENDING_NOTE = AUTO_NOTE + (
    "biên tập viên thấy cảnh này chưa đưa phần truyện tới bước ngoặt đã định trong dàn ý. Viết lại để phần kết ở đúng "
    "bước ngoặt đó, không giải quyết xung đột trung tâm của cả tiểu thuyết."
)
HOOKS_NOTE = AUTO_NOTE + "chương cuối của tiểu thuyết phải giải nốt các phục bút còn mở: "
VARIANT_NOTE = AUTO_NOTE + (
    "dàn ý phiên bản khác đã bỏ hoặc làm trái các diễn biến của truyện gốc mà yêu cầu không cho đổi; giữ lại đúng "
    "thứ tự các diễn biến: "
)
ENDING_REPLAN_NOTE = AUTO_NOTE + (
    "kết truyện vẫn chưa khép lại sau khi viết lại cảnh cuối; lập lại kế hoạch chương cuối để các cảnh dẫn tới và "
    "trình bày trọn kết thúc sau: "
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
_CUT_AT_REVIEW = frozenset({"JSON_LEAK", "NOTES_LEAK"})
REPAIRABLE = frozenset({Severity.HARD_INTEGRITY, Severity.HARD_STRUCTURAL, Severity.NARRATIVE_CRITICAL})
IDEA_ANCHOR = "[Ý tưởng gốc của tác giả — mọi phần phải trung thành: nhân vật, giới tính, ham muốn, xung đột]"
PLANNING = {"temperature": 0.6, "top_p": 0.9, "top_k": 40, "presence_penalty": 0.0}
REVIEW = {"temperature": 0.2, "top_p": 0.9, "top_k": 40, "presence_penalty": 0.0}
DRAFT = {"temperature": 0.7, "top_p": 0.8, "top_k": 20, "presence_penalty": 0.0, "repeat_penalty": 1.1}
REPAIR = {"temperature": 0.3, "top_p": 0.9, "top_k": 40, "presence_penalty": 0.0}


class StoryPrior(BaseModel):
    """A story that already exists, which this run continues or rewrites as a variant (ADR-0115). The prior text
    is stored in the run's blob store under ``text_digest``; ``part`` numbers a continuation."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    mode: Literal["continuation", "variant"]
    text_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    part: int = Field(default=2, ge=2, le=99)
    origin: str = Field(default="instruction", min_length=1, max_length=80)


class StoryBrief(BaseModel):
    """The Gate A input of a run. Its digest, which the Human greenlights, covers everything but the decision id."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    idea: str = Field(min_length=1)
    genre: str = Field(min_length=1)
    gate_a_decision_id: str | None = Field(default=None, min_length=1)
    story_target_syllables: int = Field(default=9000, ge=7000, le=11000)
    scene_window: tuple[int, int, int] = (600, 1000, 1400)
    selection: StoryModelSelection
    judge_selection: StoryModelSelection | None = None
    limits: StoryLimits
    cloud_profiles: tuple[CloudRouteProfile, ...] = Field(default=(), exclude_if=lambda value: not value)
    #: The story this run continues or rewrites; ``idea`` is then the author's direction or variant instruction.
    prior: StoryPrior | None = Field(default=None, exclude_if=lambda value: value is None)
    #: How strictly the story is read for sensitive content (ADR-0121), from the project's setting.
    content_safety: SafetyLevel = Field(default="standard", exclude_if=lambda value: value == "standard")
    #: The part of a book this run writes (ADR-0116); none for a three-chapter story.
    book: books.BookPart | None = Field(default=None, exclude_if=lambda value: value is None)
    #: A short story digests each chapter and carries what happened into the next (stage-by-stage F3). Briefs drafted
    #: before it leave it out, so their runs keep their exact inputs on resume.
    carries_digests: bool = Field(default=False, exclude_if=lambda value: not value)

    @property
    def chapters(self) -> int:
        return CHAPTERS if self.book is None else self.book.chapters

    @property
    def judge(self) -> StoryModelSelection:
        """The route of review calls (audits, confirmation, critic, outline and plan review); the writer's by default."""
        return self.judge_selection or self.selection

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
        judge_gateway: AuthoringTextGateway | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        retry_delays: Sequence[float] = TRANSPORT_RETRY_DELAYS,
        canon_base: ResolvedCanonView | None = None,
    ) -> None:
        """``canon_base`` is the project's committed ``MAIN`` head when an earlier story holds it; this run's Canon
        then branches from it."""
        if (brief.judge_selection is None) != (judge_gateway is None):
            raise ValueError("a judge gateway is given exactly when the brief names a judge route")
        if brief.gate_a_decision_id is None:
            raise ValueError("a story run starts only after its Gate A greenlight")
        self._identity = identity
        self._brief = brief
        self._gate_a_decision_id = brief.gate_a_decision_id
        self._store = store
        self._gateway = gateway
        self._judge_gateway = judge_gateway or gateway
        self._blobs = blobs
        self._clock = clock
        self._retry_delays = tuple(retry_delays)
        self._outages = 0
        self._prior_context: str | None = None
        self._prior_tail = ""
        self._canon_base = canon_base
        self._lock: CanonLock | None = None
        self._pack: GenrePack | None = None
        self._book = brief.book
        self._chapters = brief.chapters
        self._digesting = brief.book is not None or brief.carries_digests
        self._plan: books.BookPlan | None = None
        self._memory = books.BookMemory()
        self._book_ins: list[tuple[str, str]] = []
        self._title: str | None = None
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
            # Every automatic replan restarts the pass; each chapter replans at most PLAN_REPLANS times, so the
            # passes they take are bounded and come on top of those that converge Human revisions.
            for _ in range(CONVERGE_PASSES + self._chapters * PLAN_REPLANS + 1):
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
        writer = self._brief.selection.config_digest
        if self._brief.judge_selection is None:
            return writer
        return writer + "+" + self._brief.judge_selection.config_digest

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
        judge: bool = False,
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
                gateway = self._judge_gateway if judge else self._gateway
                output = await gateway.generate(
                    scope=self._scope,
                    request=StoryStepRequest(
                        step_id=step_id,
                        kind=kind,
                        context_digest=self._brief.digest(),
                        selection=self._brief.judge if judge else self._brief.selection,
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
                self._outages = 0
                return output.text
            except StoryStepError as error:
                if error.code in TRANSPORT:
                    await self._outage(error)
                elif error.code not in RETRYABLE:
                    raise

    # --- stages ------------------------------------------------------------------------------------

    async def _read_prior(self, prior: StoryPrior) -> tuple[CanonLock, tuple[str, str], str]:
        """Summaries of the prior text's chunks, then its attested canon lock (ADR-0115)."""
        text = self._blobs.read_exact(prior.text_digest).decode("utf-8")
        chunks = prior_prompts.split_prior(text)
        omitted = len(chunks) > prior_prompts.MAX_PRIOR_CHUNKS
        if omitted and prior.mode == "variant":
            raise Blocked(RunPhase.BLOCKED_QUALITY, "variant: the story is too long to read in full")
        chunks = chunks[-prior_prompts.MAX_PRIOR_CHUNKS :]
        source = ("prior", prior.text_digest)
        summaries: list[PriorSummary] = []
        summary_ins: list[tuple[str, str]] = []
        for k, chunk in enumerate(chunks, start=1):
            node = f"prior_summary[{k}]"
            raw = await self._ensure(
                node,
                inputs=[source],
                decoding=PLANNING,
                extra={"chunk": k, "of": len(chunks)},
                produce=lambda e, node=node, chunk=chunk, k=k: self._json(
                    node,
                    e,
                    StoryStepKind.PRIOR_READING,
                    prior_prompts.PRIOR_SYSTEM,
                    prior_prompts.prior_summary_prompt(chunk, k, len(chunks)),
                    PriorSummary,
                ),
            )
            summaries.append(PriorSummary.model_validate_json(raw))
            summary_ins.append((node, content_digest(raw)))
        tail = text.strip()[-prior_prompts.PRIOR_TAIL_CHARS :]
        read = summaries
        if len(summaries) > prior_prompts.RECENT_CHUNKS:
            # ADR-0118: earlier chunks reach the lock through arc summaries, so a long novel is read whole.
            early = summaries[: -prior_prompts.RECENT_CHUNKS]
            arcs: list[PriorSummary] = []
            for g in range(0, len(early), prior_prompts.ARC_CHUNKS):
                group = early[g : g + prior_prompts.ARC_CHUNKS]
                node = f"arc_summary[{g // prior_prompts.ARC_CHUNKS + 1}]"
                raw = await self._ensure(
                    node,
                    inputs=summary_ins[g : g + len(group)],
                    decoding=PLANNING,
                    produce=lambda e, node=node, group=group, g=g: self._json(
                        node,
                        e,
                        StoryStepKind.PRIOR_READING,
                        prior_prompts.PRIOR_SYSTEM,
                        prior_prompts.arc_summary_prompt(group, g + 1, g + len(group)),
                        PriorSummary,
                    ),
                )
                arcs.append(PriorSummary.model_validate_json(raw))
                summary_ins.append((node, content_digest(raw)))
            read = [*arcs, *summaries[-prior_prompts.RECENT_CHUNKS :]]

        async def lock(epoch: int) -> bytes:
            raw = await self._json(
                "canon_lock",
                epoch,
                StoryStepKind.PRIOR_READING,
                prior_prompts.PRIOR_SYSTEM,
                prior_prompts.canon_lock_prompt(read, tail, mode=prior.mode, omitted=omitted),
                CanonLock,
            )
            try:
                attested = prior_prompts.attest(CanonLock.model_validate_json(raw), text)
            except ValueError as error:
                raise Blocked(RunPhase.BLOCKED_QUALITY, f"canon_lock: {error}") from None
            return attested.model_dump_json().encode("utf-8")

        lock_raw = await self._ensure("canon_lock", inputs=[source, *summary_ins], decoding=PLANNING, produce=lock)
        return CanonLock.model_validate_json(lock_raw), ("canon_lock", content_digest(lock_raw)), tail

    def _with_prior(self, prompt: str) -> str:
        """A planning prompt preceded by the prior story's canon lock and the author's ask, when there is one, and by
        the genre pack's planning guidance (ADR-0119)."""
        genre = planning_block(self._pack)
        if genre:
            prompt = f"{genre}\n\n{prompt}"
        if self._prior_context is not None:
            return f"{self._prior_context}\n\n---\n\n{prompt}"
        # The author's idea anchors every planning step, not only the seed, so a drifted seed cannot carry the
        # whole run away from it (donor shenbi a440306: intent anchored, never invented).
        return f"{IDEA_ANCHOR}\n{self._brief.idea}\n\n---\n\n{prompt}"

    def _book_state(self) -> books.BookState | None:
        """The state the previous part committed, for a book part after the first."""
        if self._book is None or self._book.state_digest is None:
            return None
        return books.BookState.model_validate_json(self._blobs.read_exact(self._book.state_digest))

    async def _converge(self) -> _Story:
        brief = ("brief", self._brief.digest())
        base = self._canon_base
        recorded = None if base is None else [base.branch_id, base.canon_version_id]
        await self._ensure(
            CANON_BASE_NODE,
            inputs=[],
            decoding=PLANNING,
            produce=_constant(json.dumps(recorded).encode("utf-8")),
            extra={"base": recorded},
        )
        prior_ins: list[tuple[str, str]] = []
        idea = self._brief.idea
        if self._brief.prior is not None:
            lock, lock_in, self._prior_tail = await self._read_prior(self._brief.prior)
            self._lock = lock
            prior_ins = [lock_in]
            self._prior_context = prior_prompts.prior_context(
                lock,
                mode=self._brief.prior.mode,
                direction=self._brief.idea,
                part=self._brief.prior.part,
                style=prior_prompts.style_line(self._blobs.read_exact(self._brief.prior.text_digest).decode("utf-8")),
            )
            idea = self._prior_context
        carried = self._book_state()
        if carried is not None:
            # A later part keeps the book's cast, bibles and style byte for byte (ADR-0116).
            assert self._book is not None
            assert self._book.state_digest is not None
            source = ("book_state", self._book.state_digest)
            self._title = carried.title
            seed_raw = await self._ensure(
                "seed",
                inputs=[source],
                decoding=PLANNING,
                produce=_constant(StorySeed.model_validate(carried.seed).model_dump_json().encode("utf-8")),
            )
            bible_raw = await self._ensure(
                "story_bible",
                inputs=[source],
                decoding=PLANNING,
                produce=_constant(StoryBibleOut.model_validate(carried.story_bible).model_dump_json().encode("utf-8")),
            )
            style_raw = await self._ensure(
                "style_bible",
                inputs=[source],
                decoding=PLANNING,
                produce=_constant(StyleBibleOut.model_validate(carried.style_bible).model_dump_json().encode("utf-8")),
            )
            seed = StorySeed.model_validate_json(seed_raw)
            seed_in = ("seed", content_digest(seed_raw))
            bible = StoryBibleOut.model_validate_json(bible_raw)
            bible_in = ("story_bible", content_digest(bible_raw))
            style = StyleBibleOut.model_validate_json(style_raw)
            style_in = ("style_bible", content_digest(style_raw))
        else:
            seed_prompt = planning.seed_prompt(idea=idea, genre=self._brief.genre)
            cast = SHORT_SEED
            if self._book is not None:
                cast = (books.BOOK_SEED_CHARACTERS, books.BOOK_SEED_LOCATIONS)
                seed_prompt = (
                    f"Đây là hạt giống cho một TIỂU THUYẾT {self._book.spec.chapters} chương: dựng dàn nhân vật và "
                    f"bối cảnh đủ cho truyện dài (tối đa {cast[0]} nhân vật, {cast[1]} địa điểm).\n\n{seed_prompt}"
                )

            async def produce_seed(epoch: int) -> bytes:
                raw = await self._json(
                    "seed", epoch, StoryStepKind.SEED, planning.PLANNING_SYSTEM, seed_prompt, books.bound_seed(*cast)
                )
                drawn = StorySeed.model_validate_json(raw)
                missing = missing_idea_names(idea, drawn)
                problems = seed_problems(drawn)
                if not missing and not problems:
                    return raw
                # One more draw names everything the first lacked: the idea's own characters (ADR-0127) and the
                # seed's foundation problems (donor shenbi validates the seed before the pipeline starts).
                lacks = []
                if missing:
                    lacks.append(f"bỏ mất nhân vật của ý tưởng: {', '.join(missing)} (giữ đúng tên và vai như ý tưởng)")
                lacks.extend(problems)
                again = f"{seed_prompt}\n\nLần trước seed chưa đạt: " + "; ".join(lacks) + "."
                return await self._json(
                    "seed", epoch, StoryStepKind.SEED, planning.PLANNING_SYSTEM, again, books.bound_seed(*cast)
                )

            seed_raw = await self._ensure("seed", inputs=[brief, *prior_ins], decoding=PLANNING, produce=produce_seed)
            seed = StorySeed.model_validate_json(seed_raw)
            seed_in = ("seed", content_digest(seed_raw))
            bible_raw = await self._ensure(
                "story_bible",
                inputs=[seed_in, *prior_ins],
                decoding=PLANNING,
                produce=lambda e: self._json(
                    "story_bible",
                    e,
                    StoryStepKind.BIBLE,
                    planning.PLANNING_SYSTEM,
                    self._with_prior(planning.story_bible_prompt(seed)),
                    StoryBibleOut,
                ),
            )
            bible = StoryBibleOut.model_validate_json(bible_raw)
            bible_in = ("story_bible", content_digest(bible_raw))
            style_raw = await self._ensure(
                "style_bible",
                inputs=[seed_in, bible_in, *prior_ins],
                decoding=PLANNING,
                produce=lambda e: self._json(
                    "style_bible",
                    e,
                    StoryStepKind.BIBLE,
                    planning.PLANNING_SYSTEM,
                    self._with_prior(planning.style_bible_prompt(seed, bible)),
                    StyleBibleOut,
                ),
            )
            style = StyleBibleOut.model_validate_json(style_raw)
            style_in = ("style_bible", content_digest(style_raw))
        self._pack = pack_for(self._brief.genre, seed.genre)
        if self._book is not None:
            plan, plan_in = await self._book_plan(seed_in, bible_in, seed, bible, carried)
            seed = books.merged_seed(seed, plan.book_outline())
            self._plan = plan
            self._memory = carried.memory if carried is not None else books.initial_memory(plan)
            memory_in = ("book_memory", content_digest(self._memory.model_dump_json().encode("utf-8")))
            self._book_ins = [plan_in, memory_in]
            part = self._book
            outline_raw = await self._ensure(
                "outline",
                inputs=[plan_in],
                decoding=PLANNING,
                produce=_constant(
                    json.dumps(
                        {"outline": books.part_outline(plan, part).model_dump(), "review_problems": []},
                        ensure_ascii=False,
                    ).encode("utf-8")
                ),
            )
        else:
            outline_raw = await self._ensure(
                "outline", inputs=[seed_in, *prior_ins], decoding=PLANNING, produce=lambda e: self._outline(e, seed)
            )
        outline = ShortOutline.model_validate(json.loads(outline_raw)["outline"])
        outline_in = ("outline", content_digest(outline_raw))

        names, locations = entity_keys(seed)
        plans: list[ChapterPlan] = []
        plan_ins: list[tuple[str, str]] = []
        for c in range(1, self._chapters + 1):
            previous = tuple(plans)
            node = chapter_plan(c)
            raw = await self._ensure(
                node,
                inputs=[seed_in, bible_in, outline_in, *plan_ins, *prior_ins, *self._book_ins],
                decoding=PLANNING,
                produce=lambda e, c=c, previous=previous: self._chapter_plan(
                    e, c, seed, bible, outline, previous, names, locations
                ),
            )
            plans.append(ChapterPlan.model_validate_json(raw))
            plan_ins.append((node, content_digest(raw)))

        if self._lock is not None and self._brief.prior is not None and self._brief.prior.mode == "variant":
            await self._variant_review(outline, plans, plan_ins)

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
        if self._book is not None:
            await self._commit_book_state(story)
        return story

    # --- the book (ADR-0116) -----------------------------------------------------------------------

    def _safety(self) -> SafetyLevel:
        """The brief's content safety level (ADR-0121); a variant for readers from 12 is always ``strict``."""
        prior = self._brief.prior
        if prior is not None and prior.origin == "young-readers":
            return "strict"
        return self._brief.content_safety

    def _first(self) -> int:
        """The book-wide number of this run's first chapter."""
        return 1 if self._book is None else self._book.first_chapter

    def _ends_story(self) -> bool:
        return self._book is None or self._book.is_last

    async def _book_plan(
        self,
        seed_in: tuple[str, str],
        bible_in: tuple[str, str],
        seed: StorySeed,
        bible: StoryBibleOut,
        carried: books.BookState | None,
    ) -> tuple[books.BookPlan, tuple[str, str]]:
        """The book's skeleton, then each volume's chapter rows; a later part reads the plan its book committed."""
        assert self._book is not None
        if carried is not None:
            return carried.plan, ("book_plan", content_digest(carried.plan.model_dump_json().encode("utf-8")))
        spec = self._book.spec
        volumes = spec.volumes()
        outline_raw = await self._ensure(
            "book_outline",
            inputs=[seed_in, bible_in],
            decoding=PLANNING,
            produce=lambda e: self._json(
                "book_outline",
                e,
                StoryStepKind.BOOK_PLANNING,
                book_prompts.BOOK_SYSTEM,
                self._with_prior(
                    book_prompts.book_outline_prompt(seed, bible, chapters=spec.chapters, volumes=volumes)
                ),
                books.bound_book_outline(len(volumes)),
            ),
        )
        outline = books.BookOutline.model_validate_json(outline_raw)
        previous_in = ("book_outline", content_digest(outline_raw))
        rows: tuple[books.PlannedRow, ...] = ()
        hooks: tuple[books.Hook, ...] = ()
        for v, (first, last) in enumerate(volumes):
            node = f"book_chapters[{v + 1}]"
            raw = await self._ensure(
                node,
                inputs=[previous_in],
                decoding=PLANNING,
                produce=lambda e, node=node, v=v, first=first, last=last, rows=rows, hooks=hooks: self._volume_rows(
                    node, e, outline, v, first, last, rows, hooks
                ),
            )
            data = json.loads(raw)
            rows = tuple(books.PlannedRow.model_validate(r) for r in data["rows"])
            hooks = tuple(books.Hook.model_validate(h) for h in data["hooks"])
            previous_in = (node, content_digest(raw))
        plan = books.BookPlan(outline=outline.model_dump(mode="json"), rows=rows, hooks=hooks)
        return plan, ("book_plan", content_digest(plan.model_dump_json().encode("utf-8")))

    async def _volume_rows(
        self,
        node: str,
        epoch: int,
        outline: books.BookOutline,
        volume: int,
        first: int,
        last: int,
        rows: tuple[books.PlannedRow, ...],
        hooks: tuple[books.Hook, ...],
    ) -> bytes:
        """One volume's rows in chunks: code checks sent back for revision at most ``PLAN_REVISIONS`` times, then
        one judged review and one revision kept only if the code checks still pass."""
        assert self._book is not None
        total = self._book.spec.chapters
        start = first
        settled: list[str] = []
        while start <= last:
            count = min(books.ROWS_PER_CALL, last - start + 1)
            model = books.bound_rows(count, [*books.open_hook_ids(hooks), *books.next_hook_ids(hooks, 2 * count)])
            base = self._with_prior(
                book_prompts.book_rows_prompt(
                    outline,
                    volume=volume,
                    first=start,
                    count=count,
                    total=total,
                    earlier=rows,
                    open_hooks=[h for h in hooks if h.paid is None],
                    next_id=len(hooks) + 1,
                )
            )

            async def generate(prompt: str, model: type[books.BookRows] = model) -> list[books.BookRow]:
                text = await self._step(
                    node,
                    epoch,
                    kind=StoryStepKind.BOOK_PLANNING,
                    system=book_prompts.BOOK_SYSTEM,
                    prompt=prompt,
                    decoding=PLANNING,
                    model=model,
                )
                return list(books.BookRows.model_validate_json(model.model_validate_json(text).model_dump_json()).rows)

            generated = await generate(base)
            added, ledger = books.add_rows(rows, hooks, generated, first=start, total=total)
            problems = books.plan_problems(added, ledger, total=total)
            for _ in range(books.PLAN_REVISIONS):
                if not problems:
                    break
                generated = await generate(book_prompts.book_rows_revision_prompt(base, generated, problems))
                added, ledger = books.add_rows(rows, hooks, generated, first=start, total=total)
                problems = books.plan_problems(added, ledger, total=total)
            if problems:
                # What the revisions left is settled in code (ADR-0116 amendment): a plan never stops the run.
                added, ledger, notes = books.settle_plan(added, ledger, total=total)
                settled.extend(notes)
            review = OutlineReview.model_validate_json(
                await self._step(
                    node,
                    epoch,
                    kind=StoryStepKind.BOOK_PLANNING,
                    system=book_prompts.BOOK_SYSTEM,
                    prompt=book_prompts.book_rows_review_prompt(outline, volume, added[len(rows) :]),
                    decoding=REVIEW,
                    model=OutlineReview,
                    judge=True,
                )
            )
            if review.problems:
                revised = await generate(book_prompts.book_rows_revision_prompt(base, generated, review.problems))
                again, again_ledger = books.add_rows(rows, hooks, revised, first=start, total=total)
                if not books.plan_problems(again, again_ledger, total=total):
                    added, ledger = again, again_ledger
            rows, hooks = added, ledger
            start += count
        return json.dumps(
            {
                "rows": [r.model_dump(mode="json") for r in rows],
                "hooks": [h.model_dump(mode="json") for h in hooks],
                "settled": settled,
            },
            ensure_ascii=False,
        ).encode("utf-8")

    def _book_note(self, chapter: int) -> str:
        """The book row and memory a chapter plan receives: role, hooks to plant and pay, what came before."""
        assert self._plan is not None
        number = self._first() + chapter - 1
        row = next(r for r in self._plan.rows if r.chapter == number)
        hooks = {h.hook_id: h for h in self._plan.hooks}
        lines = [f"[Chương {number} trong tiểu thuyết — vai trò: {row.role.value}]"]
        if row.plants:
            lines.append("Phục bút phải cài trong chương: " + "; ".join(hooks[h].text for h in row.plants))
        if row.payoffs:
            lines.append("Phục bút phải giải trong chương: " + "; ".join(hooks[h].text for h in row.payoffs))
        memory = books.memory_block(self._memory, self._plan, chapter=number)
        return "\n".join(lines) + (f"\n\n{memory}" if memory else "")

    async def _chapter_text(self, refs: Sequence[SceneRef]) -> str:
        return "\n\n".join([json.loads(await self._head(r.node_id))["prose"] for r in refs])

    async def _chapter_digest(self, chapter: int, refs: Sequence[SceneRef]) -> tuple[str, str]:
        """The memory of an accepted chapter: extracted from its text, names attested. A short story has no hooks."""
        number = self._first() + chapter - 1
        text = await self._chapter_text(refs)
        known = [(h.hook_id, h.text) for h in self._memory.hooks if h.status != "resolved" and h.planted <= number]
        node = f"chapter_digest[{chapter}]"

        async def produce(epoch: int) -> bytes:
            raw = await self._json(
                node,
                epoch,
                StoryStepKind.BOOK_MEMORY,
                book_prompts.MEMORY_SYSTEM,
                book_prompts.chapter_digest_prompt(number, text, known),
                books.bound_digest([hook_id for hook_id, _ in known]),
            )
            digest = books.attest_digest(books.ChapterDigest.model_validate_json(raw), text)
            return digest.model_dump_json().encode("utf-8")

        raw = await self._ensure(
            node, inputs=[("chapter", content_digest(text.encode("utf-8")))], decoding=PLANNING, produce=produce
        )
        return node, content_digest(raw)

    def _open_hooks(self, digests: Sequence[tuple[int, books.ChapterDigest]]) -> list[books.HookStatus]:
        folded = books.fold(self._memory, digests, part=0, part_summary="", tail="")
        return [h for h in folded.hooks if h.status != "resolved"]

    async def _close_open_hooks(self, final_scene: str) -> None:
        """The book's last chapter: the final scene is rewritten once with the hooks still open (ADR-0117)."""
        open_hooks = self._open_hooks(await self._digests(self._chapters + 1))
        if not open_hooks:
            return
        state = await self._store.load()
        if any(n.startswith(HOOKS_NOTE) for n in state.intents.get(final_scene, ())):
            return
        note = HOOKS_NOTE + "; ".join(f"{h.hook_id}: {h.text}" for h in open_hooks)
        await self._store.apply(lambda s: (add_intent(s, node_ids=(final_scene,), note=note), None))
        raise _Restart(final_scene)

    async def _book_findings(self) -> list[Finding]:
        """Hooks the plan pays in a chapter whose digest does not resolve them; at the book's end, any still open."""
        assert self._plan is not None
        digests = await self._digests(self._chapters + 1)
        findings: list[Finding] = []
        for number, digest in digests:
            row = next(r for r in self._plan.rows if r.chapter == number)
            resolved = {str(getattr(op.hook, "value", op.hook)) for op in digest.hooks if op.op == "resolved"}
            node = f"chapter_digest[{number - self._first() + 1}]"
            findings.extend(
                Finding("HOOK_NOT_PAID", Severity.STYLISTIC, node, f"{hook} planned for chapter {number} stays open")
                for hook in row.payoffs
                if hook not in resolved
            )
        if self._ends_story():
            findings.extend(
                Finding("HOOK_OPEN_AT_END", Severity.STYLISTIC, "manuscript", f"{h.hook_id} stays open: {h.text}")
                for h in self._open_hooks(digests)
            )
        return findings

    async def _variant_review(
        self, outline: ShortOutline, plans: Sequence[ChapterPlan], plan_ins: Sequence[tuple[str, str]]
    ) -> None:
        """The variant's plans against the source spine; one automatic outline note, then an exception."""
        assert self._lock is not None
        events = list(self._lock.chapter_events)
        prompt = variant_review_prompt(events, outline, plans, self._brief.idea)

        async def produce(epoch: int) -> bytes:
            review = VariantReview.model_validate_json(
                await self._step(
                    "variant_review",
                    epoch,
                    kind=StoryStepKind.OUTLINE,
                    system=planning.PLANNING_SYSTEM,
                    prompt=prompt,
                    decoding=REVIEW,
                    model=VariantReview,
                    judge=True,
                )
            )
            lost = sorted({i for i in (*review.missing, *review.contradicted) if 1 <= i <= len(events)})
            return json.dumps({"lost": lost, "notes": review.notes}, ensure_ascii=False).encode("utf-8")

        raw = await self._ensure("variant_review", inputs=list(plan_ins), decoding=REVIEW, produce=produce)
        lost = json.loads(raw)["lost"]
        if not lost:
            return
        state = await self._store.load()
        if any(n.startswith(VARIANT_NOTE) for n in state.intents.get("outline", ())):
            return
        note = VARIANT_NOTE + "; ".join(f"{i}. {events[i - 1]}" for i in lost)
        await self._store.apply(lambda s: (add_intent(s, node_ids=("outline",), note=note), None))
        raise _Restart("outline")

    async def _variant_findings(self) -> list[Finding]:
        if self._lock is None or not (await self._store.load()).nodes.get("variant_review"):
            return []
        lost = json.loads(await self._head("variant_review"))["lost"]
        return [
            Finding(
                "VARIANT_SPINE",
                Severity.NARRATIVE_CRITICAL,
                "outline",
                f"the variant drops or contradicts source event {i}: {self._lock.chapter_events[i - 1]}",
            )
            for i in lost
        ]

    async def _digests(self, upto: int) -> list[tuple[int, books.ChapterDigest]]:
        """The digests of this run's chapters before ``upto``, numbered across the book."""
        found = []
        for c in range(1, upto):
            raw = await self._head(f"chapter_digest[{c}]")
            found.append((self._first() + c - 1, books.ChapterDigest.model_validate_json(raw)))
        return found

    async def _commit_book_state(self, story: _Story) -> None:
        """The part's summary, then the book state the next part reads."""
        assert self._book is not None
        assert self._plan is not None
        digests = await self._digests(self._chapters + 1)
        digest_ins = [(f"chapter_digest[{c}]", content_digest(d.model_dump_json().encode())) for c, d in digests]
        summary_raw = await self._ensure(
            "part_summary",
            inputs=digest_ins,
            decoding=PLANNING,
            produce=lambda e: self._json(
                "part_summary",
                e,
                StoryStepKind.BOOK_MEMORY,
                book_prompts.MEMORY_SYSTEM,
                book_prompts.part_summary_prompt(
                    self._book.part if self._book else 1, [(c, d.summary) for c, d in digests]
                ),
                books.PartSummary,
            ),
        )
        summary = books.PartSummary.model_validate_json(summary_raw).summary
        refs = scene_refs(story.outline_input)
        text = await self._chapter_text(refs)
        packaged = Packaging.model_validate(json.loads(await self._head("packaging"))["packaging"])
        title = self._title or packaging_prompts.best_title(
            packaged, [c.name for c in story.seed.characters], story.seed.working_title
        )
        state = books.BookState(
            spec=self._book.spec,
            parts_done=self._book.part,
            title=title,
            plan=self._plan,
            seed=story.seed.model_dump(mode="json"),
            story_bible=story.bible.model_dump(mode="json"),
            style_bible=story.style.model_dump(mode="json"),
            memory=books.fold(self._memory, digests, part=self._book.part, part_summary=summary, tail=text),
        )
        await self._ensure(
            "book_state",
            inputs=[("part_summary", content_digest(summary_raw)), ("title", title), *digest_ins, *self._book_ins],
            decoding=PLANNING,
            produce=_constant(state.model_dump_json().encode("utf-8")),
        )

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
                model=bound_short_outline(),
            )

        base_prompt = self._with_prior(outline_prompts.outline_prompt(seed))
        notes = (await self._store.load()).intents.get("outline", ())
        if notes:
            base_prompt += "\n\n[Yêu cầu sửa dàn ý]\n" + "\n".join(f"- {n}" for n in notes)
        outline = ShortOutline.model_validate_json(await generate(base_prompt))
        review = OutlineReview.model_validate_json(
            await self._step(
                "outline",
                epoch,
                kind=StoryStepKind.OUTLINE,
                system=outline_prompts.OUTLINE_SYSTEM,
                prompt=self._with_prior(outline_prompts.outline_review_prompt(seed, outline, idea=self._brief.idea)),
                decoding=REVIEW,
                model=OutlineReview,
                judge=True,
            )
        )
        problems = [*outline_prompts.deterministic_outline_problems(outline), *review.problems]
        if problems:
            outline = ShortOutline.model_validate_json(
                await generate(self._with_prior(outline_prompts.outline_revision_prompt(seed, outline, problems)))
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
        prompt = self._with_prior(
            planning.chapter_plan_prompt(
                chapter_number=chapter,
                outline=outline,
                bible=bible,
                character_names=list(names),
                location_names=list(locations),
                previous_plans=previous,
                first_chapter=self._first(),
                ends_story=self._ends_story(),
            )
        )
        if self._book is not None:
            prompt = f"{self._book_note(chapter)}\n\n---\n\n{prompt}"
        node = chapter_plan(chapter)
        state = await self._store.load()
        notes = state.intents.get(node, ())
        if notes:
            # A replan sees the plan that failed as well as every failure, so it changes what failed instead of
            # drawing a new plan with the same contradiction (donor shenbi 0cdc218).
            failed = state.node(node).head_revision_id
            if failed is not None:
                old = ChapterPlan.model_validate_json(self._blobs.read_exact(state.revisions[failed].digest))
                prompt += "\n\n[Kế hoạch lần trước — đã thất bại, không lặp lại]\n" + json.dumps(
                    old.model_dump(include={"chapter_goal", "withheld_cards", "required_changes_by_end", "do_not"}),
                    ensure_ascii=False,
                )
            prompt += "\n\n[Yêu cầu sửa kế hoạch]\n" + "\n".join(f"- {n}" for n in notes)

        # A book chapter needs enough scenes to reach its length: a scene holds at most 1 000 syllables.
        min_scenes = 3
        if self._book is not None:
            min_scenes = min(SCENES_PER_CHAPTER_MAX, max(3, -(-self._book.spec.chapter_syllables // 1000)))
            prompt += (
                f"\n\nChương này dài khoảng {self._book.spec.chapter_syllables} chữ: chia ít nhất {min_scenes} cảnh."
            )
        bound = bound_chapter_plan(list(names), list(locations), min_scenes=min_scenes)

        async def generate(text: str) -> tuple[ChapterPlan, list[str]]:
            plan = ChapterPlan.model_validate_json(
                await self._step(
                    node,
                    epoch,
                    kind=StoryStepKind.SCENE_CONTRACT,
                    system=planning.PLANNING_SYSTEM,
                    prompt=text,
                    decoding=PLANNING,
                    model=bound,
                )
            )
            unknown = sorted(
                {s.pov for s in plan.scenes if planning.resolve_name(s.pov, names) is None}
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
            raise Blocked(RunPhase.BLOCKED_QUALITY, f"{node}: POV or location outside the bible: {', '.join(unknown)}")
        review = OutlineReview.model_validate_json(
            await self._step(
                node,
                epoch,
                kind=StoryStepKind.SCENE_CONTRACT,
                system=planning.PLANNING_SYSTEM,
                prompt=planning.chapter_plan_review_prompt(plan, chapter),
                decoding=REVIEW,
                model=OutlineReview,
                judge=True,
            )
        )
        # Contradictions are caught here, before any scene is drafted on an unsatisfiable plan (donor shenbi
        # chapter_planning gates); they go into the one revision the review already allows.
        problems = [*review.problems, *plan_conflicts(plan)]
        if problems:
            revised, unknown = await generate(planning.chapter_plan_revision_prompt(prompt, plan, problems))
            if (not unknown and not plan_conflicts(revised)) or (
                not unknown and len(plan_conflicts(revised)) < len(plan_conflicts(plan))
            ):
                plan = revised
        return plan.model_dump_json().encode("utf-8")

    # --- scenes and the chapter loop ---------------------------------------------------------------

    def _plan_state(self, story: _Story) -> tuple[Any, str, Any, Any]:
        delta = build_genesis_delta(
            self._identity,
            story.bible_input,
            created_by=f"run:{self._identity.run_id}",
            created_at=self._started,
            base=self._canon_base,
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
        for c in range(1, self._chapters + 1):
            chapter_refs = [r for r in refs if r.chapter == c]
            for cycle in range(REVIEW_CYCLES + 1):
                for ref in chapter_refs:
                    await self._ensure_scene(
                        story, ref, refs, delta, version, proposal, plan, [seed_in, bible_in, style_in, plan_ins[c - 1]]
                    )
                if cycle == REVIEW_CYCLES or not await self._review_chapter(story, c, chapter_refs, final=False):
                    break
            await self._review_chapter(story, c, chapter_refs, final=True)
            if self._digesting and (self._book is not None or c < self._chapters):
                await self._chapter_digest(c, chapter_refs)
            if self._book is not None and c == self._chapters and self._ends_story():
                await self._close_open_hooks(chapter_refs[-1].node_id)

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
        # A book scene sees its own chapter, or the scene just before; the book memory stands for the rest.
        visible = [
            acceptances[i] for i in recent_indices(refs, ref.global_index, chapter_window=self._book is not None)
        ]
        memory = ""
        if self._book is None and self._digesting and ref.chapter > 1:
            digests = await self._digests(ref.chapter)
            inputs = [
                *inputs,
                *((f"chapter_digest[{c}]", content_digest(d.model_dump_json().encode())) for c, d in digests),
            ]
            memory = books.short_memory_block(
                digests, names=story.plans[ref.chapter - 1].scenes[ref.scene - 1].characters
            )
        if self._book is not None:
            digests = await self._digests(ref.chapter)
            inputs = [
                *inputs,
                *(
                    (f"chapter_digest[{c - self._first() + 1}]", content_digest(d.model_dump_json().encode()))
                    for c, d in digests
                ),
            ]
            assert self._plan is not None
            memory = books.memory_block(
                books.fold(self._memory, digests, part=0, part_summary="", tail="") if digests else self._memory,
                self._plan,
                chapter=self._first() + ref.chapter - 1,
                names=story.plans[ref.chapter - 1].scenes[ref.scene - 1].characters,
            )
        readers = provisional_readers(
            self._identity,
            story.bible_input,
            canon_view=provisional_canon_view(delta, self._canon_base),
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
            recent_decision_ids=[a.decision_id for a in visible],
        )
        binding = {"context_pack_id": pack.context_pack_id, "context_content_hash": pack.content_hash}
        if self._book is None:
            context = drafting.render_context(pack, story.names, memory=memory)
        else:
            context = drafting.render_context(pack, story.names, openings=max(0, ref.scene - 2), memory=memory)
        chapter = story.plans[ref.chapter - 1]
        planned = chapter.scenes[ref.scene - 1]
        is_last = ref.scene == len(chapter.scenes)
        is_final = is_last and ref.chapter == self._chapters and self._ends_story()
        story_target = (
            self._brief.story_target_syllables
            if self._book is None
            else self._book.spec.chapter_syllables * self._chapters
        )
        target = drafting.target_syllables_for(chapter.scenes, story_target=story_target, chapters=self._chapters)
        allowed = _allowed_names(story)
        earlier = [a.revision.normalized_content for a in acceptances]

        async def produce(epoch: int) -> bytes:
            state = await self._store.load()
            note = "\n".join(state.intents.get(ref.node_id, ())) or None
            prompt = drafting.scene_draft_prompt(
                context=context,
                scene=planned,
                plan=chapter,
                chapter_number=self._first() + ref.chapter - 1,
                scene_number=ref.scene,
                is_last_scene_of_chapter=is_last,
                is_final_scene=is_final,
                target_syllables=target,
                revision_note=note,
                genre_rules=craft_rules(self._pack),
                voice=drafting.voice_block(story.seed, story.style, story.bible),
                chapter_first=ref.scene == 1,
                story_first=ref.scene == 1 and ref.chapter == 1 and self._first() == 1 and self._brief.prior is None,
            )
            prior = self._brief.prior
            if (
                self._prior_tail
                and prior is not None
                and prior.mode == "continuation"
                and (ref.chapter, ref.scene) == (1, 1)
            ):
                # The seam: the new part opens right after the prior text's last lines, never retelling them.
                prompt = (
                    "PHẦN TRƯỚC KẾT THÚC BẰNG ĐOẠN SAU (không kể lại, viết nối tiếp ngay sau đó):\n<<<\n"
                    f"{self._prior_tail}\n>>>\n\n{prompt}"
                )
            prose, findings = await self._draft_until_clean(
                ref.node_id,
                epoch,
                prompt,
                context,
                allowed,
                planned.dialogue_required,
                target,
                earlier,
                cast=story.seed.characters,
                pov=planned.pov,
                person=story.seed.pov,
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
        *,
        cast: Sequence[SeedCharacter] = (),
        pov: str | None = None,
        person: str | None = None,
    ) -> tuple[str, tuple[Finding, ...]]:
        bounds = drafting.paragraph_bounds(target)
        try:
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
        except Blocked:
            # The round's calls are spent before this contract got a draft (an earlier scene changed after this
            # scene's own repairs): Shenbi keeps the best version written so far and marks it for the Human.
            state = await self._store.load()
            if state.node(node).head_revision_id is None:
                raise
            kept = json.loads(await self._head(node))["prose"]
            checked = check_scene_prose(
                kept,
                node_id=node,
                window=self._window,
                allowed_names=allowed,
                requires_dialogue=dialogue,
                earlier=earlier,
            )
            note = Finding(
                "BEST_VERSION_KEPT",
                Severity.NARRATIVE_CRITICAL,
                node,
                ESCALATED_MARK + "cảnh trước đã đổi sau khi cảnh này hết lượt viết lại; giữ bản đã viết, cần đọc lại",
            )
            findings, blocking = escalate_or_block((*checked, note))
            if blocking:
                raise
            return kept, tuple(findings)
        history: list[str] = []
        best: tuple[str, tuple[Finding, ...]] | None = None
        while True:
            # Certain fixes first, with no model call: a misspelt character name, a narration sentence opening with
            # the wrong gender (ADR-0127; donor huohuo deterministic continuity fixes).
            # The point-of-view character named where the narration only calls them by their address.
            prose = name_pov(cast, pov, fix_gender_openings(cast, fix_near_names(prose, allowed)))
            findings = (
                *check_scene_prose(
                    prose,
                    node_id=node,
                    window=self._window,
                    allowed_names=allowed,
                    requires_dialogue=dialogue,
                    earlier=earlier,
                ),
                *pov_findings(cast, pov, prose, node_id=node),
                *pov_person_findings(person, prose, node_id=node, syllables=count_syllables(prose)),
            )
            if best is None or _weight(findings) <= _weight(best[1]):
                best = (prose, findings)
            repairable = [f for f in findings if f.severity in REPAIRABLE]
            if not repairable:
                return prose, findings
            try:
                if any(f.code == "SCENE_TOO_SHORT" for f in repairable):
                    prose = await self._step(
                        node,
                        epoch,
                        kind=StoryStepKind.SCENE_DRAFT,
                        system=drafting.DRAFT_SYSTEM,
                        # Measured numbers make a retry actionable (donor shenbi 5b517c3: a generic retry message
                        # failed three attempts in a row).
                        prompt=prompt
                        + REGENERATE_NOTE
                        + f" Bản trước có {count_syllables(prose)} chữ; cần khoảng {target} chữ, đúng {bounds[0]} đoạn.",
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
                prose = await self._repair_once(node, epoch, prose, repairable, context, history)
            except Blocked:
                kept, blocking = escalate_or_block(best[1])
                if blocking:
                    raise
                return best[0], tuple(kept)

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
            if error.code in TRANSPORT:
                await self._outage(error)
                return prose
            if error.code not in RETRYABLE:
                raise
            history.append(f"{error.code.value}")
            return prose
        self._outages = 0
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
        facts = "\n".join(f"- {c.name}: {c.locked_line()}" for c in story.seed.characters)
        if self._digesting and chapter > 1:
            # The continuity judge reads what earlier chapters actually wrote, not what their plans meant to.
            previous = " ".join(d.summary for _c, d in await self._digests(chapter))
        else:
            previous = " ".join(p.chapter_goal for p in story.plans[: chapter - 1])
        findings: list[Finding] = [f for n, h in heads.items() for f in anti_ai_findings(h["prose"], node_id=n)]
        findings.extend(fatigue_findings(self._pack, [(n, h["prose"]) for n, h in heads.items()]))
        findings.extend(gender_findings(story.seed.characters, scenes))
        # Scenes accepted before these checks existed are held to them here: a letter of another script, a point-of-
        # view character never named, narration calling someone "em".
        for ref in refs:
            prose = heads[ref.node_id]["prose"]
            alien = foreign_script(prose, [c.name for c in story.seed.characters])
            if alien:
                index = alien[0][0]
                findings.append(
                    Finding(
                        "FOREIGN_SCRIPT",
                        Severity.HARD_INTEGRITY,
                        ref.node_id,
                        "chữ của ngôn ngữ khác trong lời văn; viết lại bằng tiếng Việt",
                        prose[max(0, index - 20) : index + 20],
                    )
                )
            for code, leaks in (("JSON_LEAK", json_leaks(prose)), ("NOTES_LEAK", notes_leaks(prose))):
                if leaks:
                    findings.append(
                        Finding(code, Severity.HARD_STRUCTURAL, ref.node_id, "notes or JSON in prose", leaks[0][:120])
                    )
            pov = plan.scenes[ref.scene - 1].pov if ref.scene <= len(plan.scenes) else None
            findings.extend(pov_findings(story.seed.characters, pov, prose, node_id=ref.node_id))
            findings.extend(
                pov_person_findings(story.seed.pov, prose, node_id=ref.node_id, syllables=count_syllables(prose))
            )
        if refs:
            last = max(refs, key=lambda r: r.scene)
            findings.extend(
                closing_hook_findings(plan.closing_hook, heads[last.node_id]["prose"], node_id=last.node_id)
            )
        for dimension in CHAPTER_DIMENSIONS:
            result = await self._judge(
                node,
                lambda step_id, decoding, dimension=dimension: audit_chapter(
                    self._judge_gateway,
                    scope=self._scope,
                    selection=self._brief.judge,
                    step_id=step_id,
                    context_digest=self._brief.digest(),
                    decoding=decoding,
                    dimension=dimension,
                    chapter_number=chapter,
                    scenes=scenes,
                    plan=plan,
                    facts=facts,
                    previous_summary=previous,
                    safety=self._safety(),
                ),
            )
            findings.extend(result.findings)
            state = await self._store.load()
        claims = [i for i, f in enumerate(findings) if f.blocking and ":" in f.code]
        # Safety claims are always read a second time (ADR-0117), then structural ones.
        safety = f"{AuditDimension.SAFETY.value}:"
        claims.sort(
            key=lambda i: (
                not findings[i].code.startswith(safety),
                findings[i].severity is not Severity.HARD_STRUCTURAL,
            )
        )
        second_reading = set(claims[:CONFIRM_MAX])
        findings = [
            await self._confirmed(node, f, scenes, plan) if i in second_reading else f for i, f in enumerate(findings)
        ]
        repairable = [f for f in findings if f.severity in REPAIRABLE]
        repairable.extend(humanize_targets(findings))
        if not final and repairable:
            changed = False
            for scene_node in sorted({f.node_id for f in repairable}):
                scene_findings = [f for f in repairable if f.node_id == scene_node]
                memo = [f for f in scene_findings if f.code.startswith(f"{AuditDimension.MEMO_COMPLIANCE.value}:")]
                contract = [f for f in memo if f.blocking and not _excess(f)]
                scene_findings = [f for f in scene_findings if f not in memo or _excess(f)]
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
                ref = next(r for r in refs if r.node_id == scene_node)
                kept = [str(k) for k in scene_head.get("fixed", [])]
                context = drafting.scene_repair_context(
                    facts,
                    plan=plan,
                    scene=plan.scenes[ref.scene - 1],
                    is_last=ref.scene == len(plan.scenes),
                    voice=drafting.voice_block(story.seed, story.style, story.bible),
                    kept=kept,
                )
                # Leaked notes and JSON are cut with no model call; what is left goes to the model.
                cut, _notes = deterministic_fixes(
                    scene_head["prose"], [f for f in scene_findings if f.code in _CUT_AT_REVIEW]
                )
                rest = [f for f in scene_findings if f.code not in _CUT_AT_REVIEW]
                try:
                    repaired = (
                        cut if not rest else await self._repair_once(scene_node, scene_epoch, cut, rest, context, [])
                    )
                except Blocked:
                    continue
                if (
                    repaired != scene_head["prose"]
                    and self._no_worse(story, scene_head["prose"], repaired)
                    and not _restores(scene_head, repaired)
                ):
                    fixed = [*kept, *(f"{f.code}: “{f.quote[:80]}”" for f in scene_findings if f.quote)]
                    # Only passages this repair actually removed are guarded against coming back.
                    fixed_quotes = [
                        f.quote
                        for f in scene_findings
                        if f.quote and f.quote in scene_head["prose"] and f.quote not in repaired
                    ]
                    await self._replace_head(
                        scene_node,
                        json.dumps(
                            {
                                **scene_head,
                                "prose": repaired,
                                "fixed": fixed,
                                "fixed_quotes": [*scene_head.get("fixed_quotes", []), *fixed_quotes],
                            },
                            ensure_ascii=False,
                        ).encode("utf-8"),
                    )
                    changed = True
            if changed:
                return True
            # Automatic repair changed nothing: seal now, as a later cycle would audit the same text.
            final = True
        blocking = [f for f in findings if f.blocking]
        contract = f"{AuditDimension.MEMO_COMPLIANCE.value}:"
        if final and blocking and all(f.code.startswith(contract) for f in blocking):
            plan_node = chapter_plan(chapter)
            state = await self._store.load()
            replanned = sum(
                1
                for n in state.intents.get(plan_node, ())
                if n.startswith(AUTO_NOTE) and not n.startswith(ENDING_REPLAN_NOTE)
            )
            if replanned < PLAN_REPLANS:
                # Each replan sees the failed plan and every earlier failure (donor shenbi accumulates failure
                # families so a retry converges); after PLAN_REPLANS the finding goes to the Showrunner.
                note = AUTO_NOTE + PLAN_REPAIR_NOTE + "; ".join(f"{f.message} (trích: “{f.quote}”)" for f in blocking)
                scene_nodes = tuple(ref.node_id for ref in refs)
                await self._store.apply(
                    lambda s: (
                        add_intent(drop_auto_intents(s, scene_nodes), node_ids=(plan_node,), note=note),
                        None,
                    )
                )
                raise _Restart(plan_node)
        if final:
            # ADR-0117: a craft finding still open at the seal is recorded, never a stop or an exception.
            craft = f"{AuditDimension.CRAFT.value}:"
            findings = [
                Finding(f.code, Severity.STYLISTIC, f.node_id, f.message, f.quote) if f.code.startswith(craft) else f
                for f in findings
            ]
            findings, blocking = escalate_or_block(findings)
            if blocking:
                raise Blocked(
                    RunPhase.BLOCKED_QUALITY,
                    f"{node}: " + "; ".join(f"{f.code} {f.node_id}" for f in blocking),
                    blocking,
                )
        record = json.dumps({"findings": [_finding_dict(f) for f in findings]}, ensure_ascii=False).encode("utf-8")
        await self._promote(
            node, record, fp, expected=state.node(node).head_revision_id, epoch=state.node(node).generation_epoch
        )
        return False

    def _no_worse(self, story: _Story, before: str, after: str) -> bool:
        """Shenbi's revision acceptance: a repair is kept only if it adds no integrity or structural finding."""

        def weight(text: str) -> tuple[int, int, int]:
            return _weight(
                check_scene_prose(text, node_id="", window=self._window, allowed_names=_allowed_names(story))
            )

        return weight(after)[:2] <= weight(before)[:2]

    async def _confirmed(
        self, node: str, finding: Finding, scenes: Sequence[tuple[str, str]], plan: ChapterPlan
    ) -> Finding:
        """A blocking audit claim stays blocking only if an independent second reading confirms it."""
        confirmed = await self._judge(
            node,
            lambda step_id, decoding: confirm_finding(
                self._judge_gateway,
                scope=self._scope,
                selection=self._brief.judge,
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
        attempt = 0
        while True:
            state = await self._store.load()
            prefix = step_prefix(state, node)
            used = sum(1 for a in state.attempts if a.kind is AttemptKind.GENERATE and a.step_id.startswith(prefix))
            step_id = f"{prefix}{used + 1}"
            try:
                result = await call(step_id, _decoding(REVIEW, step_id))
                self._outages = 0
                return result
            except StoryStepError as error:
                if error.code in TRANSPORT:
                    await self._outage(error)
                    continue
                attempt += 1
                if error.code not in RETRYABLE or attempt == JUDGE_ATTEMPTS:
                    raise

    async def _outage(self, error: StoryStepError) -> None:
        """Shenbi's dispatch rule: a transport failure is retried after a pause, at most ``len(retry_delays)`` times
        in a row; then the run stops at ``MODEL_UNAVAILABLE`` for the Human's Retry."""
        if self._outages >= len(self._retry_delays):
            raise error
        delay = self._retry_delays[self._outages]
        self._outages += 1
        if delay:
            await asyncio.sleep(delay)

    async def _manuscript_review(self, story: _Story, outline_in: tuple[str, str]) -> None:
        refs = scene_refs(story.outline_input)
        heads = [(ref.node_id, json.loads(await self._head(ref.node_id))["prose"]) for ref in refs]
        inputs = [outline_in, *((n, content_digest(p.encode())) for n, p in heads)]
        reviewed = heads
        synopsis: str | None = None
        ending_note = ENDING_NOTE
        if self._book is not None:
            # A part is judged on its digests and its last chapter in full, so the prompt stays bounded.
            digests = await self._digests(self._chapters)
            synopsis = "\n".join(f"- Chương {c}: {d.summary}" for c, d in digests) or "(không có)"
            reviewed = [h for ref, h in zip(refs, heads, strict=True) if ref.chapter == self._chapters]
            if not self._ends_story():
                ending_note = PART_ENDING_NOTE

        async def produce(epoch: int) -> bytes:
            result = await self._judge(
                "manuscript_review",
                lambda step_id, decoding: critic_manuscript(
                    self._judge_gateway,
                    scope=self._scope,
                    selection=self._brief.judge,
                    step_id=step_id,
                    context_digest=self._brief.digest(),
                    decoding=decoding,
                    scenes=reviewed,
                    outline=story.outline,
                    synopsis=synopsis,
                ),
            )
            last_chapter = [h for ref, h in zip(refs, heads, strict=True) if ref.chapter == refs[-1].chapter]
            findings = [
                await self._ending_confirmed(f, last_chapter, story) if f.code == "NO_ENDING" else f
                for f in result.findings
            ]
            blocking = [f for f in findings if f.blocking]
            final_scene = heads[-1][0]
            if [f.code for f in blocking] == ["NO_ENDING"]:
                state = await self._store.load()
                if ending_note not in state.intents.get(final_scene, ()):
                    await self._store.apply(lambda s: (add_intent(s, node_ids=(final_scene,), note=ending_note), None))
                    raise _Restart(final_scene)
                # The rewrite of the final scene did not close the story: its last chapter is planned once more
                # toward the outline's ending (no donor publishes an unresolved ending automatically).
                last_plan = chapter_plan(refs[-1].chapter)
                if not any(n.startswith(ENDING_REPLAN_NOTE) for n in state.intents.get(last_plan, ())):
                    quote = next((f.quote for f in blocking if f.quote), "")
                    note = ENDING_REPLAN_NOTE + f"{story.outline.ending} (cảnh cuối hiện kết ở: “{quote}”)"
                    await self._store.apply(lambda s: (add_intent(s, node_ids=(last_plan,), note=note), None))
                    raise _Restart(last_plan)
            findings, blocking = escalate_or_block(findings)
            if blocking:
                raise Blocked(
                    RunPhase.BLOCKED_QUALITY,
                    "manuscript_review: " + "; ".join(f.message for f in blocking),
                    blocking,
                )
            return json.dumps(
                {
                    "findings": [_finding_dict(f) for f in findings],
                    "discarded_unquoted": result.discarded_unquoted,
                },
                ensure_ascii=False,
            ).encode("utf-8")

        await self._ensure("manuscript_review", inputs=inputs, decoding=REVIEW, produce=produce)

    async def _ending_confirmed(
        self, finding: Finding, last_chapter: Sequence[tuple[str, str]], story: _Story
    ) -> Finding:
        """The critic's unresolved-ending claim stays blocking only if a second reading of the last chapter, against
        the approved ending, confirms it."""
        claim = Finding(
            finding.code,
            finding.severity,
            finding.node_id,
            (
                f"Chương cuối chưa giải quyết xung đột trung tâm theo kết thúc đã duyệt: {story.outline.ending}"
                if self._ends_story()
                else f"Chương cuối của phần chưa tới bước ngoặt đã định: {story.outline.ending}"
            ),
            finding.quote,
        )
        checked = await self._confirmed("manuscript_review", claim, last_chapter, story.plans[-1])
        return finding if checked.blocking else unconfirmed(finding)

    async def _packaging(self, story: _Story, seed_in: tuple[str, str]) -> None:
        refs = scene_refs(story.outline_input)
        manuscript = "\n\n".join([json.loads(await self._head(r.node_id))["prose"] for r in refs])
        inputs = [seed_in, ("manuscript", content_digest(manuscript.encode()))]
        # The model reads a bounded view of a book part: its digests, first and last chapters. Selling-point
        # quotes are still checked in code against the whole part.
        shown = manuscript
        if self._book is not None:
            digests = await self._digests(self._chapters + 1)
            first = await self._chapter_text([r for r in refs if r.chapter == 1])
            last = await self._chapter_text([r for r in refs if r.chapter == self._chapters])
            synopsis = "\n".join(f"- Chương {c}: {d.summary}" for c, d in digests)
            shown = f"[Tóm tắt các chương]\n{synopsis}\n\n[Chương đầu]\n{first}\n\n[Chương cuối]\n{last}"

        async def produce(epoch: int) -> bytes:
            attempts: list[tuple[Packaging, set[str]]] = []
            for _ in range(2):
                packaging = Packaging.model_validate_json(
                    await self._step(
                        "packaging",
                        epoch,
                        kind=StoryStepKind.PACKAGING,
                        system=packaging_prompts.PACKAGING_SYSTEM,
                        prompt=packaging_prompts.packaging_prompt(
                            manuscript=shown, working_title=story.seed.working_title, premise=story.seed.premise
                        ),
                        decoding=PLANNING,
                        model=Packaging,
                    )
                )
                attempts.append((packaging, set(packaging_prompts.unverified_selling_points(packaging, manuscript))))
                titled = any(
                    not packaging_prompts.title_problems(t.title, [c.name for c in story.seed.characters])
                    for t in packaging.titles
                )
                if titled and len(packaging.selling_points) - len(attempts[-1][1]) >= MIN_VERIFIED_SELLING_POINTS:
                    break
            packaging, unverified = min(attempts, key=lambda a: len(a[1]))
            verified_points = [p for p in packaging.selling_points if p.point not in unverified]
            if len(verified_points) >= MIN_VERIFIED_SELLING_POINTS:
                kept = [p.model_dump() for p in verified_points]
                point_findings: list[Finding] = []
            else:
                kept = [p.model_dump() for p in packaging.selling_points]
                point_findings = [
                    Finding(
                        "SELLING_POINT_UNVERIFIED",
                        Severity.NARRATIVE_CRITICAL,
                        "packaging",
                        f"{ESCALATED_MARK}điểm bán hàng không trích được câu nào trong truyện: {p.point}",
                        p.evidence_quote,
                    )
                    for p in packaging.selling_points
                    if p.point in unverified
                ]
            claims = await self._judge(
                "packaging",
                lambda step_id, decoding, blurbs=packaging.blurbs: unfaithful_blurbs(
                    self._judge_gateway,
                    scope=self._scope,
                    selection=self._brief.judge,
                    step_id=step_id,
                    context_digest=self._brief.digest(),
                    decoding=decoding,
                    blurbs=blurbs,
                    manuscript=shown,
                ),
            )
            flagged = {c.blurb - 1 for c in claims}
            order = sorted(range(len(packaging.blurbs)), key=lambda i: i in flagged)
            blurbs = [packaging.blurbs[i] for i in order]
            verified = Packaging.model_validate({**packaging.model_dump(), "selling_points": kept, "blurbs": blurbs})
            findings = [
                Finding(
                    "BLURB_UNSUPPORTED",
                    Severity.NARRATIVE_CRITICAL,
                    "packaging",
                    f"bản giới thiệu nêu chi tiết không có trong truyện: {c.reason}",
                    c.claim,
                )
                for c in claims
            ]
            return json.dumps(
                {
                    "packaging": verified.model_dump(),
                    "findings": [_finding_dict(f) for f in (*point_findings, *findings)],
                },
                ensure_ascii=False,
            ).encode("utf-8")

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
        packaged = json.loads(await self._head("packaging"))
        packaging = Packaging.model_validate(packaged["packaging"])
        findings.extend(_finding_from(f) for f in packaged["findings"])
        texts = [(scene_draft(c, 1), "\n\n".join(chapters[c])) for c in sorted(chapters)]
        findings.extend(long_span_findings(texts))
        findings.extend(opening_findings(texts))
        reference = self._memory.tail if self._book is not None and self._book.part > 1 else self._prior_tail
        if reference and (self._book is not None or (self._brief.prior and self._brief.prior.mode == "continuation")):
            findings.extend(drift_findings(reference, texts[0][1], node=texts[0][0]))
        if self._book is not None:
            findings.extend(await self._book_findings())
        findings.extend(await self._variant_findings())
        if self._book is None:
            findings.extend(story_length_findings([chapters[c] for c in sorted(chapters)]))
        else:
            target = self._book.spec.chapter_syllables * self._chapters
            findings.extend(part_length_findings([chapters[c] for c in sorted(chapters)], target))
        findings, blocking = escalate_or_block(findings)
        if blocking:
            raise Blocked(RunPhase.BLOCKED_QUALITY, "; ".join(f"{f.code} {f.node_id}" for f in blocking), blocking)
        record = [{**_finding_dict(f), "id": f"F{i + 1:03d}"} for i, f in enumerate(findings)]
        quality: dict[str, Any] = {"findings": record, "packaging": packaging.model_dump()}
        if self._book is not None:
            # The next part reads this state (ADR-0116); it is bound to the approval with the quality record.
            book_state = await self._head("book_state")
            quality["book_state"] = self._blobs.put(book_state)
            quality["book_part"] = self._book.part
        quality_digest = self._blobs.put(json.dumps(quality, ensure_ascii=False).encode("utf-8"))
        exceptions = tuple(
            r["id"]
            for r in record
            if r["severity"] in (Severity.NARRATIVE_CRITICAL.value, Severity.LOCAL_MODEL_LIMIT.value)
        )
        title = packaging_prompts.best_title(
            packaging, [c.name for c in story.seed.characters], story.seed.working_title
        )
        if self._book is not None:
            title = f"{self._title or title} — Phần {self._book.part}"
        export = render_markdown(
            title=title,
            blurb=packaging.blurbs[0],
            chapters=[chapters[c] for c in sorted(chapters)],
            first_chapter=self._first(),
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
            context_window="all" if self._book is None else "chapter",
            canon_parent=(
                None
                if self._canon_base is None
                else (self._canon_base.branch_id, self._canon_base.canon_version_id or "")
            ),
        )


def _constant(data: bytes) -> Callable[[int], Awaitable[bytes]]:
    """A node whose content is copied or computed, not generated."""

    async def produce(_: int) -> bytes:
        return data

    return produce


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


def _restores(scene_head: dict[str, Any], repaired: str) -> bool:
    """Whether a repair brings back a passage an earlier round of review repair removed."""
    return any(len(q) >= 12 and q in repaired for q in scene_head.get("fixed_quotes", []))


def step_prefix(state: RunState, node: str) -> str:
    """Attempts of a node in one round share its call cap. A round ends with a Human revision or retry; for a
    scene or chapter review it also ends when its chapter plan is replanned, since the contract is new; for a chapter
    plan it ends when that plan or an earlier one is replanned, since each regenerates it; for a scene it also ends
    with each rewrite the driver asks for (its own notes)."""
    replans = 0
    if node.startswith(("scene_draft[", "chapter_review[", "chapter_plan[")):
        chapter = int(node.split("[", 1)[1].split(",", 1)[0].rstrip("]"))
        first = 1 if node.startswith("chapter_plan[") else chapter
        replans = sum(len(state.intents.get(chapter_plan(c), ())) for c in range(first, chapter + 1))
    if node == "variant_review":
        # A review of plans the Human or the driver has sent back is a new round.
        replans = sum(
            len(notes) for n, notes in state.intents.items() if n == "outline" or n.startswith("chapter_plan[")
        )
    rewrites = 0
    if node.startswith("scene_draft[") or node == "outline":
        rewrites = sum(1 for n in state.intents.get(node, ()) if n.startswith(AUTO_NOTE))
    suffix = f"+{rewrites}" if rewrites else ""
    return f"{node}@r{len(human_intents(state).get(node, ()))}.{state.retries}.{replans}{suffix}#"


def run_call_bound(
    chapters: int = CHAPTERS,
    scenes_per_chapter: int = SCENES_PER_CHAPTER_MAX,
    *,
    book: books.BookPart | None = None,
    digests: bool = False,
) -> int:
    """Generate calls of a run whose every chapter review fails until repair is spent: each chapter replanned
    PLAN_REPLANS times (regenerating its plan and every later one), every scene drafted and repaired in each review
    cycle of every contract, each review with all its audits and second readings, and the final scene rewritten for its ending.
    Output retries come out of the margin left by nodes that need fewer calls."""
    contracts = 1 + PLAN_REPLANS
    review = len(CHAPTER_DIMENSIONS) + CONFIRM_MAX
    planning = 3 + 3  # seed and bibles; outline, its review and revision
    plans = sum(1 + PLAN_REPLANS * c for c in range(1, chapters + 1)) * PLAN_CALLS
    scenes = chapters * scenes_per_chapter * (1 + REVIEW_CYCLES) * contracts
    reviews = chapters * contracts * (1 + REVIEW_CYCLES) * review
    # The final scene rewritten for its ending, then, if the ending still does not close, the last chapter replanned
    # once: its plan, its scenes in every review cycle and its reviews.
    ending = 1 + (1 + REVIEW_CYCLES) * review
    ending += PLAN_CALLS + scenes_per_chapter * (1 + REVIEW_CYCLES) + (1 + REVIEW_CYCLES) * review
    late = 2 * NODE_CAPS["manuscript_review"] + NODE_CAPS["packaging"] + 1
    memory = 0
    if book is None and digests:
        memory = (chapters - 1) * NODE_CAPS["chapter_digest"]
    if book is not None:
        # ADR-0116: a digest per chapter and the part summary; part 1 also writes the book plan.
        memory = chapters * NODE_CAPS["chapter_digest"] + NODE_CAPS["part_summary"]
        if book.state_digest is None:
            memory += NODE_CAPS["book_outline"] + len(book.spec.volumes()) * NODE_CAPS["book_chapters"]
        if book.is_last:
            # ADR-0117: the final scene rewritten once for open hooks, its chapter reviewed and digested again.
            memory += scenes_per_chapter * contracts + (1 + REVIEW_CYCLES) * review + NODE_CAPS["chapter_digest"]
    return planning + plans + scenes + reviews + ending + late + memory


def variant_call_bound(chapters: int = CHAPTERS) -> int:
    """ADR-0117: the variant review in two rounds and one replan of the outline and every chapter plan."""
    # A chapter plan repaired after its review sends the plans back to the variant review once more.
    return (2 + chapters) * NODE_CAPS["variant_review"] + NODE_CAPS["outline"] + chapters * PLAN_CALLS


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
            StoryEntityInput(key=names[c.name], name=c.name, description=c.locked_line()) for c in seed.characters
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


_EXCESS_MARKERS = ("withheld", "reveal", "do_not", "forbidden", "broken", "violat", "leak")


#: Deterministic and judged machine-voice findings; a scene with this many gets one humanizing repair (ADR-0119).
HUMANIZE_CODES = frozenset({"STOCK_PHRASE", "NOT_BUT_PATTERN", "GENRE_FATIGUE"})
HUMANIZE_MIN = 3


def humanize_targets(findings: Sequence[Finding]) -> list[Finding]:
    """Stylistic machine-voice findings of the scenes that carry at least ``HUMANIZE_MIN`` of them: huohuo's
    humanize loop as a span repair bounded by the chapter's review cycles, never a gate."""
    voice = [
        f
        for f in findings
        if f.severity is Severity.STYLISTIC
        and (f.code in HUMANIZE_CODES or f.code.startswith(f"{AuditDimension.ANTI_AI.value}:"))
        and f.quote
    ]
    counts: dict[str, int] = {}
    for f in voice:
        counts[f.node_id] = counts.get(f.node_id, 0) + 1
    return [f for f in voice if counts[f.node_id] >= HUMANIZE_MIN]


def _excess(finding: Finding) -> bool:
    """A memo finding about a sentence that must not be there (a revealed card, a broken do-not item): Shenbi's
    spot-fix and Huohuo's span patch remove it; a missing change still needs the scene rewritten."""
    return any(marker in finding.code.lower() for marker in _EXCESS_MARKERS)


def _allowed_names(story: _Story) -> set[str]:
    """Bible names plus every participant the chapter plans name (minor and collective characters)."""
    return set(story.names.values()) | {n for p in story.plans for s in p.scenes for n in s.characters}


def _weight(findings: Sequence[Finding]) -> tuple[int, int, int]:
    """Shenbi's best-version order: fewer integrity, then structural, then narrative-critical findings."""
    return (
        sum(f.severity is Severity.HARD_INTEGRITY for f in findings),
        sum(f.severity is Severity.HARD_STRUCTURAL for f in findings),
        sum(f.severity is Severity.NARRATIVE_CRITICAL for f in findings),
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


def render_markdown(*, title: str, blurb: str, chapters: Sequence[Sequence[str]], first_chapter: int = 1) -> str:
    """The exported manuscript: deterministic from the approved scene texts and the chosen title and blurb, each scene
    laid out in natural paragraphs (its words unchanged); a book part numbers its chapters across the book."""
    parts = [f"# {title}", "", f"> {blurb}", ""]
    for number, scenes in enumerate(chapters, start=first_chapter):
        laid = [natural_paragraphs(scene) for scene in scenes]
        parts.extend([f"## Chương {number}", "", "\n\n* * *\n\n".join(laid), ""])
    return "\n".join(parts).rstrip() + "\n"


def part_length_findings(chapters: Sequence[Sequence[str]], target: int) -> tuple[Finding, ...]:
    """A book part's length against its own target: outside the hard spread is structural, outside the target
    spread stylistic."""
    total = syllables_of(chapters)
    for spread, severity in ((PART_HARD_SPREAD, Severity.HARD_STRUCTURAL), (PART_TARGET_SPREAD, Severity.STYLISTIC)):
        low, high = round(target * (1 - spread)), round(target * (1 + spread))
        if not low <= total <= high:
            return (Finding("STORY_LENGTH", severity, "manuscript", f"{total} syllables outside {low}-{high}"),)
    return ()


def syllables_of(chapters: Sequence[Sequence[str]]) -> int:
    return sum(count_syllables(s) for scenes in chapters for s in scenes)

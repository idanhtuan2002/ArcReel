"""Human actions on story runs: brief, start after Gate A, touchpoint 2, the run lifecycle, export and hand-off.

Every action that changes a run is a Human action by a principal holding the project's Showrunner grant (the
principal class that may Approve); reads need only the authenticated user. A run is one ``story_authoring_run``
task whose resource id is the run id; the run id derives from the Gate A decision, so starting the same
greenlit brief twice returns the same run.

Lifecycle (amendment Change C §8):

- ``RUNNING``, ``BLOCKED_*``, ``MODEL_UNAVAILABLE``, ``READY_FOR_APPROVAL``: revise, retry (blocked), discard.
- ``APPROVING``: nothing.
- ``PARTIALLY_COMMITTED``, ``COMMIT_BLOCKED``: resume, revise (successor manifest), abort.
- ``COMMITTED``: export, send to video, withdraw.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from lib.custom_provider import is_custom_provider, parse_provider_id
from lib.db.models.task import Task
from lib.db.repositories.custom_provider_repo import CustomProviderRepository
from lib.db.repositories.gates import GreenlightRepository
from lib.db.repositories.task_repo import STORY_RUN_TASK_TYPE, TaskRepository
from lib.episode_ledger import discover_sources
from lib.source_preview import preview_sources
from lib.text_backends.ollama import OllamaChatClient
from r2.host_hardening.paid_routes import PaidRouteUnqualifiedError
from r2.narrative_lifecycle.errors import NarrativeDecisionAuthorizationError
from server.story_authoring import book as books
from server.story_authoring.artifacts import BlobStoreError, StoryBlobStore
from server.story_authoring.audits import CONTENT_SAFETY_SETTING, DEFAULT_CONTENT_SAFETY, SAFETY_LEVELS, SafetyLevel
from server.story_authoring.authority import GrantNarrativeShowrunnerAuthority
from server.story_authoring.cloud import (
    CLOUD_ADAPTERS,
    OPENAI_ENDPOINT,
    OPENAI_MAX_INPUT_BOUND,
    CloudStoryGateway,
    story_cloud_client,
)
from server.story_authoring.commit import CANON_BASE_MOVED, ManuscriptCommitter, load_offered_manifest
from server.story_authoring.contracts import (
    OLLAMA_CHAT_ENDPOINT,
    AttemptKind,
    StoryLimits,
    StoryModelSelection,
    StoryScope,
)
from server.story_authoring.driver import (
    CHAPTERS,
    StoryBrief,
    StoryPrior,
    run_call_bound,
    story_bible_input,
    variant_call_bound,
)
from server.story_authoring.executor import RouteUnavailable, default_ollama_client, resolve_route_credential
from server.story_authoring.generation import AttemptSink, AuthoringTextGateway
from server.story_authoring.handoff import OnConflict, SourceUpload, send_to_video, upload_in_flight
from server.story_authoring.idea_draw import DRAW_ATTEMPTS, DRAW_MAX_OUTPUT_TOKENS, DrawnProfile, draw_profile
from server.story_authoring.idea_profile import ProfileSeed
from server.story_authoring.narrative import StoryIdentity
from server.story_authoring.pipeline import intent_targets, node_kind
from server.story_authoring.prompts.prior import prior_calls
from server.story_authoring.prompts.schemas import StorySeed, StyleBibleOut
from server.story_authoring.routes import max_prices, resolve_cloud_route, story_routes, validate_cloud_brief
from server.story_authoring.runtime import (
    AttemptState,
    HandoffRecord,
    RunPhase,
    RunState,
    RunStateStore,
    add_intent,
    new_run_state,
    reopen_unconverged,
    set_phase,
)
from server.story_authoring.variant_profiles import profile_instruction

type Factory = async_sessionmaker[AsyncSession]

RUN_CALLS = run_call_bound()
SECONDS_PER_CALL = 120
PRIOR_MARGIN_CALLS = 13
DEFAULT_LIMITS = StoryLimits(
    generate_calls_max=RUN_CALLS,
    count_calls_max=RUN_CALLS,
    input_tokens_max=RUN_CALLS * 24576,
    output_tokens_max=RUN_CALLS * 4096,
    wall_clock_max_seconds=RUN_CALLS * SECONDS_PER_CALL,
)
BLOCKED_PHASES = frozenset(
    {
        RunPhase.BLOCKED_BUDGET,
        RunPhase.BLOCKED_QUALITY,
        RunPhase.BLOCKED_BINDING_MISMATCH,
        RunPhase.BLOCKED_PROPAGATION,
        RunPhase.MODEL_UNAVAILABLE,
    }
)
REVISABLE_PHASES = frozenset({RunPhase.RUNNING, RunPhase.READY_FOR_APPROVAL, RunPhase.COMMIT_BLOCKED, *BLOCKED_PHASES})
DISCARDABLE_PHASES = frozenset(
    {RunPhase.RUNNING, RunPhase.AWAITING_GATE_A, RunPhase.READY_FOR_APPROVAL, RunPhase.RECOVERY_INCONSISTENT}
    | BLOCKED_PHASES
)
PLANNING_TARGETS = frozenset({"seed", "story_bible", "style_bible", "outline", "packaging"})


class StoryActionRefused(Exception):
    """A request the run's state or the Human's evidence does not allow; ``code`` is stable for the API."""

    def __init__(self, code: str, detail: str, *, status: int = 409) -> None:
        self.code = code
        self.detail = detail
        self.status = status
        super().__init__(f"{code}: {detail}")


@dataclass(frozen=True)
class BookProgress:
    spec: books.BookSpec
    parts_done: int
    state_digest: str


@dataclass(frozen=True)
class StoryRunRef:
    run_id: str
    task_id: str
    brief: StoryBrief


def is_continuation(brief: StoryBrief) -> bool:
    """A continuation's manuscript is handed to video after the parts already in the project (ADR-0115), as is
    every part of a book after the first (ADR-0116)."""
    if brief.book is not None:
        return brief.book.part > 1
    return brief.prior is not None and brief.prior.mode == "continuation"


def rebasable(state: RunState) -> bool:
    """A run blocked before any commit step because another run took the project's MAIN Canon first: a retry
    rebases it on that branch (its scenes are written again on the new Canon) and offers it again."""
    return (
        state.phase is RunPhase.COMMIT_BLOCKED
        and state.commit is not None
        and not state.commit.completed_steps
        and CANON_BASE_MOVED in (state.block_reason or "")
    )


def book_limits(limits: StoryLimits, part: books.BookPart) -> StoryLimits:
    """A book part's limits: the call bound of its chapter count, tokens and wall clock scaled from it."""
    calls = run_call_bound(part.chapters, book=part)
    return limits.model_copy(
        update={
            "chapters": part.chapters,
            "generate_calls_max": calls,
            "count_calls_max": calls,
            "input_tokens_max": calls * limits.max_input_tokens,
            "output_tokens_max": calls * limits.max_output_tokens,
            "wall_clock_max_seconds": calls * SECONDS_PER_CALL,
        }
    )


def brief_idea(idea: str | None, variant_profile: str | None) -> str:
    """The idea a brief carries: the author's text, a named variant profile's instruction, or both."""
    try:
        instruction = profile_instruction(variant_profile) if variant_profile else None
    except KeyError:
        raise StoryActionRefused(
            "VARIANT_PROFILE_UNKNOWN", f"no variant profile {variant_profile!r}", status=422
        ) from None
    parts = [part for part in (instruction, idea) if part]
    if not parts:
        raise StoryActionRefused("IDEA_REQUIRED", "a brief needs an idea or a variant profile", status=422)
    return "\n\n".join(parts)


def run_id_for(gate_a_decision_id: str) -> str:
    return "story-" + hashlib.sha256(gate_a_decision_id.encode("utf-8")).hexdigest()[:24]


class StoryAuthoringService:
    def __init__(
        self,
        *,
        session_factory: Factory,
        authority: GrantNarrativeShowrunnerAuthority,
        project_dir_for: Callable[[str], Path],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._factory = session_factory
        self._authority = authority
        self._project_dir_for = project_dir_for
        self._clock = clock

    # --- brief and start ---------------------------------------------------------------------------

    async def draft_brief(
        self,
        *,
        idea: str,
        genre: str,
        provider_id: str,
        model_id: str,
        story_target_syllables: int = 9000,
        judge_provider_id: str | None = None,
        judge_model_id: str | None = None,
        max_cost_minor_units: int = 500,
        project_name: str | None = None,
        prior_mode: Literal["continuation", "variant"] | None = None,
        prior_project: str | None = None,
        prior_origin: str = "instruction",
        book: books.BookSpec | None = None,
        user_id: str | None = None,
    ) -> StoryBrief:
        """The brief with its frozen routes; its digest is what the Human greenlights at Gate A. A judge route is
        optional; without one the writer's route also reviews.

        With ``prior_mode`` the run reads a story that already exists (ADR-0115): a continuation reads
        ``project_name``'s own sources and writes the next part; a variant reads ``prior_project``'s sources and
        writes another version of that story into ``project_name``. ``idea`` is then the author's direction or the
        variant instruction. The prior text is stored in ``project_name``'s blob store and named in the brief."""
        if (judge_provider_id is None) != (judge_model_id is None):
            raise StoryActionRefused("ROUTE_INCOMPLETE", "a judge route needs both a provider and a model", status=422)
        selection = await self._selection(provider_id, model_id)
        judge = (
            await self._selection(judge_provider_id, judge_model_id) if judge_provider_id and judge_model_id else None
        )
        profiles = []
        for route in (selection, judge):
            if route is not None and route.endpoint != OLLAMA_CHAT_ENDPOINT:
                resolved = await resolve_cloud_route(self._factory, route.provider_id, route.model_id)
                if resolved.selection != route:
                    raise StoryActionRefused("ROUTE_CHANGED", "cloud route changed while preparing the brief")
                if resolved.profile not in profiles:
                    profiles.append(resolved.profile)
        limits = DEFAULT_LIMITS
        if profiles:
            if type(max_cost_minor_units) is not int or not 1 <= max_cost_minor_units <= 10_000:
                raise StoryActionRefused(
                    "CLOUD_BUDGET_INVALID", "cloud USD cap must be between 1 and 10000 cents", status=422
                )
            bounded = {}
            if any(profile.adapter_version == CLOUD_ADAPTERS[OPENAI_ENDPOINT] for profile in profiles):
                # OpenAI-compatible input is bounded by bytes, not counted in tokens (cloud.OPENAI_MAX_INPUT_BOUND).
                bounded = {
                    "max_input_tokens": OPENAI_MAX_INPUT_BOUND,
                    "server_context_tokens": OPENAI_MAX_INPUT_BOUND + DEFAULT_LIMITS.max_output_tokens,
                }
            limits = StoryLimits.model_validate(
                {
                    **DEFAULT_LIMITS.model_dump(),
                    **bounded,
                    "currency": "USD",
                    "max_cost_minor_units": max_cost_minor_units,
                    "cloud_prices": max_prices(tuple(profiles)),
                }
            )
        part: books.BookPart | None = None
        if book is not None:
            if prior_mode is not None:
                raise StoryActionRefused("BOOK_WITH_PRIOR", "a new book starts from an idea", status=422)
            part = books.BookPart(spec=book)
        elif prior_mode == "continuation" and project_name is not None:
            # ADR-0116: a continuation of a book with parts left writes its next part from the book state.
            progress = await self.book_progress(project_name, user_id=user_id)
            if progress is not None and progress.parts_done < len(progress.spec.parts()):
                part = books.BookPart(
                    spec=progress.spec, part=progress.parts_done + 1, state_digest=progress.state_digest
                )
                prior_mode = None
        prior = None
        if prior_mode is not None:
            if (
                project_name is None
                or (prior_mode == "variant") != (prior_project is not None)
                or prior_project == project_name
            ):
                raise StoryActionRefused(
                    "PRIOR_SOURCE_INVALID", "a continuation reads its own project, a variant another one", status=422
                )
            source_project = prior_project if prior_mode == "variant" else project_name
            assert source_project is not None
            docs = discover_sources(self._project_dir_for(source_project))
            text = "\n\n".join(doc.text.strip() for doc in docs if doc.text.strip())
            if not text:
                raise StoryActionRefused("PRIOR_STORY_MISSING", "the source project has no story text", status=409)
            digest = StoryBlobStore(self._project_dir_for(project_name)).put(text.encode("utf-8"))
            prior = StoryPrior(
                mode=prior_mode,
                text_digest=digest,
                part=len(docs) + 1 if prior_mode == "continuation" else 2,
                origin=prior_origin,
            )
            # Reading the prior text (never less than the 13 calls the earlier fixed margin held), and for a variant
            # its review and replan (ADR-0117).
            extra_calls = max(prior_calls(text, mode=prior_mode), PRIOR_MARGIN_CALLS) * 3
            if prior_mode == "variant":
                extra_calls += variant_call_bound()
            limits = limits.model_copy(
                update={
                    "generate_calls_max": limits.generate_calls_max + extra_calls,
                    "count_calls_max": limits.count_calls_max + extra_calls,
                    "input_tokens_max": limits.input_tokens_max + extra_calls * limits.max_input_tokens,
                    "output_tokens_max": limits.output_tokens_max + extra_calls * limits.max_output_tokens,
                    "wall_clock_max_seconds": limits.wall_clock_max_seconds + extra_calls * SECONDS_PER_CALL,
                }
            )
        if part is not None:
            limits = book_limits(limits, part)
        safety = self.content_safety(project_name) if project_name is not None else DEFAULT_CONTENT_SAFETY
        return StoryBrief(
            content_safety=safety,
            idea=idea,
            genre=genre,
            book=part,
            story_target_syllables=story_target_syllables,
            selection=selection,
            judge_selection=judge if judge != selection else None,
            limits=limits,
            cloud_profiles=tuple(profiles),
            prior=prior,
        )

    async def draw_cost_bound(self, *, provider_id: str, model_id: str) -> int:
        """What drawing an idea may cost on a route, in minor units: nothing on a local route."""
        selection = await self._selection(provider_id, model_id)
        if selection.endpoint == OLLAMA_CHAT_ENDPOINT:
            return 0
        try:
            prices = (await resolve_cloud_route(self._factory, provider_id, model_id)).profile.prices
        except (ValueError, PaidRouteUnqualifiedError):
            raise StoryActionRefused("ROUTE_NOT_QUALIFIED", "cloud story route is unavailable or unqualified") from None
        return DRAW_ATTEMPTS * prices.minor_units(DEFAULT_LIMITS.max_input_tokens, DRAW_MAX_OUTPUT_TOKENS)

    async def draw_profile(
        self,
        *,
        provider_id: str,
        model_id: str,
        max_cost_minor_units: int,
        scope: StoryScope,
        draw_key: str,
        seed: ProfileSeed,
        avoid: Sequence[str],
        genre_pack: str | None = None,
        book_chapters: int | None = None,
        client_for: Callable[[str, str | None], OllamaChatClient] | None = None,
    ) -> DrawnProfile:
        """ADR-0125: draw a run's idea and settings on its writer route, at the project's content safety level."""
        selection = await self._selection(provider_id, model_id)
        try:
            key = await resolve_route_credential(self._factory, selection)
        except RouteUnavailable:
            raise StoryActionRefused("MODEL_UNAVAILABLE", "the writer route is unavailable") from None
        limits = DEFAULT_LIMITS
        cloud = None
        if selection.endpoint != OLLAMA_CHAT_ENDPOINT:
            try:
                resolved = await resolve_cloud_route(self._factory, provider_id, model_id)
            except (ValueError, PaidRouteUnqualifiedError):
                raise StoryActionRefused("ROUTE_NOT_QUALIFIED", "cloud story route is unavailable") from None
            if resolved.selection != selection or not key:
                raise StoryActionRefused("ROUTE_CHANGED", "cloud route changed while drawing the idea")
            limits = StoryLimits.model_validate(
                {
                    **DEFAULT_LIMITS.model_dump(),
                    "currency": "USD",
                    "max_cost_minor_units": max(1, min(10_000, max_cost_minor_units)),
                    "cloud_prices": resolved.profile.prices,
                }
            )
            cloud = story_cloud_client(selection, api_key=key)

        async def revalidate() -> None:
            if (await resolve_cloud_route(self._factory, provider_id, model_id)).selection != selection:
                raise ValueError("cloud route changed")

        async def gateway_for(sink: AttemptSink) -> AuthoringTextGateway:
            if cloud is not None:
                return CloudStoryGateway(
                    selection=selection, limits=limits, client=cloud, sink=sink, revalidate=revalidate
                )
            make = client_for or default_ollama_client
            return AuthoringTextGateway(
                selection=selection, limits=limits, client=make(selection.base_url, key), sink=sink
            )

        try:
            return await draw_profile(
                gateway_for=gateway_for,
                selection=selection,
                limits=limits,
                scope=scope,
                draw_key=draw_key,
                seed=seed,
                avoid=avoid,
                safety=self.content_safety(scope.project_name),
                genre_pack=genre_pack,
                book_chapters=book_chapters,
            )
        finally:
            if cloud is not None:
                await cloud.close()

    def content_safety(self, project_name: str) -> SafetyLevel:
        """The project's content safety level (ADR-0121), the lowest (``off``) when unset; ``standard`` when the project
        cannot be read. Sexual content involving minors stays blocked at every level."""
        try:
            project = json.loads((self._project_dir_for(project_name) / "project.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return "standard"
        level = project.get(CONTENT_SAFETY_SETTING) if isinstance(project, dict) else None
        return level if level in SAFETY_LEVELS else DEFAULT_CONTENT_SAFETY

    def source_preview(self, project_name: str) -> list[dict[str, Any]]:
        """The project's story sources as a run would read them: chapters found, size, warnings (ADR-0118)."""
        return [asdict(p) for p in preview_sources(discover_sources(self._project_dir_for(project_name)))]

    async def book_progress(self, project_name: str, *, user_id: str | None = None) -> BookProgress | None:
        """The project's book: the latest part committed and handed to video, read from its quality record;
        ``user_id`` limits it to that user's runs."""
        query = select(Task).where(Task.task_type == STORY_RUN_TASK_TYPE, Task.project_name == project_name)
        if user_id is not None:
            query = query.where(Task.user_id == user_id)
        async with self._factory() as session:
            tasks = (await session.execute(query)).scalars()
            found = [(t.task_id, json.loads(t.payload_json or "{}")) for t in tasks]
        blobs = self._blobs(project_name)
        best: BookProgress | None = None
        for task_id, payload in found:
            brief = StoryBrief.model_validate(payload["brief"])
            if brief.book is None:
                continue
            state = await RunStateStore(self._factory, task_id=task_id).load()
            if state.phase is not RunPhase.COMMITTED or state.handoff is None or not state.handoff.done:
                continue
            manifest = load_offered_manifest(blobs, state)
            if manifest.quality_record_digest is None:
                continue
            record = json.loads(blobs.read_exact(manifest.quality_record_digest))
            digest = record.get("book_state")
            if digest is None or (best is not None and brief.book.part <= best.parts_done):
                continue
            best = BookProgress(spec=brief.book.spec, parts_done=brief.book.part, state_digest=digest)
        return best

    async def list_routes(self) -> list[dict[str, Any]]:
        return await story_routes(self._factory)

    async def _custom_endpoint(self, provider_id: str, model_id: str) -> str | None:
        async with self._factory() as session:
            repo = CustomProviderRepository(session)
            provider = await repo.get_provider(parse_provider_id(provider_id))
            model = await repo.get_model_by_ids(provider.id, model_id) if provider is not None else None
        return model.endpoint if model is not None else None

    async def _selection(self, provider_id: str, model_id: str) -> StoryModelSelection:
        if not is_custom_provider(provider_id) or await self._custom_endpoint(provider_id, model_id) in CLOUD_ADAPTERS:
            try:
                return (await resolve_cloud_route(self._factory, provider_id, model_id)).selection
            except (ValueError, PaidRouteUnqualifiedError):
                raise StoryActionRefused(
                    "ROUTE_NOT_QUALIFIED", "cloud story route is unavailable or unqualified", status=422
                ) from None
        async with self._factory() as session:
            repo = CustomProviderRepository(session)
            provider = await repo.get_provider(parse_provider_id(provider_id))
            model = await repo.get_model_by_ids(provider.id, model_id) if provider is not None else None
        if provider is None or model is None or not model.is_enabled:
            raise StoryActionRefused("ROUTE_NOT_FOUND", f"{provider_id}/{model_id} is not configured", status=422)
        if model.endpoint != OLLAMA_CHAT_ENDPOINT:
            raise StoryActionRefused(
                "ROUTE_NOT_QUALIFIED", f"story authoring needs the {OLLAMA_CHAT_ENDPOINT} endpoint", status=422
            )
        return StoryModelSelection.create(
            provider_id=provider_id,
            endpoint=model.endpoint,
            base_url=provider.base_url,
            model_id=model_id,
            has_credential=bool(provider.api_key),
        )

    async def start(
        self, *, user_id: str, project_name: str, principal: str, brief: StoryBrief, gate_a_decision_id: str
    ) -> StoryRunRef:
        await self._require_grant(principal, user_id=user_id, project_name=project_name)
        return await self.start_greenlit(
            user_id=user_id, project_name=project_name, brief=brief, gate_a_decision_id=gate_a_decision_id
        )

    async def start_greenlit(
        self,
        *,
        user_id: str,
        project_name: str,
        brief: StoryBrief,
        gate_a_decision_id: str,
        command: tuple[str, str] | None = None,
    ) -> StoryRunRef:
        """Start once the caller's own authority is proven; the Gate A, route and replay checks are the same for
        every actor. ``command`` (actor scope, command id) records the task under the caller's command, so a worker
        can check the caller's authority again before the story runs."""
        draft = brief.model_copy(update={"gate_a_decision_id": None})
        await self._require_greenlight(user_id, project_name, draft.digest(), gate_a_decision_id)
        try:
            await validate_cloud_brief(self._factory, draft)
        except (ValueError, PaidRouteUnqualifiedError):
            raise StoryActionRefused("ROUTE_CHANGED", "story route or approved cloud profile changed") from None
        run_id = run_id_for(gate_a_decision_id)
        existing = await self._find(user_id, project_name, run_id)
        if existing is not None:
            return existing
        started = draft.model_copy(update={"gate_a_decision_id": gate_a_decision_id})
        async with self._factory() as session:
            task = await TaskRepository(session).enqueue(
                project_name=project_name,
                task_type=STORY_RUN_TASK_TYPE,
                media_type="text",
                resource_id=run_id,
                payload={"brief": started.model_dump(mode="json")},
                user_id=user_id,
                actor_scope=command[0] if command is not None else None,
                command_id=command[1] if command is not None else None,
                command_digest=started.digest() if command is not None else None,
            )
        store = RunStateStore(self._factory, task_id=task["task_id"])
        await store.initialize(new_run_state(run_id=run_id, limits=started.limits, now=self._clock()))
        return StoryRunRef(run_id=run_id, task_id=task["task_id"], brief=started)

    async def _require_greenlight(self, user_id: str, project_name: str, digest: str, decision_id: str) -> None:
        async with self._factory() as session:
            history = await GreenlightRepository(session).list_for_project(user_id=user_id, project_name=project_name)
        decision = next((d for d in history if d.decision_id == decision_id), None)
        if decision is None or decision.action != "GREENLIGHT":
            raise StoryActionRefused("GATE_A_MISSING", "no Gate A greenlight with this decision id")
        if decision.source_digest != digest:
            raise StoryActionRefused("GATE_A_DIGEST_MISMATCH", "the greenlight names another brief digest")
        if any(d.source_digest == digest and d.sequence > decision.sequence for d in history):
            raise StoryActionRefused("GATE_A_SUPERSEDED", "a later Gate A decision exists for this brief")

    # --- reads -------------------------------------------------------------------------------------

    async def get(self, *, user_id: str, project_name: str, run_id: str) -> tuple[StoryRunRef, RunState]:
        ref = await self._require(user_id, project_name, run_id)
        return ref, await RunStateStore(self._factory, task_id=ref.task_id).load()

    async def drafts(self, *, user_id: str, project_name: str, run_id: str) -> dict[str, Any]:
        """What a run has written so far, readable while it works: each chapter's plan and the scenes drafted, whether
        the chapter's review has sealed it, and the nodes a model is generating right now. Drafts of an unsealed chapter
        may still be repaired or rewritten; a scene being generated has no text until its call returns."""
        ref, state = await self.get(user_id=user_id, project_name=project_name, run_id=run_id)
        blobs = self._blobs(project_name)

        def head(node_id: str) -> Any:
            revision = state.revisions[state.nodes[node_id].head_revision_id or ""]
            return json.loads(blobs.read_exact(revision.digest))

        first = ref.brief.book.first_chapter if ref.brief.book is not None else 1
        chapters: dict[int, dict[str, Any]] = {}

        def chapter(number: int) -> dict[str, Any]:
            return chapters.setdefault(
                number,
                {"chapter": first + number - 1, "goal": None, "planned": 0, "reviewed": False, "scenes": []},
            )

        title = None
        for node_id, node in state.nodes.items():
            if node.head_revision_id is None or node.head_revision_id not in state.revisions:
                continue
            kind = node_kind(node_id)
            try:
                if kind == "seed":
                    title = head(node_id).get("working_title")
                elif kind == "chapter_plan":
                    plan = head(node_id)
                    entry = chapter(int(node_id.split("[", 1)[1].rstrip("]")))
                    entry["goal"] = plan.get("chapter_goal")
                    entry["planned"] = len(plan.get("scenes") or [])
                elif kind == "scene_draft":
                    c, s = (int(part) for part in node_id.split("[", 1)[1].rstrip("]").split(","))
                    chapter(c)["scenes"].append({"scene": s, "text": head(node_id).get("prose", "")})
                elif kind == "chapter_review":
                    chapter(int(node_id.split("[", 1)[1].rstrip("]")))["reviewed"] = True
            except (BlobStoreError, ValueError, KeyError):
                continue  # a head whose blob is missing is shown as not written yet
        for entry in chapters.values():
            entry["scenes"].sort(key=lambda item: item["scene"])
        working = sorted(
            {
                attempt.step_id.split("@", 1)[0]
                for attempt in state.attempts
                if attempt.kind is AttemptKind.GENERATE
                and attempt.state in (AttemptState.RESERVED, AttemptState.DISPATCHED)
            }
        )
        return {
            "run_id": ref.run_id,
            "phase": state.phase.value,
            "title": title,
            "chapters": [chapters[c] for c in sorted(chapters)],
            "working": working,
        }

    async def list_runs(self, *, user_id: str, project_name: str) -> list[dict[str, Any]]:
        """The user's runs in a project, newest first, with what a picker shows."""
        async with self._factory() as session:
            tasks = (
                await session.execute(
                    select(Task)
                    .where(
                        Task.task_type == STORY_RUN_TASK_TYPE,
                        Task.project_name == project_name,
                        Task.user_id == user_id,
                    )
                    .order_by(Task.queued_at.desc())
                )
            ).scalars()
            found = [(t.resource_id, t.task_id, t.queued_at, json.loads(t.payload_json or "{}")) for t in tasks]
        runs = []
        for run_id, task_id, queued_at, payload in found:
            state = await RunStateStore(self._factory, task_id=task_id).load()
            brief = StoryBrief.model_validate(payload["brief"])
            runs.append(
                {
                    "run_id": run_id,
                    "phase": state.phase.value,
                    "idea": brief.idea,
                    "genre": brief.genre,
                    "started_at": queued_at.isoformat(),
                }
            )
        return runs

    def offered(self, project_name: str, state: RunState) -> dict[str, Any] | None:
        """The offered manifest with what touchpoint 2 shows: scenes, findings, exceptions and packaging."""
        if state.commit is None:
            return None
        blobs = self._blobs(project_name)
        manifest = load_offered_manifest(blobs, state)
        quality = (
            json.loads(blobs.read_exact(manifest.quality_record_digest))
            if manifest.quality_record_digest is not None
            else {"findings": [], "packaging": None}
        )
        return {
            "manifest_digest": state.commit.offered_manifest_digest,
            "export_digest": manifest.export_digest,
            "scenes": [
                {"node_id": s.node_id, "chapter": s.chapter, "scene": s.scene, "text": s.revision.normalized_content}
                for s in manifest.scenes
            ],
            "findings": quality["findings"],
            "packaging": quality["packaging"],
            "exceptions_offered": list(manifest.exceptions_offered),
            "completed_steps": list(state.commit.completed_steps),
            "blocked_step": state.commit.blocked_step,
        }

    async def export(self, *, user_id: str, project_name: str, run_id: str) -> bytes:
        _, state = await self.get(user_id=user_id, project_name=project_name, run_id=run_id)
        if state.phase is not RunPhase.COMMITTED or state.commit is None:
            raise StoryActionRefused("NOT_COMMITTED", f"run is {state.phase.value}")
        blobs = self._blobs(project_name)
        return blobs.read_exact(load_offered_manifest(blobs, state).export_digest)

    # --- touchpoint 2 and the commit sequence ------------------------------------------------------

    async def approve(
        self,
        *,
        user_id: str,
        project_name: str,
        run_id: str,
        principal: str,
        manifest_digest_seen: str,
        accepted_exceptions: list[str],
    ) -> RunState:
        committer = await self._committer(user_id, project_name, run_id)
        return await committer.approve(
            principal=principal, manifest_digest_seen=manifest_digest_seen, accepted_exceptions=accepted_exceptions
        )

    async def resume(self, *, user_id: str, project_name: str, run_id: str, principal: str) -> RunState:
        return await (await self._committer(user_id, project_name, run_id)).resume(principal=principal)

    async def abort(self, *, user_id: str, project_name: str, run_id: str, principal: str) -> RunState:
        return await (await self._committer(user_id, project_name, run_id)).abort(principal=principal)

    async def committer(self, *, user_id: str, project_name: str, run_id: str) -> ManuscriptCommitter:
        """The run's commit owner; each of its actions proves its own actor's authority."""
        return await self._committer(user_id, project_name, run_id)

    async def _committer(self, user_id: str, project_name: str, run_id: str) -> ManuscriptCommitter:
        ref, state = await self.get(user_id=user_id, project_name=project_name, run_id=run_id)
        store = RunStateStore(self._factory, task_id=ref.task_id)
        blobs = self._blobs(project_name)
        heads = {}
        for node in ("seed", "style_bible"):
            head = state.nodes.get(node)
            if head is None or head.head_revision_id is None:
                raise StoryActionRefused("NOT_READY", "the run has no story bible yet")
            heads[node] = blobs.read_exact(state.revisions[head.head_revision_id].digest)
        bible = story_bible_input(
            StorySeed.model_validate_json(heads["seed"]), StyleBibleOut.model_validate_json(heads["style_bible"])
        )
        return ManuscriptCommitter(
            identity=StoryIdentity(user_id=user_id, project_name=project_name, run_id=run_id),
            bible=bible,
            store=store,
            blobs=blobs,
            session_factory=self._factory,
            authority=self._authority,
            clock=self._clock,
        )

    # --- lifecycle ---------------------------------------------------------------------------------

    async def revise(
        self, *, user_id: str, project_name: str, run_id: str, principal: str, target: str, note: str
    ) -> RunState:
        """Attach a revision note; the run regenerates the target and everything stale after it, then re-offers."""
        if not note.strip():
            raise StoryActionRefused("EMPTY_NOTE", "a revision request needs a note", status=422)
        await self._require_grant(principal, user_id=user_id, project_name=project_name)
        ref, state = await self.get(user_id=user_id, project_name=project_name, run_id=run_id)
        nodes = _intent_nodes(state, target)

        def change(current: RunState) -> tuple[RunState, bool]:
            if current.phase not in REVISABLE_PHASES:
                return current, False
            revised = add_intent(current, node_ids=nodes, note=note.strip())
            return set_phase(revised, RunPhase.RUNNING), True

        return await self._transition(ref, change, "revise", requeue=True)

    async def retry(self, *, user_id: str, project_name: str, run_id: str, principal: str) -> RunState:
        await self._require_grant(principal, user_id=user_id, project_name=project_name)
        ref, _ = await self.get(user_id=user_id, project_name=project_name, run_id=run_id)

        def change(current: RunState) -> tuple[RunState, bool]:
            if current.phase not in BLOCKED_PHASES and not rebasable(current):
                return current, False
            return set_phase(reopen_unconverged(current), RunPhase.RUNNING), True

        return await self._transition(ref, change, "retry", requeue=True)

    async def discard(self, *, user_id: str, project_name: str, run_id: str, principal: str) -> RunState:
        return await self._terminal(user_id, project_name, run_id, principal, DISCARDABLE_PHASES, RunPhase.DISCARDED)

    async def withdraw(self, *, user_id: str, project_name: str, run_id: str, principal: str) -> RunState:
        """Withdraw a committed run; refused while a hand-off upload is running."""
        return await self._terminal(
            user_id,
            project_name,
            run_id,
            principal,
            frozenset({RunPhase.COMMITTED}),
            RunPhase.WITHDRAWN,
            unless=lambda state: upload_in_flight(state, now=self._clock()),
        )

    async def _terminal(
        self,
        user_id: str,
        project_name: str,
        run_id: str,
        principal: str,
        allowed: frozenset[RunPhase],
        phase: RunPhase,
        *,
        unless: Callable[[RunState], bool] = lambda _: False,
    ) -> RunState:
        await self._require_grant(principal, user_id=user_id, project_name=project_name)
        ref, _ = await self.get(user_id=user_id, project_name=project_name, run_id=run_id)

        def change(current: RunState) -> tuple[RunState, bool]:
            if current.phase not in allowed or unless(current):
                return current, False
            return set_phase(current, phase, reason=f"{phase.value.lower()} by {principal}"), True

        return await self._transition(ref, change, phase.value.lower(), requeue=False)

    async def _transition(
        self, ref: StoryRunRef, change: Callable[[RunState], tuple[RunState, bool]], action: str, *, requeue: bool
    ) -> RunState:
        store = RunStateStore(self._factory, task_id=ref.task_id)
        state, allowed = await store.apply(change)
        if not allowed:
            raise StoryActionRefused(
                "ACTION_NOT_ALLOWED", f"{action} is not allowed while the run is {state.phase.value}"
            )
        if requeue:
            async with self._factory() as session:
                await TaskRepository(session).requeue_finished_story_run(ref.task_id)
        return state

    # --- hand-off ----------------------------------------------------------------------------------

    async def send_to_video(
        self,
        *,
        user_id: str,
        project_name: str,
        run_id: str,
        principal: str,
        command_id: str,
        load_project: Callable[[], dict[str, object]],
        upload: SourceUpload,
        on_conflict: OnConflict = "fail",
    ) -> HandoffRecord:
        """Hand the committed manuscript to video; the project is loaded only after the grant and run checks."""
        await self._require_grant(principal, user_id=user_id, project_name=project_name)
        ref = await self._require(user_id, project_name, run_id)
        return await send_to_video(
            store=RunStateStore(self._factory, task_id=ref.task_id),
            blobs=self._blobs(project_name),
            project=load_project(),
            source_dir=self._project_dir_for(project_name) / "source",
            command_id=command_id,
            upload=upload,
            on_conflict=on_conflict,
            clock=self._clock,
            after_existing=is_continuation(ref.brief),
        )

    # --- helpers -----------------------------------------------------------------------------------

    def _blobs(self, project_name: str) -> StoryBlobStore:
        return StoryBlobStore(self._project_dir_for(project_name))

    async def require_source_grant(self, principal: str, *, user_id: str, project_name: str) -> None:
        """A variant copies another project's story into a brief: its reader must be that project's Showrunner."""
        await self._require_grant(principal, user_id=user_id, project_name=project_name)

    async def _require_grant(self, principal: str, *, user_id: str, project_name: str) -> None:
        try:
            await self._authority.require_showrunner(principal, user_id=user_id, project_name=project_name)
        except NarrativeDecisionAuthorizationError as error:
            raise StoryActionRefused("NOT_AUTHORIZED", str(error), status=403) from error

    async def _require(self, user_id: str, project_name: str, run_id: str) -> StoryRunRef:
        ref = await self._find(user_id, project_name, run_id)
        if ref is None:
            raise StoryActionRefused("RUN_NOT_FOUND", f"no story run {run_id}", status=404)
        return ref

    async def _find(self, user_id: str, project_name: str, run_id: str) -> StoryRunRef | None:
        async with self._factory() as session:
            task = (
                await session.execute(
                    select(Task).where(
                        Task.task_type == STORY_RUN_TASK_TYPE,
                        Task.project_name == project_name,
                        Task.user_id == user_id,
                        Task.resource_id == run_id,
                    )
                )
            ).scalar_one_or_none()
        if task is None:
            return None
        payload = json.loads(task.payload_json or "{}")
        return StoryRunRef(run_id=run_id, task_id=task.task_id, brief=StoryBrief.model_validate(payload["brief"]))


def _intent_nodes(state: RunState, target: str) -> tuple[str, ...]:
    """The nodes a revision request lands on; only planning nodes, chapters and existing scenes are targets."""
    scenes = sorted(n for n in state.nodes if node_kind(n) == "scene_draft")
    shape = [sum(1 for n in scenes if n.startswith(f"scene_draft[{c},")) for c in range(1, CHAPTERS + 1)]
    if target in PLANNING_TARGETS or target in scenes:
        return (target,)
    if target.startswith("chapter[") and target.endswith("]") and target[8:-1].isdigit():
        chapter = int(target[8:-1])
        if 1 <= chapter <= CHAPTERS and shape[chapter - 1]:
            return intent_targets(target, shape)
    raise StoryActionRefused("UNKNOWN_TARGET", f"{target!r} is not a revisable part of this story", status=422)

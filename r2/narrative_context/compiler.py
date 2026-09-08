"""Deterministic, visibility-safe narrative context compilation.

The public surface is a single ``compile`` entry point that returns a complete
immutable pack or one stable error — never a partial pack. Filtering strictly
precedes ranking and budgeting: a retrieval score can never recover a segment
rejected by authority, scope, time, or visibility. Prose is never a visibility
input; only descriptor metadata proven against exact authority reads decides a
segment's channel.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime

from r2.contracts import (
    ContextChannel,
    ContextMode,
    DescriptorAuthorityClass,
    DescriptorVisibilityPolicy,
    Fact,
    NarrativeContextPack,
    NarrativeContextRequest,
    NarrativeContextSegment,
    NarrativePlan,
    NarrativeSourceDescriptor,
    SceneContract,
    SelectionTrace,
    SelectionTraceReason,
    SelectionTraceStatus,
    compute_source_content_hash,
    ensure_json_value,
)
from r2.narrative.canon_state import ResolvedCanonView
from r2.narrative.epistemic import EpistemicView, EpistemicViewResolver
from r2.narrative.errors import EpistemicIntegrityError
from r2.narrative.validation import NarrativeInvariantValidator

from .errors import (
    NarrativeContextBudgetError,
    NarrativeContextInputError,
    NarrativeContextValidationError,
    NarrativeSourceMetadataError,
)
from .ports import (
    AcceptedNarrativeReader,
    CanonVersionReader,
    CreativePolicyReader,
    NarrativePlanReader,
    RetrievalSnapshotReader,
    TokenCounter,
)

_MANDATORY_PRIORITY = {
    ContextChannel.AUTHOR_TRUTH: 2,
    ContextChannel.POV_KNOWN: 2,
    ContextChannel.POV_SUSPECTED: 2,
    ContextChannel.POV_FALSE_BELIEF: 2,
    ContextChannel.EXPLICIT_UNKNOWN: 2,
    ContextChannel.AUTHORIAL_INTENT: 1,
    ContextChannel.CREATIVE_POLICY: 3,
}
_OPTIONAL_PRIORITY = {
    ContextChannel.RECENT_ACCEPTED: 5,
    ContextChannel.RETRIEVED_REFERENCE: 6,
    ContextChannel.SUMMARY: 7,
}
_POV_CHANNEL = {
    "known": ContextChannel.POV_KNOWN,
    "suspected": ContextChannel.POV_SUSPECTED,
    "false_beliefs": ContextChannel.POV_FALSE_BELIEF,
    "explicit_unknown": ContextChannel.EXPLICIT_UNKNOWN,
}


def _sha(prefix: str, payload: object) -> str:
    body = json.dumps(
        ensure_json_value(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return prefix + hashlib.sha256(body).hexdigest()


def _covers(descriptor: NarrativeSourceDescriptor, at: datetime) -> bool:
    if descriptor.effective_from is not None and descriptor.effective_from > at:
        return False
    return descriptor.effective_until is None or at < descriptor.effective_until


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _fact_row(fact: Fact) -> str:
    return json.dumps(
        {
            "subject_ref": fact.subject_ref,
            "predicate": fact.predicate,
            "value": ensure_json_value(fact.value),
            "effective_from": _iso(fact.effective_from),
            "effective_until": _iso(fact.effective_until),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _scene_constraint_digest(scene: SceneContract) -> str:
    payload = {
        "forbidden_events": [item.model_dump(mode="json") for item in scene.forbidden_events],
        "forbidden_knowledge": [item.model_dump(mode="json") for item in scene.forbidden_knowledge],
        "required_events": [item.model_dump(mode="json") for item in scene.required_events],
        "required_reveals": [item.model_dump(mode="json") for item in scene.required_reveals],
        "entry_state_constraints": [item.model_dump(mode="json") for item in scene.entry_state_constraints],
        "exit_state_targets": [item.model_dump(mode="json") for item in scene.exit_state_targets],
        "active_threads": list(scene.active_threads),
        "promise_payoff_refs": list(scene.promise_payoff_refs),
        "creative_constraints": list(scene.creative_constraints),
        "participants": list(scene.participants),
        "temporal_window": {
            "effective_from": scene.temporal_window.effective_from.isoformat(),
            "effective_until": scene.temporal_window.effective_until.isoformat(),
        },
    }
    return json.dumps(ensure_json_value(payload), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class NarrativeContextCompiler:
    def __init__(
        self,
        *,
        canon_reader: CanonVersionReader,
        plan_reader: NarrativePlanReader,
        policy_reader: CreativePolicyReader,
        accepted_reader: AcceptedNarrativeReader,
        snapshot_reader: RetrievalSnapshotReader,
        token_counter: TokenCounter,
        validator: NarrativeInvariantValidator | None = None,
    ) -> None:
        self._canon_reader = canon_reader
        self._plan_reader = plan_reader
        self._policy_reader = policy_reader
        self._accepted_reader = accepted_reader
        self._snapshot_reader = snapshot_reader
        self._token_counter = token_counter
        self._validator = validator or NarrativeInvariantValidator()

    async def compile(self, request: NarrativeContextRequest) -> NarrativeContextPack:
        canon = await self._exact_canon(request)
        plan, scene = await self._exact_plan_and_scene(request)
        self._require_basis_equality(request, plan)
        self._run_hard_validation(canon=canon, plan=plan, scene=scene)
        pov_view = await self._pov_view(request, canon)

        mandatory = self._mandatory_segments(request, canon, scene, pov_view)
        mandatory += await self._policy_segments(request)

        optional, traces = await self._optional_segments_and_traces(request, canon)
        recent_optional, recent_traces = await self._recent_accepted_segments_and_traces(request, canon)
        optional += recent_optional
        traces += recent_traces

        used, kept_optional, traces = self._allocate_budget(request, mandatory, optional, traces)
        segments = tuple(mandatory)
        retrieved = tuple(
            seg for seg in kept_optional if seg.channel in (ContextChannel.RETRIEVED_REFERENCE, ContextChannel.SUMMARY)
        )
        recent = tuple(seg for seg in kept_optional if seg.channel is ContextChannel.RECENT_ACCEPTED)

        pack_input = {
            "compiler_version": request.compiler_version,
            "token_counter_version": self._token_counter.version,
            "canon": [request.canon_branch_id, request.canon_version_id],
            "plan": [request.plan_id, request.plan_version],
            "scene": [request.scene_contract_id, request.scene_contract_version],
            "policy": [request.creative_policy_ref, request.creative_policy_version],
            "mode": request.mode.value,
            "pov": request.pov_subject_entity_id,
            "story_time": request.story_time.isoformat(),
            "retrieval_snapshot_ref": request.retrieval_snapshot_ref,
            "recent_accepted_refs": list(request.recent_accepted_refs),
            "token_budget": request.token_budget,
        }
        content_input = {
            "segments": [self._segment_digest(seg) for seg in segments + recent + retrieved],
            "selection_trace": [self._trace_digest(trace) for trace in traces],
        }
        return NarrativeContextPack(
            context_pack_id=_sha("ncp:", pack_input),
            base_canon_version=request.canon_version_id,
            epistemic_view_ref=None if pov_view is None else pov_view.view_hash,
            narrative_plan_refs=(f"{request.plan_id}@{request.plan_version}",),
            creative_policy_ref=request.creative_policy_ref,
            scene_contract_ref=f"{request.scene_contract_id}@{request.scene_contract_version}",
            pov=request.pov_subject_entity_id,
            temporal_context=request.story_time,
            segments=segments,
            recent_accepted_context=recent,
            retrieved_context=retrieved,
            token_budget=request.token_budget,
            tokens_used=used,
            compiler_version=request.compiler_version,
            retrieval_snapshot_ref=request.retrieval_snapshot_ref,
            dependency_refs=(
                request.canon_version_id,
                f"{request.plan_id}@{request.plan_version}",
                request.creative_policy_ref,
            ),
            selection_trace=tuple(traces),
            content_hash=_sha("ncc:", content_input),
        )

    # -- stages ---------------------------------------------------------------

    async def _exact_canon(self, request: NarrativeContextRequest) -> ResolvedCanonView:
        view = await self._canon_reader.get_exact(
            branch_id=request.canon_branch_id,
            canon_version_id=request.canon_version_id,
            project_name=request.project_name,
            user_id=request.user_id,
        )
        if view is None:
            raise NarrativeContextInputError(f"canon version {request.canon_version_id!r} not found in scope")
        if view.canon_version_id != request.canon_version_id or view.branch_id != request.canon_branch_id:
            raise NarrativeContextInputError("Canon reader returned a view for a different exact version")
        return view

    async def _exact_plan_and_scene(self, request: NarrativeContextRequest) -> tuple[NarrativePlan, SceneContract]:
        plan = await self._plan_reader.get_exact_plan(
            plan_id=request.plan_id,
            plan_version=request.plan_version,
            project_name=request.project_name,
            user_id=request.user_id,
        )
        scene = await self._plan_reader.get_exact_scene(
            plan_id=request.plan_id,
            plan_version=request.plan_version,
            scene_contract_id=request.scene_contract_id,
            scene_contract_version=request.scene_contract_version,
            project_name=request.project_name,
            user_id=request.user_id,
        )
        if plan is None or scene is None:
            raise NarrativeContextInputError("exact plan or scene version not found in scope")
        if (plan.plan_id, plan.version) != (request.plan_id, request.plan_version):
            raise NarrativeContextInputError("plan reader returned a different exact plan version")
        if (scene.scene_contract_id, scene.version) != (
            request.scene_contract_id,
            request.scene_contract_version,
        ):
            raise NarrativeContextInputError("plan reader returned a different exact scene version")
        if request.story_time != scene.temporal_window.effective_from:
            raise NarrativeContextInputError("story_time must equal the scene temporal_window.effective_from")
        return plan, scene

    @staticmethod
    def _require_basis_equality(request: NarrativeContextRequest, plan: NarrativePlan) -> None:
        basis = plan.content.canon_basis
        if basis.branch_id != request.canon_branch_id or basis.canon_version_id != request.canon_version_id:
            raise NarrativeContextInputError("plan Canon basis does not equal the requested Canon version")

    def _run_hard_validation(self, *, canon: ResolvedCanonView, plan: NarrativePlan, scene: SceneContract) -> None:
        report = self._validator.validate_scene(canon=canon, plan=plan, scene=scene)
        if not report.ok:
            raise NarrativeContextValidationError([finding.rule_id for finding in report.findings])

    async def _pov_view(self, request: NarrativeContextRequest, canon: ResolvedCanonView) -> EpistemicView | None:
        if request.pov_subject_entity_id is None:
            return None
        try:
            return EpistemicViewResolver().resolve(
                canon=canon, subject_entity_id=request.pov_subject_entity_id, at=request.story_time
            )
        except EpistemicIntegrityError as exc:
            raise NarrativeContextValidationError(str(exc)) from exc

    def _mandatory_segments(
        self,
        request: NarrativeContextRequest,
        canon: ResolvedCanonView,
        scene: SceneContract,
        pov_view: EpistemicView | None,
    ) -> list[NarrativeContextSegment]:
        segments: list[NarrativeContextSegment] = [
            self._segment(
                channel=ContextChannel.AUTHORIAL_INTENT,
                source_ref=f"{request.scene_contract_id}@{request.scene_contract_version}",
                content=scene.purpose,
                priority=_MANDATORY_PRIORITY[ContextChannel.AUTHORIAL_INTENT],
            )
        ]
        segments.append(
            self._segment(
                channel=ContextChannel.AUTHORIAL_INTENT,
                source_ref=f"{request.scene_contract_id}@{request.scene_contract_version}#forbidden",
                content=_scene_constraint_digest(scene),
                priority=_MANDATORY_PRIORITY[ContextChannel.AUTHORIAL_INTENT],
            )
        )
        if request.mode is ContextMode.AUTHOR_DRAFT:
            truth = json.dumps(sorted(_fact_row(fact) for fact in canon.content.facts_by_id.values()))
            segments.append(
                self._segment(
                    channel=ContextChannel.AUTHOR_TRUTH,
                    source_ref=request.canon_version_id,
                    content=truth,
                    priority=_MANDATORY_PRIORITY[ContextChannel.AUTHOR_TRUTH],
                )
            )
        pov = request.pov_subject_entity_id
        if pov_view is not None and pov is not None:
            for bucket_name, channel in _POV_CHANNEL.items():
                if bucket_name == "explicit_unknown" and request.mode is ContextMode.CHARACTER_SIMULATION:
                    # Explicit-unknown content is forbidden in character simulation.
                    continue
                items = getattr(pov_view, bucket_name)
                if not items:
                    continue
                content = json.dumps(sorted(item.proposition.proposition_ref for item in items))
                segments.append(
                    self._segment(
                        channel=channel,
                        source_ref=f"pov:{pov}",
                        content=content,
                        priority=_MANDATORY_PRIORITY[channel],
                        visibility_subjects=(pov,),
                    )
                )
        return segments

    async def _policy_segments(self, request: NarrativeContextRequest) -> list[NarrativeContextSegment]:
        policy = await self._policy_reader.get_exact(
            policy_ref=request.creative_policy_ref,
            policy_version=request.creative_policy_version,
            project_name=request.project_name,
            user_id=request.user_id,
        )
        if policy is None:
            raise NarrativeContextInputError(f"creative policy {request.creative_policy_ref!r} not found in scope")
        return [
            self._segment(
                channel=ContextChannel.CREATIVE_POLICY,
                source_ref=item.source_ref,
                content=item.content,
                priority=_MANDATORY_PRIORITY[ContextChannel.CREATIVE_POLICY],
            )
            for item in policy
        ]

    async def _optional_segments_and_traces(
        self, request: NarrativeContextRequest, canon: ResolvedCanonView
    ) -> tuple[list[tuple[str, NarrativeContextSegment]], list[SelectionTrace]]:
        if request.retrieval_snapshot_ref is None:
            return [], []
        snapshot = await self._snapshot_reader.get_exact(
            snapshot_ref=request.retrieval_snapshot_ref, project_name=request.project_name, user_id=request.user_id
        )
        if snapshot is None:
            raise NarrativeContextInputError("retrieval snapshot not found in scope")
        if snapshot.user_id != request.user_id or snapshot.project_name != request.project_name:
            raise NarrativeContextInputError("retrieval snapshot is out of scope")

        eligible: list[tuple[str, NarrativeContextSegment]] = []
        traces: list[SelectionTrace] = []
        seen: set[tuple[str, str]] = set()
        for candidate in sorted(snapshot.candidates, key=lambda item: item.candidate_id):
            descriptor = candidate.source_descriptor
            reason = self._reject_reason(request, descriptor, candidate.content, canon)
            if reason is not None:
                traces.append(
                    SelectionTrace(
                        candidate_id=candidate.candidate_id,
                        source_ref=descriptor.source_ref,
                        status=SelectionTraceStatus.OMITTED,
                        reason=reason,
                    )
                )
                continue
            content_hash = descriptor.content_hash
            key = (descriptor.source_ref, content_hash)
            if key in seen:
                traces.append(
                    SelectionTrace(
                        candidate_id=candidate.candidate_id,
                        source_ref=descriptor.source_ref,
                        status=SelectionTraceStatus.OMITTED,
                        reason=SelectionTraceReason.DUPLICATE,
                        content_hash=content_hash,
                        token_count=self._token_counter.count(candidate.content),
                    )
                )
                continue
            seen.add(key)
            channel = (
                ContextChannel.SUMMARY
                if descriptor.authority_class is DescriptorAuthorityClass.SUMMARY
                else ContextChannel.RETRIEVED_REFERENCE
            )
            eligible.append(
                (
                    candidate.candidate_id,
                    self._segment(
                        channel=channel,
                        source_ref=descriptor.source_ref,
                        content=candidate.content,
                        priority=_OPTIONAL_PRIORITY[channel],
                        descriptor_ref=descriptor.descriptor_ref,
                        basis_refs=tuple(descriptor.source_basis_refs),
                        effective_from=descriptor.effective_from,
                        effective_until=descriptor.effective_until,
                        visibility_subjects=tuple(descriptor.visibility_subjects),
                    ),
                )
            )
        return eligible, traces

    def _reject_reason(
        self,
        request: NarrativeContextRequest,
        descriptor: NarrativeSourceDescriptor,
        prose: str,
        canon: ResolvedCanonView,
    ) -> SelectionTraceReason | None:
        if descriptor.user_id != request.user_id or descriptor.project_name != request.project_name:
            return SelectionTraceReason.WRONG_SCOPE
        if descriptor.content_hash != compute_source_content_hash(prose):
            return SelectionTraceReason.MISSING_SOURCE_METADATA

        requires_both_bases = descriptor.authority_class in (
            DescriptorAuthorityClass.ACCEPTED_NARRATIVE,
            DescriptorAuthorityClass.SUMMARY,
        )
        subjects = descriptor.visibility_policy is DescriptorVisibilityPolicy.SUBJECTS
        if requires_both_bases or subjects:
            basis = descriptor.canon_basis
            if (
                basis is None
                or basis.branch_id != request.canon_branch_id
                or basis.canon_version_id != request.canon_version_id
            ):
                return SelectionTraceReason.UNRESOLVED_VISIBILITY_BASIS
        if requires_both_bases:
            plan_basis = descriptor.plan_basis
            if (
                plan_basis is None
                or plan_basis.plan_id != request.plan_id
                or plan_basis.plan_version != request.plan_version
            ):
                return SelectionTraceReason.UNRESOLVED_VISIBILITY_BASIS

        if not _covers(descriptor, request.story_time):
            return SelectionTraceReason.OUT_OF_TIME
        return self._visibility_reason(request, descriptor, canon)

    def _visibility_reason(
        self,
        request: NarrativeContextRequest,
        descriptor: NarrativeSourceDescriptor,
        canon: ResolvedCanonView,
    ) -> SelectionTraceReason | None:
        if descriptor.visibility_policy is DescriptorVisibilityPolicy.AUTHOR_ONLY:
            if request.mode is ContextMode.CHARACTER_SIMULATION:
                return SelectionTraceReason.NOT_VISIBLE
            return None

        # SUBJECTS: the descriptor's whole declared proof matrix -- every (subject,
        # proposition) pair -- must be proven by an active KnowledgeState named in
        # visibility_knowledge_state_refs in KNOWN / SUSPECTED / FALSE_BELIEF at the
        # story time. UNKNOWN and absence deny visibility. This is checked in every
        # mode; author draft additionally sees the segment, simulation only if the POV
        # subject is one of the named subjects.
        allowed_ks = set(descriptor.visibility_knowledge_state_refs)
        wanted = set(descriptor.proposition_refs)
        for subject in descriptor.visibility_subjects:
            try:
                view = EpistemicViewResolver().resolve(canon=canon, subject_entity_id=subject, at=request.story_time)
            except EpistemicIntegrityError:
                return SelectionTraceReason.UNRESOLVED_VISIBILITY_BASIS
            proven = {
                item.proposition.proposition_ref
                for bucket in (view.known, view.suspected, view.false_beliefs)
                for item in bucket
                if item.knowledge_state_id in allowed_ks
            }
            if not wanted.issubset(proven):
                return SelectionTraceReason.NOT_VISIBLE

        if request.mode is ContextMode.CHARACTER_SIMULATION:
            pov = request.pov_subject_entity_id
            if pov is None or pov not in descriptor.visibility_subjects:
                return SelectionTraceReason.NOT_VISIBLE
        return None

    async def _recent_accepted_segments_and_traces(
        self, request: NarrativeContextRequest, canon: ResolvedCanonView
    ) -> tuple[list[tuple[str, NarrativeContextSegment]], list[SelectionTrace]]:
        eligible: list[tuple[str, NarrativeContextSegment]] = []
        traces: list[SelectionTrace] = []
        seen: set[tuple[str, str]] = set()
        for ref in request.recent_accepted_refs:
            record = await self._accepted_reader.get_exact(
                accepted_narrative_ref=ref, project_name=request.project_name, user_id=request.user_id
            )
            if record is None:
                raise NarrativeSourceMetadataError(f"recent accepted narrative {ref!r} not found in scope")
            descriptor = record.descriptor
            reason = self._reject_reason(request, descriptor, record.content, canon)
            if reason is not None:
                traces.append(
                    SelectionTrace(
                        candidate_id=ref,
                        source_ref=descriptor.source_ref,
                        status=SelectionTraceStatus.OMITTED,
                        reason=reason,
                    )
                )
                continue
            key = (descriptor.source_ref, descriptor.content_hash)
            if key in seen:
                traces.append(
                    SelectionTrace(
                        candidate_id=ref,
                        source_ref=descriptor.source_ref,
                        status=SelectionTraceStatus.OMITTED,
                        reason=SelectionTraceReason.DUPLICATE,
                        content_hash=descriptor.content_hash,
                        token_count=self._token_counter.count(record.content),
                    )
                )
                continue
            seen.add(key)
            eligible.append(
                (
                    ref,
                    self._segment(
                        channel=ContextChannel.RECENT_ACCEPTED,
                        source_ref=descriptor.source_ref,
                        content=record.content,
                        priority=_OPTIONAL_PRIORITY[ContextChannel.RECENT_ACCEPTED],
                        descriptor_ref=descriptor.descriptor_ref,
                        basis_refs=tuple(descriptor.source_basis_refs),
                        effective_from=descriptor.effective_from,
                        effective_until=descriptor.effective_until,
                        visibility_subjects=tuple(descriptor.visibility_subjects),
                    ),
                )
            )
        return eligible, traces

    def _allocate_budget(
        self,
        request: NarrativeContextRequest,
        mandatory: list[NarrativeContextSegment],
        optional: list[tuple[str, NarrativeContextSegment]],
        traces: list[SelectionTrace],
    ) -> tuple[int, list[NarrativeContextSegment], list[SelectionTrace]]:
        mandatory_used = sum(seg.token_count for seg in mandatory)
        if mandatory_used > request.token_budget:
            raise NarrativeContextBudgetError("mandatory context exceeds the token budget")
        used = mandatory_used
        kept: list[NarrativeContextSegment] = []
        ordered = sorted(optional, key=lambda item: (item[1].priority, item[1].source_ref, item[1].content_hash))
        for candidate_id, seg in ordered:
            if used + seg.token_count <= request.token_budget:
                used += seg.token_count
                kept.append(seg)
                status, reason = SelectionTraceStatus.INCLUDED, SelectionTraceReason.INCLUDED
            else:
                status, reason = SelectionTraceStatus.OMITTED, SelectionTraceReason.BUDGET
            traces.append(
                SelectionTrace(
                    candidate_id=candidate_id,
                    source_ref=seg.source_ref,
                    status=status,
                    reason=reason,
                    content_hash=seg.content_hash,
                    token_count=seg.token_count,
                )
            )
        traces.sort(key=lambda trace: (trace.candidate_id, trace.reason.value))
        return used, kept, traces

    def _segment(
        self,
        *,
        channel: ContextChannel,
        source_ref: str,
        content: str,
        priority: int,
        descriptor_ref: str | None = None,
        basis_refs: tuple[str, ...] = (),
        effective_from: datetime | None = None,
        effective_until: datetime | None = None,
        visibility_subjects: tuple[str, ...] = (),
    ) -> NarrativeContextSegment:
        return NarrativeContextSegment(
            channel=channel,
            source_ref=source_ref,
            descriptor_ref=descriptor_ref,
            basis_refs=basis_refs,
            effective_from=effective_from,
            effective_until=effective_until,
            visibility_subjects=visibility_subjects,
            priority=priority,
            token_count=self._token_counter.count(content),
            content_hash=_sha("ncs:", content),
            content=content,
        )

    @staticmethod
    def _segment_digest(seg: NarrativeContextSegment) -> dict[str, object]:
        return {
            "channel": seg.channel.value,
            "source_ref": seg.source_ref,
            "descriptor_ref": seg.descriptor_ref,
            "basis_refs": list(seg.basis_refs),
            "effective_from": _iso(seg.effective_from),
            "effective_until": _iso(seg.effective_until),
            "visibility_subjects": list(seg.visibility_subjects),
            "content_hash": seg.content_hash,
            "token_count": seg.token_count,
            "priority": seg.priority,
        }

    @staticmethod
    def _trace_digest(trace: SelectionTrace) -> dict[str, object]:
        return {
            "candidate_id": trace.candidate_id,
            "source_ref": trace.source_ref,
            "status": trace.status.value,
            "reason": trace.reason.value,
            "content_hash": trace.content_hash,
            "token_count": trace.token_count,
        }

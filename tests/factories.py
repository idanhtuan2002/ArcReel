"""Test data factories — reduce boilerplate when constructing common objects."""

from __future__ import annotations

import subprocess
import wave
from collections.abc import Callable
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any

from r2.contracts.narrative_lifecycle import (
    CanonMutationEffectKey,
    ChangeSetReviewCommand,
    CompilationAttempt,
    CompilationResult,
    CompilationSelectedChangeSet,
    CompiledCanonDeltaEvidence,
    ConflictResolutionCommand,
    DraftCandidate,
    ExtractionAttempt,
    ExtractionResult,
    NarrativeChangeItem,
    NarrativeChangeSet,
    NarrativeDecisionAuthorization,
    NarrativeRevision,
    NarrativeWorkScope,
    ObservedEffectiveHead,
    RevisionAcceptanceCommand,
    SourceSpan,
)
from r2.contracts.provenance import Provenance
from server.agent_runtime.models import SessionMeta

NARRATIVE_LIFECYCLE_NOW = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)


def make_translator(locale: str = "zh") -> Callable[..., str]:
    """Create a translator function bound to a fixed locale for testing."""
    from lib.i18n import _ as i18n_translate

    def translate(key: str, **kwargs) -> str:
        return i18n_translate(key, locale=locale, **kwargs)

    return translate


def wav_bytes(duration_seconds: float, sample_rate: int = 8000) -> bytes:
    """纯 stdlib 生成 wav 字节（不依赖 ffmpeg），供不要求真实音频编解码的用例使用。"""
    buf = BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00\x00" * int(duration_seconds * sample_rate))
    return buf.getvalue()


def make_test_video(path: Path, *, duration_sec: float = 1.0, fps: int = 30) -> None:
    """使用 ffmpeg 生成极短测试视频（64x64 像素）"""
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=black:size=64x64:duration={duration_sec}:rate={fps}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        capture_output=True,
        check=True,
    )


def make_test_video_with_audio_tail(
    path: Path,
    *,
    video_duration_sec: float = 1.0,
    audio_duration_sec: float = 1.5,
    fps: int = 30,
) -> None:
    """生成音轨/容器尾部比视频轨更长的极短 MP4。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=black:size=64x64:duration={video_duration_sec}:rate={fps}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={audio_duration_sec}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(path),
        ],
        capture_output=True,
        check=True,
    )


def make_session_meta(**overrides) -> SessionMeta:
    """Build a SessionMeta with sensible defaults.

    Any keyword argument overrides the corresponding default field.
    """
    defaults = {
        "id": "session-1",
        "project_name": "demo",
        "title": "demo",
        "status": "running",
        "created_at": datetime(2026, 2, 9, 8, 0, 0, tzinfo=UTC),
        "updated_at": datetime(2026, 2, 9, 8, 0, 0, tzinfo=UTC),
    }
    defaults.update(overrides)
    return SessionMeta(**defaults)


def make_task_params(**overrides) -> dict:
    """Build a dict of parameters suitable for ``GenerationQueue.enqueue_task()``.

    Any keyword argument overrides the corresponding default.
    """
    defaults = {
        "project_name": "demo",
        "task_type": "storyboard",
        "media_type": "image",
        "resource_id": "E1S01",
        "payload": {"prompt": "test"},
        "script_file": "episode_01.json",
        "source": "webui",
    }
    defaults.update(overrides)
    return defaults


def make_sdk_transcript_entry(
    uuid: str, parent: str | None, entry_type: str, session_id: str, text: str
) -> dict[str, Any]:
    """一条 SDK 形态的 transcript 条目，供前缀分叉相关的测试搭建原会话历史。"""
    return {
        "uuid": uuid,
        "parentUuid": parent,
        "sessionId": session_id,
        "type": entry_type,
        "timestamp": "2026-01-01T00:00:00Z",
        "message": {"role": entry_type, "content": text},
    }


def make_transcript_entry(
    msg_type: str = "assistant",
    text: str = "hello",
    *,
    uuid: str = "msg-1",
    tool_use_id: str | None = None,
    tool_name: str | None = None,
    **extra,
) -> dict:
    """Build a single transcript JSONL entry dict.

    ``msg_type`` is one of ``"user"``, ``"assistant"``, ``"result"``.
    """
    if msg_type == "user":
        content = text
    elif msg_type == "result":
        entry: dict = {
            "type": "result",
            "subtype": extra.get("subtype", "success"),
            "is_error": extra.get("is_error", False),
            "uuid": uuid,
        }
        entry.update(extra)
        return entry
    else:
        if tool_use_id:
            content = [{"type": "tool_use", "id": tool_use_id, "name": tool_name or "Tool", "input": {}}]
        else:
            content = [{"type": "text", "text": text}]

    entry = {"type": msg_type, "message": {"content": content}, "uuid": uuid}
    entry.update(extra)
    return entry


def custom_endpoint_definition(**overrides: Any) -> dict[str, Any]:
    """最小可用的声明式调用端点定义：单张首帧、提交 + 轮询、扁平取值，校验零错误零警告。

    用例就地改出反例或补上可选构造；``overrides`` 覆盖顶层键（如换 ``meta`` 造重复血统）。
    """
    definition: dict[str, Any] = {
        "kind": "declarative",
        "schema_version": "1.0.0",
        "meta": {"name": "示例端点", "author": "ArcReel", "version": "0.1.0"},
        "auth": {"headers": {"Authorization": "Bearer {{ api_key }}"}},
        "inputs": {"first_frame": {"source": "start_image", "encoding": "data_uri"}},
        "enum_maps": {"duration": {"5": 5, "10": 10}},
        "submit": {
            "method": "POST",
            "url": "{{ base_url }}/v1/video/create",
            "body": {
                "model": "{{ model }}",
                "prompt": "{{ prompt }}",
                "image": "{{ inputs.first_frame }}",
                "duration": "{{ duration }}",
            },
            "extract": {"task_id": ["$.task_id"], "error": ["$.error.message"]},
        },
        "poll": {
            "method": "GET",
            "url": "{{ base_url }}/v1/video/fetch/{{ task_id }}",
            "extract": {"status": ["$.status"], "video_url": ["$.video_url"], "error": ["$.error"]},
        },
        "status_map": {"pending": "queued", "processing": "running", "completed": "succeeded", "failed": "failed"},
        "capabilities": {"first_frame": True},
    }
    definition.update(overrides)
    return definition


# --------------------------------------------------------------------------- #
# M5C Narrative-lifecycle evidence contracts
#
# The defaults form one coherent candidate -> revision -> attempt -> result chain
# (matching ids and exact bases), so a test can seed the chain with no arguments.
# --------------------------------------------------------------------------- #

_NL_BASES = {
    "base_canon_version_id": "cv-1",
    "plan_version": 2,
    "scene_contract_version": 1,
    "context_pack_id": "ctx-1",
}


def make_narrative_work_scope(**overrides: Any) -> NarrativeWorkScope:
    defaults: dict[str, Any] = {
        "user_id": "u1",
        "project_name": "project-a",
        "plan_id": "plan-1",
        "scene_contract_id": "scene-1",
        "canon_branch_id": "branch-1",
    }
    defaults.update(overrides)
    return NarrativeWorkScope(**defaults)


def make_narrative_provenance(**overrides: Any) -> Provenance:
    defaults: dict[str, Any] = {"created_by": "AGENT", "created_at": NARRATIVE_LIFECYCLE_NOW}
    defaults.update(overrides)
    return Provenance(**defaults)


def make_draft_candidate(*, work_scope: NarrativeWorkScope | None = None, **overrides: Any) -> DraftCandidate:
    defaults: dict[str, Any] = {
        "candidate_id": "cand-1",
        "work_scope": work_scope or make_narrative_work_scope(),
        **_NL_BASES,
        "normalized_content": "prose",
        "content_hash": "pch:abc",
        "writer_kind": "AGENT",
        "writer_version": "w-1",
        "provenance": make_narrative_provenance(),
        "created_at": NARRATIVE_LIFECYCLE_NOW,
        "created_by": "who",
        "semantic_fingerprint": "esf:1",
    }
    defaults.update(overrides)
    return DraftCandidate(**defaults)


def make_narrative_revision(*, work_scope: NarrativeWorkScope | None = None, **overrides: Any) -> NarrativeRevision:
    defaults: dict[str, Any] = {
        "revision_id": "rev-1",
        "work_scope": work_scope or make_narrative_work_scope(),
        "base_candidate_id": "cand-1",
        "predecessor_revision_id": None,
        **_NL_BASES,
        "normalized_content": "prose",
        "content_hash": "pch:abc",
        "review_refs": [],
        "provenance": make_narrative_provenance(),
        "created_at": NARRATIVE_LIFECYCLE_NOW,
        "created_by": "who",
        "semantic_fingerprint": "esf:2",
    }
    defaults.update(overrides)
    return NarrativeRevision(**defaults)


def make_extraction_attempt(*, work_scope: NarrativeWorkScope | None = None, **overrides: Any) -> ExtractionAttempt:
    defaults: dict[str, Any] = {
        "attempt_id": "att-1",
        "generation": 0,
        "work_scope": work_scope or make_narrative_work_scope(),
        "revision_id": "rev-1",
        "revision_acceptance_decision_id": "dec-1",
        "observed_revision_effective_generation": 0,
        **_NL_BASES,
        "extractor_kind": "LOCAL",
        "extractor_version": "x-1",
        "policy_ref": "pol",
        "policy_version": "1",
        "admitted_at": NARRATIVE_LIFECYCLE_NOW,
        "admitted_by": "who",
        "input_fingerprint": "if-1",
    }
    defaults.update(overrides)
    return ExtractionAttempt(**defaults)


def make_extraction_result(**overrides: Any) -> ExtractionResult:
    defaults: dict[str, Any] = {
        "result_id": "res-1",
        "attempt_id": "att-1",
        "generation": 0,
        "outcome": "ABSTAINED",
        "change_set_ids": (),
        "diagnostics": (),
        "provider_receipt": None,
        "completed_at": NARRATIVE_LIFECYCLE_NOW,
        "output_fingerprint": "of-1",
    }
    defaults.update(overrides)
    return ExtractionResult(**defaults)


def make_canon_mutation_effect_key(**overrides: Any) -> CanonMutationEffectKey:
    defaults: dict[str, Any] = {
        "canon_subject_kind": "FACT",
        "subject_ref": "hero",
        "effect_descriptor": "trust",
        "canon_operation_count": 1,
    }
    defaults.update(overrides)
    return CanonMutationEffectKey(**defaults)


def make_narrative_change_set(**overrides: Any) -> NarrativeChangeSet:
    key = overrides.pop("key", None) or make_canon_mutation_effect_key()
    span = overrides.pop("span", None) or SourceSpan(start=0, end=4)
    defaults: dict[str, Any] = {
        "change_set_id": "cs-1",
        "change_set_lineage_id": None,
        "source_revision_id": "rev-1",
        "extraction_attempt_id": "att-1",
        "extraction_generation": 0,
        "base_canon_version_id": "cv-1",
        "source_spans": (span,),
        "semantic_effect_keys": (key,),
        "changes": (NarrativeChangeItem(change_id="ch-1", evidence_span=span, effect_keys=(key,), summary="s"),),
        "confidence": 0.7,
        "extractor_version": "x-1",
        "policy_ref": "pol",
        "policy_version": "1",
        "created_at": NARRATIVE_LIFECYCLE_NOW,
        "output_fingerprint": "of-cs",
    }
    defaults.update(overrides)
    if defaults["change_set_lineage_id"] is None:
        defaults["change_set_lineage_id"] = f"lin-{defaults['change_set_id']}"
    return NarrativeChangeSet(**defaults)


def make_narrative_decision_authorization(**overrides: Any) -> NarrativeDecisionAuthorization:
    defaults: dict[str, Any] = {
        "authorization_ref": "auth-1",
        "user_id": "u1",
        "project_name": "project-a",
        "actor_id": "showrunner-1",
        "authority_role": "HUMAN_SHOWRUNNER",
        "decision_family": "REVISION_ACCEPTANCE",
        "action": "ACCEPT",
        "decision_id": "d-1",
        "stable_subject_fingerprint": "ssf:1",
        "decision_command_fingerprint": "dcf:1",
        "authenticated_at": NARRATIVE_LIFECYCLE_NOW,
        "authenticated_via": "test-fixture",
    }
    defaults.update(overrides)
    return NarrativeDecisionAuthorization(**defaults)


def make_revision_acceptance_command(
    *, work_scope: NarrativeWorkScope | None = None, **overrides: Any
) -> RevisionAcceptanceCommand:
    defaults: dict[str, Any] = {
        "decision_id": "d-1",
        "action": "ACCEPT",
        "work_scope": work_scope or make_narrative_work_scope(),
        "selected_revision_id": "rev-1",
        "expected_latest_decision_id": None,
        "expected_effective_decision_id": None,
        **_NL_BASES,
        "actor_id": "showrunner-1",
    }
    defaults.update(overrides)
    return RevisionAcceptanceCommand(**defaults)


def make_change_set_review_command(
    *, work_scope: NarrativeWorkScope | None = None, **overrides: Any
) -> ChangeSetReviewCommand:
    defaults: dict[str, Any] = {
        "decision_id": "d-2",
        "action": "ACCEPT",
        "work_scope": work_scope or make_narrative_work_scope(),
        "revision_acceptance_decision_id": "d-1",
        "change_set_lineage_id": "lin-cs-1",
        "selected_change_set_id": "cs-1",
        "expected_latest_decision_id": None,
        "expected_effective_decision_id": None,
        **_NL_BASES,
        "actor_id": "showrunner-1",
    }
    defaults.update(overrides)
    return ChangeSetReviewCommand(**defaults)


def make_conflict_resolution_command(
    *, work_scope: NarrativeWorkScope | None = None, **overrides: Any
) -> ConflictResolutionCommand:
    defaults: dict[str, Any] = {
        "decision_id": "d-3",
        "action": "RESOLVE",
        "work_scope": work_scope or make_narrative_work_scope(),
        "revision_acceptance_decision_id": "d-1",
        "conflict_resolution_lineage_id": "lin-conflict-1",
        "competing_change_set_ids": ("cs-1", "cs-2"),
        "competing_review_decision_ids": ("d-2", "d-2b"),
        "chosen_resolution": "keep cs-1",
        "expected_latest_decision_id": None,
        "expected_effective_decision_id": None,
        **_NL_BASES,
        "actor_id": "showrunner-1",
    }
    defaults.update(overrides)
    return ConflictResolutionCommand(**defaults)


def make_compilation_attempt(*, work_scope: NarrativeWorkScope | None = None, **overrides: Any) -> CompilationAttempt:
    defaults: dict[str, Any] = {
        "attempt_id": "cattempt-1",
        "generation": 0,
        "work_scope": work_scope or make_narrative_work_scope(),
        "revision_id": "rev-1",
        "revision_acceptance_decision_id": "d-1",
        "selected_change_sets": (CompilationSelectedChangeSet(change_set_id="cs-1", review_decision_id="d-2"),),
        "conflict_resolution_decision_ids": (),
        "observed_effective_heads": (ObservedEffectiveHead(decision_id="d-1", effective_generation=1),),
        **_NL_BASES,
        "creative_policy_ref": "policy-1",
        "creative_policy_version": "1",
        "compiler_version": "compiler-1",
        "requested_canon_delta_id": "delta-1",
        "delta_created_at": NARRATIVE_LIFECYCLE_NOW,
        "delta_created_by": "showrunner-1",
        "admitted_at": NARRATIVE_LIFECYCLE_NOW,
        "admitted_by": "showrunner-1",
        "input_fingerprint": "cif-1",
    }
    defaults.update(overrides)
    return CompilationAttempt(**defaults)


def make_compilation_result(**overrides: Any) -> CompilationResult:
    defaults: dict[str, Any] = {
        "result_id": "cres-1",
        "attempt_id": "cattempt-1",
        "generation": 0,
        "outcome": "ABSTAINED",
        "canon_delta_id": None,
        "canon_delta_payload_hash": None,
        "diagnostics": (),
        "completed_at": NARRATIVE_LIFECYCLE_NOW,
        "output_fingerprint": "of-cres",
    }
    defaults.update(overrides)
    return CompilationResult(**defaults)


def make_compiled_canon_delta_evidence(**overrides: Any) -> CompiledCanonDeltaEvidence:
    from r2.narrative.hashing import seal_canon_delta

    canon_delta = overrides.pop("canon_delta", None)
    if canon_delta is None:
        from r2.contracts.narrative import AddFactOperation, CanonDeltaPayload, Fact

        canon_delta = seal_canon_delta(
            CanonDeltaPayload(
                canon_delta_id="delta-1",
                target_branch_id="branch-1",
                base_canon_version_id="cv-1",
                operations=[
                    AddFactOperation(
                        operation_id="op-1",
                        target_id="fact-1",
                        fact=Fact(
                            fact_id="fact-1",
                            subject_ref="hero",
                            predicate="mood",
                            value="calm",
                            effective_from=NARRATIVE_LIFECYCLE_NOW,
                        ),
                    )
                ],
                source_change_set_refs=["cs-1"],
                author_decision_refs=["d-1"],
                validation_report_refs=[],
                created_at=NARRATIVE_LIFECYCLE_NOW,
                created_by="showrunner-1",
            )
        )
    defaults: dict[str, Any] = {
        "compilation_result_id": "cres-1",
        "compilation_attempt_id": "cattempt-1",
        "generation": 0,
        "canon_delta": canon_delta,
        "canon_delta_payload_hash": canon_delta.payload_hash,
        "stored_at": NARRATIVE_LIFECYCLE_NOW,
    }
    defaults.update(overrides)
    return CompiledCanonDeltaEvidence(**defaults)

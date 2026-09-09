from __future__ import annotations

from datetime import UTC, datetime

import pytest

from r2.contracts import NarrativeContextRequest, SceneContract, SceneContractV2, SceneTemporalWindow
from r2.narrative_context.compiler import NarrativeContextCompiler
from r2.narrative_context.errors import NarrativeContextValidationError

FROM = datetime(2026, 3, 1, 10, tzinfo=UTC)
UNTIL = datetime(2026, 3, 1, 12, tzinfo=UTC)
_WINDOW = SceneTemporalWindow(effective_from=FROM, effective_until=UNTIL)


def _request(*, mode: str = "AUTHOR_DRAFT", pov: str | None = None) -> NarrativeContextRequest:
    return NarrativeContextRequest(
        user_id="u1",
        project_name="proj",
        canon_branch_id="main",
        canon_version_id="canon-v1",
        plan_id="plan-1",
        plan_version=1,
        scene_contract_id="scene-1",
        scene_contract_version=1,
        creative_policy_ref="policy-1",
        creative_policy_version="v1",
        mode=mode,
        pov_subject_entity_id=pov,
        story_time=FROM,
        token_budget=200,
        compiler_version="compiler-v1",
        retrieval_snapshot_ref=None,
    )


def _v1_scene() -> SceneContract:
    return SceneContract(
        scene_contract_id="scene-1",
        version=1,
        semantic_hash="sh:x",
        sequence_index=0,
        purpose="p",
        pov=None,
        location_ref=None,
        temporal_window=_WINDOW,
    )


def _v2_scene(*, pov: str | None, omni: bool) -> SceneContractV2:
    return SceneContractV2(
        scene_contract_id="scene-1",
        version=1,
        semantic_hash="sh:x",
        semantic_hash_version="r2-scene-contract-content-v2",
        sequence_index=0,
        purpose="p",
        pov=pov,
        location_ref=None,
        temporal_window=_WINDOW,
        omniscient_authoring_allowed_by_scene=omni,
    )


def _make_scene(kind: str, *, pov: str | None, omni: bool):
    return _v1_scene() if kind == "v1" else _v2_scene(pov=pov, omni=omni)


@pytest.mark.parametrize(
    ("scene_kind", "scene_pov", "omni", "expected"),
    [
        ("v1", None, False, "SCENE_OMNISCIENT_AUTHORING_FORBIDDEN"),
        ("v2", None, False, "SCENE_OMNISCIENT_AUTHORING_FORBIDDEN"),
        ("v2", "hero", True, "SCENE_OMNISCIENT_AUTHORING_FORBIDDEN"),  # scene has a fixed POV
        ("v2", None, True, "AUTHOR_DRAFT_POLICY_CAPABILITY_UNAVAILABLE"),
    ],
)
def test_no_pov_author_draft_gate(scene_kind: str, scene_pov: str | None, omni: bool, expected: str) -> None:
    with pytest.raises(NarrativeContextValidationError) as exc:
        NarrativeContextCompiler._gate_omniscient_author_draft(
            _request(), _make_scene(scene_kind, pov=scene_pov, omni=omni)
        )
    assert expected in str(exc.value)


def test_character_simulation_request_is_unaffected_by_the_gate() -> None:
    result = NarrativeContextCompiler._gate_omniscient_author_draft(
        _request(mode="CHARACTER_SIMULATION", pov="hero"), _v2_scene(pov=None, omni=True)
    )
    assert result is None


def test_a_povd_author_draft_request_is_unaffected_by_the_gate() -> None:
    result = NarrativeContextCompiler._gate_omniscient_author_draft(
        _request(mode="AUTHOR_DRAFT", pov="hero"), _v1_scene()
    )
    assert result is None


async def test_gate_short_circuits_before_any_author_only_material_is_read() -> None:
    class _Exploding:
        def __getattr__(self, name: str):
            async def _boom(*_a: object, **_k: object) -> object:
                raise AssertionError(f"{name!r} must not run once the omniscient gate rejects the request")

            return _boom

    class _Canon:
        async def get_exact(self, *, branch_id, canon_version_id, project_name, user_id):
            _ = (branch_id, project_name, user_id)
            return _resolved_view() if canon_version_id == "canon-v1" else None

    class _Plan:
        async def get_exact_plan(self, *, plan_id, plan_version, project_name, user_id):
            _ = (project_name, user_id)
            return _plan() if (plan_id, plan_version) == ("plan-1", 1) else None

        async def get_exact_scene(self, *, plan_id, plan_version, scene_contract_id, scene_contract_version, **kw):
            _ = (plan_id, plan_version, scene_contract_id, scene_contract_version, kw)
            return _v1_scene()

    class _Counter:
        version = "wc-v1"

        def count(self, content: str) -> int:
            return len(content.split())

    compiler = NarrativeContextCompiler(
        canon_reader=_Canon(),
        plan_reader=_Plan(),
        policy_reader=_Exploding(),
        accepted_reader=_Exploding(),
        snapshot_reader=_Exploding(),
        token_counter=_Counter(),
    )
    with pytest.raises(NarrativeContextValidationError) as exc:
        await compiler.compile(_request())
    assert "SCENE_OMNISCIENT_AUTHORING_FORBIDDEN" in str(exc.value)


def _resolved_view():
    from r2.contracts import CanonContent
    from r2.narrative.canon_state import ResolvedCanonView

    content = CanonContent(entities_by_id={}, facts_by_id={}, events_by_id={})
    return ResolvedCanonView(
        canon_version_id="canon-v1",
        branch_id="main",
        content_hash="scene-eval",
        content_schema_version="r2-canon-schema-v2",
        content=content,
    )


def _plan():
    from r2.contracts import CanonBasis, NarrativePlan, NarrativePlanContent

    content = NarrativePlanContent(
        canon_basis=CanonBasis(branch_id="main", canon_version_id="canon-v1"), story_frame="frame"
    )
    return NarrativePlan(
        plan_id="plan-1",
        version=1,
        content=content,
        content_hash="np:x",
        committed_at=FROM,
        committed_by="lead",
        approval_ref="ap-1",
    )

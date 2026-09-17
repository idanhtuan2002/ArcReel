"""Pure SceneContract / NarrativePlan v1 to v2 schema-transition ratchets.

A v1 lineage stays verifiable under v1 and is never rewritten in place. A lineage that
reaches v2 never downgrades, even after its v2-only lists later become empty. The base
selector is always supplied by the caller; it is never inferred from whether the v2-only
lists happen to be empty.
"""

from __future__ import annotations

from r2.contracts.narrative_plan import SceneContractV2, SceneContractValue
from r2.narrative.errors import NarrativePlanSchemaVersionError

_SCENE_V1 = "r2-scene-contract-content-v1"
_SCENE_V2 = "r2-scene-contract-content-v2"
_PLAN_V1 = "r2-narrative-plan-v1"
_PLAN_V2 = "r2-narrative-plan-v2"

_KNOWN_SCENE: frozenset[str] = frozenset({_SCENE_V1, _SCENE_V2})
_KNOWN_PLAN: frozenset[str] = frozenset({_PLAN_V1, _PLAN_V2})

# ``None`` means genesis (no prior version). ``v2 -> v1`` is absent: a v2 lineage never
# downgrades. ``v1 -> v1`` and ``genesis -> v1`` stay legal, but only for content whose
# minimum selector is still v1 (checked separately against ``content_minimum``).
_LEGAL_SCENE: frozenset[tuple[str | None, str]] = frozenset(
    {
        (None, _SCENE_V1),
        (None, _SCENE_V2),
        (_SCENE_V1, _SCENE_V1),
        (_SCENE_V1, _SCENE_V2),
        (_SCENE_V2, _SCENE_V2),
    }
)
_LEGAL_PLAN: frozenset[tuple[str | None, str]] = frozenset(
    {
        (None, _PLAN_V1),
        (None, _PLAN_V2),
        (_PLAN_V1, _PLAN_V1),
        (_PLAN_V1, _PLAN_V2),
        (_PLAN_V2, _PLAN_V2),
    }
)


def minimum_scene_selector(scene: SceneContractValue) -> str:
    """The lowest scene selector whose byte domain can still represent ``scene``.

    Returns ``r2-scene-contract-content-v2`` when the scene carries any v2-only semantic
    (a ``RELATIONSHIP`` or ``THREAD`` constraint in either state list, or
    ``omniscient_authoring_allowed_by_scene`` set), otherwise ``...-v1``. A v2 scene with
    no v2-only semantic still reports a v1 minimum; the ratchet, not the minimum, is what
    forbids that lineage from downgrading.
    """
    if isinstance(scene, SceneContractV2):
        if scene.omniscient_authoring_allowed_by_scene:
            return _SCENE_V2
        for constraint in (*scene.entry_state_constraints, *scene.exit_state_targets):
            if constraint.constraint_kind in ("RELATIONSHIP", "THREAD"):
                return _SCENE_V2
    return _SCENE_V1


def require_scene_schema_transition(*, from_selector: str | None, to_selector: str, content_minimum: str) -> None:
    """Raise ``NarrativePlanSchemaVersionError`` unless the scene ratchet permits the move.

    Rejects: an unknown selector, an illegal transition (including any ``v2 -> v1``
    downgrade), and a ``to_selector`` below ``content_minimum``.
    """
    for selector in (from_selector, to_selector, content_minimum):
        if selector is not None and selector not in _KNOWN_SCENE:
            raise NarrativePlanSchemaVersionError(f"unknown scene selector {selector!r}")
    if (from_selector, to_selector) not in _LEGAL_SCENE:
        raise NarrativePlanSchemaVersionError(f"illegal scene schema transition {from_selector!r} -> {to_selector!r}")
    if to_selector == _SCENE_V1 and content_minimum == _SCENE_V2:
        raise NarrativePlanSchemaVersionError(
            "scene content carries a v2-only semantic; the v1 selector is below minimum"
        )


def require_plan_schema_transition(*, from_selector: str | None, to_selector: str, contains_v2_scene: bool) -> None:
    """Raise ``NarrativePlanSchemaVersionError`` unless the plan ratchet permits the move.

    Rejects: an unknown selector, an illegal transition (including any ``v2 -> v1``
    downgrade), and a ``v1`` target for a plan that contains any v2 scene member.
    """
    for selector in (from_selector, to_selector):
        if selector is not None and selector not in _KNOWN_PLAN:
            raise NarrativePlanSchemaVersionError(f"unknown plan selector {selector!r}")
    if (from_selector, to_selector) not in _LEGAL_PLAN:
        raise NarrativePlanSchemaVersionError(f"illegal plan schema transition {from_selector!r} -> {to_selector!r}")
    if to_selector == _PLAN_V1 and contains_v2_scene:
        raise NarrativePlanSchemaVersionError("plan contains a v2 scene member; the v1 plan selector is below minimum")

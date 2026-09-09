"""Public NarrativePlan authority API.

Write ports, unit-of-work protocols, and mutable write primitives are deliberately
NOT re-exported here: they live in ``r2.narrative_plan.ports`` and are typed against
only by ``NarrativePlanService`` and the Host adapter, so the public facade cannot be
used to assemble a second authority path. Read-only surfaces (validation, hashing,
integrity, the exact Canon read protocol, and the sole commit service) are public.
"""

from .errors import (
    NarrativePlanApprovalError,
    NarrativePlanError,
    NarrativePlanIdentityConflictError,
    NarrativePlanNotFoundError,
    NarrativePlanValidationError,
    NarrativePlanVersionConflict,
)
from .hashing import compute_plan_content_hash, compute_scene_semantic_hash
from .integrity import NarrativePlanIntegrityChecker
from .ports import CanonVersionReader, NarrativePlanReadPort
from .service import NarrativePlanService
from .validation import SceneVersionCheck, next_scene_version, validate_plan_hierarchy, validate_scene_version

__all__ = [
    "CanonVersionReader",
    "NarrativePlanApprovalError",
    "NarrativePlanError",
    "NarrativePlanIdentityConflictError",
    "NarrativePlanIntegrityChecker",
    "NarrativePlanNotFoundError",
    "NarrativePlanReadPort",
    "NarrativePlanService",
    "NarrativePlanValidationError",
    "NarrativePlanVersionConflict",
    "SceneVersionCheck",
    "compute_plan_content_hash",
    "compute_scene_semantic_hash",
    "next_scene_version",
    "validate_plan_hierarchy",
    "validate_scene_version",
]

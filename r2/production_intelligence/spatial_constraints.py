"""Apply one verified spatial constraint set to a provider-neutral PromptPlan (ADR-0102 decision 4).

Only typed VISIBLE constraints enter the semantic environment intent. INFERRED and GAP rows are
carried as coverage warnings, never as scene facts, and no topology is added without a set.
"""

from __future__ import annotations

from r2.contracts import PromptPlan
from r2.contracts.spatial_constraint import SpatialConstraintSetV1, SpatialConstraintV1
from r2.production_binding.spatial_set import spatial_constraint_set_digest, spatial_constraint_set_id

SPATIAL_PROMPT_CONSUMER_VERSION = "m8c-spatial-constraints-v1"


def constraint_line(constraint: SpatialConstraintV1) -> str:
    if constraint.relation_kind == "PRESERVE_ON_WALL":
        return f"Keep the {constraint.subject_ref} on the {constraint.wall} wall."
    return f"Show the {constraint.subject_ref} on the {constraint.wall} wall where both views meet."


def apply_spatial_constraints(plan: PromptPlan, constraint_set: SpatialConstraintSetV1) -> PromptPlan:
    digest = spatial_constraint_set_digest(constraint_set.model_dump(mode="json"))
    lines = [constraint_line(constraint) for constraint in constraint_set.constraints]
    environment = "\n".join([plan.environment_intent, *lines] if plan.environment_intent else lines)
    requirements = {
        **plan.output_requirements,
        "spatial_constraint_set": {"set_id": spatial_constraint_set_id(digest), "set_digest": digest},
        "spatial_coverage_warnings": [
            {"assertion_id": w.assertion_id, "evidence_class": w.evidence_class.value, "relation": w.relation}
            for w in constraint_set.coverage_warnings
        ],
    }
    return PromptPlan.model_validate(
        {
            **plan.model_dump(mode="json"),
            "environment_intent": environment,
            "output_requirements": requirements,
            "compiler_version": f"{plan.compiler_version}+{SPATIAL_PROMPT_CONSUMER_VERSION}",
        }
    )


__all__ = ["SPATIAL_PROMPT_CONSUMER_VERSION", "apply_spatial_constraints", "constraint_line"]

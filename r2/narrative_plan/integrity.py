"""Executable logical-head and immutable-lineage integrity check for a scoped plan.

``narrative_plans.head_version`` is a logical pointer with no physical foreign key;
this checker compensates. It reads only through ``NarrativePlanReadPort``, collects
findings rather than repairing, and never selects a fallback version.
"""

from __future__ import annotations

from r2.contracts import (
    NarrativeValidationFinding,
    NarrativeValidationReport,
    NarrativeValidationSeverity,
)

from .ports import NarrativePlanReadPort

PLAN_INTEGRITY_RULE_ORDER: tuple[str, ...] = (
    "PLAN_HEAD_MISSING_OR_OUT_OF_SCOPE",
    "PLAN_HEAD_NULL_WITH_VERSIONS",
    "PLAN_HEAD_NOT_LATEST",
    "PLAN_VERSION_GAP",
    "PLAN_VERSION_PARENT_MISMATCH",
)
_RULE_INDEX = {rule_id: index for index, rule_id in enumerate(PLAN_INTEGRITY_RULE_ORDER)}


def _finding(rule_id: str, refs: tuple[str, ...], message: str) -> NarrativeValidationFinding:
    return NarrativeValidationFinding(
        rule_id=rule_id,
        severity=NarrativeValidationSeverity.ERROR,
        affected_refs=refs,
        message=message,
    )


class NarrativePlanIntegrityChecker:
    def __init__(self, repository: NarrativePlanReadPort) -> None:
        self._repository = repository

    async def check_plan(self, *, plan_id: str, project_name: str, user_id: str) -> NarrativeValidationReport:
        findings: list[NarrativeValidationFinding] = []
        head = await self._repository.get_plan_head(plan_id=plan_id, project_name=project_name, user_id=user_id)
        versions = await self._repository.list_plan_versions(
            plan_id=plan_id, project_name=project_name, user_id=user_id
        )
        numbers = [version.version for version in versions]

        if numbers != list(range(1, len(versions) + 1)):
            findings.append(
                _finding("PLAN_VERSION_GAP", (plan_id,), f"plan {plan_id!r} version numbers are not 1..N: {numbers}")
            )

        for version in versions:
            expected = None if version.version == 1 else version.version - 1
            if version.parent_version != expected or version.content.parent_version != expected:
                findings.append(
                    _finding(
                        "PLAN_VERSION_PARENT_MISMATCH",
                        (plan_id, str(version.version)),
                        f"plan {plan_id!r} version {version.version} row/content parent_version is not {expected!r}",
                    )
                )

        if head is not None and head.head_version is None and versions:
            findings.append(
                _finding(
                    "PLAN_HEAD_NULL_WITH_VERSIONS",
                    (plan_id,),
                    f"plan {plan_id!r} head is null while {len(versions)} versions exist",
                )
            )
        elif head is not None and head.head_version is not None:
            head_row = await self._repository.get_version(
                plan_id=plan_id, version=head.head_version, project_name=project_name, user_id=user_id
            )
            if head_row is None:
                findings.append(
                    _finding(
                        "PLAN_HEAD_MISSING_OR_OUT_OF_SCOPE",
                        (plan_id, str(head.head_version)),
                        f"plan {plan_id!r} head {head.head_version} does not resolve in scope",
                    )
                )
            elif numbers and head.head_version != numbers[-1]:
                findings.append(
                    _finding(
                        "PLAN_HEAD_NOT_LATEST",
                        (plan_id, str(head.head_version)),
                        f"plan {plan_id!r} head {head.head_version} is not the greatest version {numbers[-1]}",
                    )
                )

        findings.sort(key=lambda finding: (_RULE_INDEX[finding.rule_id], finding.affected_refs))
        return NarrativeValidationReport(findings=tuple(findings))

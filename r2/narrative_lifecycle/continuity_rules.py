"""Clean-room Python port of the Novel Studio ``hardRules.ts`` deterministic
continuity checks and stable report merge.

Donor pin: ``YfengJ/novel-studio-ai@9b690ae2e2f6921f9bd2782b42cef53c1662ad3b``
``src/lib/continuity/hardRules.ts`` (source SHA-256
``7756c4093b52e11e3f591c58af1719887428fd5e437f4ade0828533ac3663954``). Behaviour is
matched to the unmodified source and verified through the Node parity harness
(``tests/integration/donor_parity``). This module is pure: it produces deterministic
continuity findings over an explicit input snapshot and never becomes a
``NarrativeChangeSet`` or Canon state.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

# ``re.ASCII`` restricts case-insensitive folding to ASCII, matching ECMAScript ``/i``
# (no ``u`` flag): the donor regex does NOT fold ``İ`` / ``ı`` / ``ſ`` to ``i`` / ``s``,
# whereas bare Python ``re.IGNORECASE`` would. The Han alternatives still match literally.
_STORY_RESURRECTION_RE = re.compile(r"复活|亡者|死而复生|undead|resurrection", re.IGNORECASE | re.ASCII)
_OUTLINE_RESURRECTION_RE = re.compile(r"复活|亡者归来|死而复生|undead|resurrection", re.IGNORECASE | re.ASCII)

_BLOCKING_SEVERITIES = frozenset({"high", "critical"})


@dataclass(frozen=True)
class ContinuityIssue:
    """One deterministic continuity finding. ``type`` mirrors the donor field name."""

    severity: str
    type: str
    description: str
    evidence: str
    suggested_fix: str


@dataclass(frozen=True)
class ContinuityReport:
    """A frozen ordered continuity report. ``passed`` mirrors the donor ``pass`` field."""

    passed: bool
    issues: tuple[ContinuityIssue, ...]


def _stringify(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _nullish_str(value: object) -> str:
    """``String(value ?? "")`` — null/undefined become the empty string."""
    return "" if value is None else str(value)


def _story_allows_resurrection(context_pack: Mapping[str, object]) -> bool:
    return bool(_STORY_RESURRECTION_RE.search(_stringify(context_pack.get("storyBible"))))


def _outline_requires_resurrection(context_pack: Mapping[str, object]) -> bool:
    text = f"{_stringify(context_pack.get('chapterOutline'))} {_stringify(context_pack.get('sceneBeats'))}"
    return bool(_OUTLINE_RESURRECTION_RE.search(text))


def run_hard_rule_checks(context_pack: Mapping[str, object], draft_text: str) -> tuple[ContinuityIssue, ...]:
    """Return the ordered critical continuity issues for ``draft_text`` under ``context_pack``."""
    issues: list[ContinuityIssue] = []
    can_use_dead = _story_allows_resurrection(context_pack) and _outline_requires_resurrection(context_pack)

    active_states = context_pack.get("activeCharacterStates") or []
    if isinstance(active_states, Sequence) and not isinstance(active_states, (str, bytes)):
        for state in active_states:
            state_map = state if isinstance(state, Mapping) else {}
            alive = _nullish_str(state_map.get("alive_status"))
            name = _nullish_str(state_map.get("name"))
            if not name or alive != "dead" or name not in draft_text or can_use_dead:
                continue
            issues.append(
                ContinuityIssue(
                    severity="critical",
                    type="dead_character_appears",
                    description=f"角色 {name} 当前状态为 dead，但草稿中出现了可能的正常行动或出场。",
                    evidence=name,
                    suggested_fix=(
                        "删除该角色正常行动，改为回忆/幻象/尸体线索，或在章节细纲与设定圣经中明确复活机制。"
                    ),
                )
            )

    forbidden_list = context_pack.get("forbiddenContradictions") or []
    if isinstance(forbidden_list, Sequence) and not isinstance(forbidden_list, (str, bytes)):
        issues.extend(
            ContinuityIssue(
                severity="critical",
                type="forbidden_contradiction",
                description=f"草稿触碰 Story Bible 禁止违背事项：{forbidden}",
                evidence=forbidden,
                suggested_fix="按 Story Bible 最高优先级重写相关段落。",
            )
            for forbidden in forbidden_list
            if forbidden and isinstance(forbidden, str) and forbidden in draft_text
        )

    return tuple(issues)


def merge_continuity_reports(
    model_report: ContinuityReport, hard_issues: Sequence[ContinuityIssue]
) -> ContinuityReport:
    """Concatenate model issues then hard issues; pass only if no issue is high/critical
    and the model report already passed."""
    issues = (*model_report.issues, *hard_issues)
    passed = all(issue.severity not in _BLOCKING_SEVERITIES for issue in issues) and model_report.passed
    return ContinuityReport(passed=passed, issues=issues)

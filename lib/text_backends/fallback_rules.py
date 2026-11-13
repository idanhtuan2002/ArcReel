"""Which models a text call may use (ADR-0139): an open run's own script model, and which fallbacks.

The fallback list is the project's settings, edited freely. A call made for an automatic run is also held to that
run's rules, which the worker sets for the task it executes: no cloud model under a local-only policy, and none of the
run's reviewers (a reviewer never writes what it reviews). Everywhere, a cloud model needs the per-call ceiling the
settings require.
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class FallbackRules:
    local_only: bool = False
    #: Model identities that may never take a fallback's place (the run's reviewers).
    excluded_identities: frozenset[str] = field(default_factory=frozenset)
    #: The run's frozen script model (provider, model): a run's script work stays on it whatever the project's
    #: settings say now, so a new default applies from the next run and never stops an open one.
    text_route: tuple[str, str] | None = None


RUN_FALLBACK_RULES: ContextVar[FallbackRules | None] = ContextVar("run_fallback_rules", default=None)


@contextmanager
def run_fallback_rules(rules: FallbackRules | None) -> Generator[None]:
    """Hold the calls made inside to ``rules`` (``None``: no run)."""
    token = RUN_FALLBACK_RULES.set(rules)
    try:
        yield
    finally:
        RUN_FALLBACK_RULES.reset(token)


def allowed_fallback(entry: dict[str, Any], rules: FallbackRules | None = None) -> bool:
    """Whether a settings fallback entry may be used under ``rules`` (default: the current run's, if any)."""
    rules = rules if rules is not None else RUN_FALLBACK_RULES.get() or FallbackRules()
    local = entry.get("local") is True
    if not local and (rules.local_only or not entry.get("max_cost_per_call")):
        return False
    return entry.get("model_identity") not in rules.excluded_identities


__all__ = ["RUN_FALLBACK_RULES", "FallbackRules", "allowed_fallback", "run_fallback_rules"]
